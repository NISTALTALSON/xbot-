"""AISecurityDaily v5 reach layer.

Adds, on top of bot.py (v4):
  * rank_entries   - post the story that matters most, not a random one
  * generate_post  - hook-first copy in rotating formats (Gemini, JSON out)
  * compose_post   - fits hook + body + link inside Bluesky's limit
  * analytics      - records every post, pulls likes/reposts/replies back,
                     and shifts future format choice toward what performs
Everything here fails soft: if anything breaks, bot.py falls back to v4 behaviour.
"""
import calendar
import json
import os
import random
import re
import time
from datetime import datetime, timezone

import requests

ANALYTICS_FILE = "analytics.json"
MAX_TRACKED = 400

# UTC hours with a post. Starting set for an India + Europe + US audience;
# the analytics report prints per-hour results so this can be tuned from data.
POST_HOURS_UTC = {int(h) for h in os.environ.get("POST_HOURS_UTC", "4,7,11,13,16,20").split(",") if h.strip()}

FORMATS = {
    "release": "A release breakdown for AI engineers: lead with the model or product name and the single most important capability or number, then what actually changes for people building with it.",
    "builder": "A practical builder angle: how an engineer could use this, what it costs or limits, or the tradeoff to know before adopting it.",
    "compare": "What is different versus before: the concrete change (capability, price, context length, speed) that matters, not marketing language.",
    "reality": "A grounded hype check: what is genuinely new here and what the headline does not prove. Only state limits that follow from the excerpt.",
    "take": "A sharp, defensible opinion on what this signals for where AI is heading, backed by one fact from the story.",
    "plain": "Explain what happened in plain English with one accurate analogy and zero jargon.",
    "question": "State the news in one punchy line, then end with a real question AI engineers would debate.",
    "stakes": "Lead with the most striking concrete fact or number and who is exposed or affected.",
    "action": "Lead with who is affected, then one thing the reader can do today (patch, rotate, disable, try, check).",
}
FOLLOWUP_FORMATS = {"release", "builder", "compare", "stakes", "action"}
KIND_FORMATS = {
    "release": ["release", "builder", "compare", "reality", "take"],
    "ai": ["builder", "take", "plain", "reality", "question", "release"],
    "paper": ["plain", "builder", "take", "question"],
    "other": ["stakes", "action", "take", "plain", "question"],
}
AI_CATS = {"artificial_intelligence"}
AI_WORDS = {
    "gpt-": 5, "gpt ": 2, "claude": 5, "gemini": 5, "llama": 5, "qwen": 5, "deepseek": 5, "mistral": 4,
    "grok": 3, "openai": 4, "anthropic": 4, "deepmind": 4, "hugging face": 3, "open-weight": 5,
    "open weights": 5, "open-source model": 5, "language model": 4, "llm": 4, "foundation model": 4,
    "benchmark": 3, "state-of-the-art": 3, "sota": 3, "agent": 3, "agentic": 4, "mcp": 3,
    "model context protocol": 4, "reasoning model": 5, "fine-tun": 3, "context window": 4, "inference": 3,
    "multimodal": 3, "embedding": 2, "transformer": 2, "diffusion": 2, "copilot": 2, "coding agent": 4,
    "ai model": 4, "generative ai": 3, "pricing": 1, "gpu": 2, "eval": 2, "rag": 2,
}
RELEASE_RX = re.compile(r"\b(introducing|announcing|launch(?:es|ed)?|releas(?:es|ed|ing)|unveil(?:s|ed)?|"
                        r"now available|rolls? out|open[- ]sources?|debuts?)\b", re.I)
VERSION_RX = re.compile(r"\b(v?\d+\.\d+|gpt-?\d\S*|claude[\s-]\w+|gemini[\s-]\d\S*|llama[\s-]?\d\S*|qwen[\s-]?\d\S*)", re.I)
PRIMARY = ("openai.com", "deepmind", "anthropic.com", "huggingface.co", "mistral.ai", "blog.google",
           "developer.nvidia.com", "blogs.nvidia.com", "ai.meta.com", "simonwillison.net", "latent.space",
           "interconnects.ai")

HOT = {
    "zero-day": 6, "0-day": 6, "actively exploited": 7, "exploited in the wild": 7,
    "cve-20": 4, "critical": 3, "remote code execution": 4, "rce": 3, "ransomware": 4,
    "data breach": 4, "breach": 3, "supply chain": 4, "backdoor": 3, "vulnerability": 2,
    "patch": 2, "malware": 2, "jailbreak": 3, "prompt injection": 4, "ai agent": 2,
    "llm": 2, "leak": 2, "cisa": 3, "nation-state": 3, "apt": 2, "botnet": 2, "exploit": 2,
}
JUNK = ("sponsored", "webinar", "podcast", "weekly recap", "week in review", "newsletter",
        "top 10", "top 5", "best of", "job", "hiring", "register now", "giveaway")
STOP = set("the a an of to in on for and or is are was be by with from at as it its this that new how why what after over into".split())


# ---------------------------------------------------------------- ranking
def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9\-]+", title.lower()) if len(w) > 3 and w not in STOP}


def _age_hours(entry):
    e = entry.get("_entry") or {}
    t = e.get("published_parsed") or e.get("updated_parsed")
    if not t:
        return None
    return max(0.0, (time.time() - calendar.timegm(t)) / 3600)


def _ai_hits(text):
    return sum(w for k, w in AI_WORDS.items() if k in text)


def story_kind(entry):
    title = entry["title"]
    if "arxiv.org" in entry.get("link", ""):
        return "paper"
    if entry.get("category") in AI_CATS or _ai_hits(title.lower()) >= 4:
        return "release" if (RELEASE_RX.search(title) or VERSION_RX.search(title)) else "ai"
    return "other"


def rank_entries(entries):
    toks = [_tokens(e["title"]) for e in entries]
    scored = []
    for i, e in enumerate(entries):
        text = (e["title"] + " " + (e.get("summary") or "")[:300]).lower()
        link = e.get("link", "")
        s = sum(w for k, w in HOT.items() if k in text)
        ai = _ai_hits(text)
        s += min(14, ai)
        if e.get("category") in AI_CATS:
            s += 6
        elif ai < 3:
            s -= 8  # off-topic for an AI-focused account unless it is a huge story
        if "arxiv.org" in link and ai < 6:
            s -= 5
        if any(p in link for p in PRIMARY):
            s += 3  # first-party announcements and expert blogs outperform rewrites
        if RELEASE_RX.search(e["title"]):
            s += 4
        if VERSION_RX.search(e["title"]):
            s += 2
        s -= 6 * sum(1 for j in JUNK if j in e["title"].lower())
        age = _age_hours(e)
        if age is not None:
            s += 4 if age < 6 else 2 if age < 24 else 0 if age < 48 else -3 if age < 72 else -8
        same = sum(1 for j, t in enumerate(toks) if j != i and toks[i] and t and
                   len(toks[i] & t) / len(toks[i] | t) >= 0.4)
        s += min(9, 3 * same)  # several outlets covering it = it matters
        if re.search(r"\d", e["title"]):
            s += 1
        scored.append((s + random.uniform(0, 2), e))
    scored.sort(key=lambda x: x[0], reverse=True)
    print("   [v5] top stories by score:")
    for s, e in scored[:3]:
        print(f"        {s:5.1f}  [{story_kind(e)}] {e['title'][:66]}")
    return [e for _, e in scored]


# ---------------------------------------------------------------- analytics
def _load():
    try:
        with open(ANALYTICS_FILE, encoding="utf-8") as f:
            d = json.load(f)
            d.setdefault("posts", [])
            return d
    except Exception:
        return {"posts": []}


def _save(d):
    d["posts"] = d["posts"][-MAX_TRACKED:]
    with open(ANALYTICS_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)


def record_post(uri, category, fmt, title, linkpos="root"):
    d = _load()
    now = datetime.now(timezone.utc)
    d["posts"].append({"uri": uri, "ts": now.isoformat(), "hour": now.hour, "category": category,
                       "format": fmt, "linkpos": linkpos, "title": title[:80], "score": 0, "likes": 0,
                       "reposts": 0, "replies": 0, "quotes": 0, "checked": None})
    _save(d)


def refresh_metrics():
    """Pull engagement for posts 3h-14d old from Bluesky's public API (no login needed)."""
    d = _load()
    now = time.time()
    due = []
    for p in d["posts"]:
        age = now - datetime.fromisoformat(p["ts"]).timestamp()
        if 3 * 3600 <= age <= 14 * 86400:
            due.append(p)
    for i in range(0, len(due), 25):
        chunk = due[i:i + 25]
        try:
            r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts",
                             params=[("uris", p["uri"]) for p in chunk], timeout=20)
            r.raise_for_status()
            by_uri = {x["uri"]: x for x in r.json().get("posts", [])}
        except Exception as ex:
            print(f"   [v5] metrics fetch failed: {str(ex)[:60]}")
            break
        for p in chunk:
            x = by_uri.get(p["uri"])
            if not x:
                continue
            p.update(likes=x.get("likeCount", 0), reposts=x.get("repostCount", 0),
                     replies=x.get("replyCount", 0), quotes=x.get("quoteCount", 0))
            p["score"] = p["likes"] + 2 * p["reposts"] + 3 * p["replies"] + 2 * p["quotes"]
            p["checked"] = datetime.now(timezone.utc).isoformat()
    _save(d)


def _avg_by(posts, key):
    agg = {}
    for p in posts:
        if p.get("checked"):
            agg.setdefault(p[key], []).append(p["score"])
    return {k: (sum(v) / len(v), len(v)) for k, v in agg.items()}


def print_report():
    posts = _load()["posts"]
    done = [p for p in posts if p.get("checked")]
    print(f"\n   [v5] ANALYTICS - {len(done)} measured posts of {len(posts)} tracked")
    for key in ("format", "category", "hour", "linkpos"):
        rows = sorted(_avg_by(done, key).items(), key=lambda kv: kv[1][0], reverse=True)[:5]
        print(f"        by {key}: " + ", ".join(f"{k}={a:.1f} (n={n})" for k, (a, n) in rows))
    best = sorted(done, key=lambda p: p["score"], reverse=True)[:3]
    for p in best:
        print(f"        top post: score {p['score']} | {p['format']} | {p['title']}")


def _weighted_pick(key, options):
    stats = _avg_by(_load()["posts"], key)
    weights = []
    for o in options:
        avg, n = stats.get(o, (0, 0))
        weights.append(1.0 + avg if n >= 3 else 2.0)  # unproven options keep getting tried
    return random.choices(options, weights=weights)[0]


def pick_format(entry):
    return _weighted_pick("format", KIND_FORMATS[story_kind(entry)])


def pick_linkpos():
    """A/B test: link in the main post vs. in the self-reply (external links often cut reach)."""
    return _weighted_pick("linkpos", ["root", "reply"])


# ---------------------------------------------------------------- generation
def _gemini_json(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    for model in (os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"), "gemini-2.5-flash"):
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8}},
                timeout=30)
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as ex:
            print(f"   [v5] gemini {model} failed: {str(ex)[:60]}")
    return None


def parse_post_json(raw):
    """Validate model output. Returns dict(hook, body, followup?) or None."""
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        d = json.loads(raw)
    except Exception:
        return None
    hook = str(d.get("hook", "")).strip()
    body = str(d.get("body", "")).strip()
    if len(hook) < 15 or len(body) < 15:
        return None
    if len(hook) > 100:
        hook = hook[:100].rsplit(" ", 1)[0].rstrip(",;:-") + "..."
    out = {"hook": hook, "body": body[:200]}
    fu = str(d.get("followup", "") or "").strip()
    if len(fu) >= 20:
        out["followup"] = fu[:280]
    return out


def generate_post(title, body_text, category, fmt):
    if not body_text:
        return None
    want_fu = fmt in FOLLOWUP_FORMATS
    prompt = (
        "You write for an AI news account on Bluesky covering new models, releases, tooling, research and AI security. "
        "Readers are AI engineers, ML practitioners, developers and curious tech people.\n"
        f"Category: {category.replace('_', ' ')}\nHeadline: {title}\n"
        f"Article excerpt:\n{body_text[:3000]}\n\n"
        f"Post format: {FORMATS[fmt]}\n\n"
        'Return JSON with keys "hook", "body"' + (', "followup"' if want_fu else "") + ".\n"
        '- "hook": first line, max 90 chars. Stop the scroll with a concrete fact, number, name or '
        "consequence from the article. No clickbait, no 'BREAKING', no emoji at the start.\n"
        '- "body": 1-2 sentences, max 170 chars, the why-it-matters or the angle.\n'
        + ('- "followup": max 240 chars, 2-3 short numbered points a builder can act on or remember '
           '(what is new, limits or cost if stated, how to try or apply it). Facts from the excerpt only.\n' if want_fu else "")
        + "\nRules: use ONLY facts present in the excerpt; never invent numbers, names, CVE ids or dates; "
        "if unsure, leave it out. No URLs, hashtags or source names. Plain words, active voice, sound like "
        "a sharp AI engineer sharing what they just read, not a press release. Avoid hype words like revolutionary, game-changing or groundbreaking. At most one emoji in the whole post, only if it adds meaning."
    )
    return parse_post_json(_gemini_json(prompt))


def compose_post(v2, entry, hashtags, count, trunc, limit, link_in_root=True):
    link = entry["link"]
    tag = (hashtags or "").split()[0] if hashtags else ""
    parts_footer = [x for x in (tag, link if link_in_root else "") if x]
    footer = "\n".join(parts_footer)
    hook, body = v2["hook"], v2["body"]
    base = f"{hook}\n\n\n\n{footer}" if footer else f"{hook}\n\n"
    room = limit - count(base)
    if room >= 40:
        if count(body) > room:
            cut = trunc(body, room)
            end = max(cut.rfind(c) for c in ".!?")
            body = cut[:end + 1] if end >= 30 else cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."
        post = f"{hook}\n\n{body}" + (f"\n\n{footer}" if footer else "")
    else:
        post = f"{hook}" + (f"\n\n{footer}" if footer else "")
    if count(post) > limit:
        keep = link if link_in_root else ""
        post = trunc(hook, limit - count(keep) - 2) + (f"\n\n{keep}" if keep else "")
    return post


def reply_text(v2, entry, linkpos, count, trunc, limit):
    """Self-reply under the main post: key points and/or the source link."""
    if not v2:
        return None
    fu = v2.get("followup", "")
    src = f"Source: {entry['link']}" if linkpos == "reply" else ""
    if not (fu or src):
        return None
    if fu and src:
        fu = trunc(fu, limit - count(src) - 2)
    return "\n\n".join(x for x in (fu, src) if x)


# ---------------------------------------------------------------- X drafts (manual posting, free)
URL_RX = re.compile(r"https?://\S+")


def _x_len(text):
    return len(URL_RX.sub("x" * 23, text))  # X counts every link as 23 characters


def build_x_draft(v2, entry, hashtags):
    """Returns (tweet, reply). Link goes in the reply, since links in the main tweet tend to cut reach."""
    tags = " ".join((hashtags or "").split()[:2])
    hook, body = v2["hook"], v2["body"]
    tail = f"\n\n{tags}" if tags else ""
    room = 280 - len(hook) - len(tail) - 2
    if room >= 40:
        if len(body) > room:
            cut = body[:room]
            end = max(cut.rfind(c) for c in ".!?")
            body = cut[:end + 1] if end >= 30 else cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."
        tweet = f"{hook}\n\n{body}{tail}"
    else:
        tweet = f"{hook}{tail}"
    src = f"Source: {entry['link']}"
    fu = v2.get("followup", "")
    if fu and _x_len(fu) + 2 + _x_len(src) > 280:
        fu = fu[:280 - _x_len(src) - 5].rsplit(" ", 1)[0] + "..."
    reply = "\n\n".join(x for x in (fu, src) if x)
    return tweet, reply


def send_x_draft(v2, entry, fmt, hashtags, dry=False):
    """Send a ready-to-paste X post to WhatsApp (CallMeBot) and/or a private Telegram chat."""
    tweet, reply = build_x_draft(v2, entry, hashtags)
    msg = f"X DRAFT [{fmt}]\n\nTWEET:\n{tweet}\n\nREPLY (post under the tweet):\n{reply}"
    if dry:
        print("   ---- X DRAFT (would be sent to WhatsApp/Telegram) ----")
        print(msg)
        return
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    key = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if phone and key:
        try:
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": phone, "text": msg, "apikey": key}, timeout=30)
            print(f"   [v5] X draft -> WhatsApp: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] WhatsApp draft failed: {str(ex)[:60]}")
    sphone = os.environ.get("SIGNAL_PHONE", "").strip()
    skey = os.environ.get("SIGNAL_APIKEY", "").strip()
    if sphone and skey:
        try:
            r = requests.get("https://signal.callmebot.com/signal/send.php",
                             params={"phone": sphone, "apikey": skey, "text": msg}, timeout=30)
            print(f"   [v5] X draft -> Signal: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] Signal draft failed: {str(ex)[:60]}")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "").strip()
    if token and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": msg, "disable_web_page_preview": True}, timeout=20)
            print(f"   [v5] X draft -> Telegram: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] Telegram draft failed: {type(ex).__name__}")
