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

from urllib.parse import urlparse

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
    "outage": 3, "offline": 2, "emergency": 3, "nsa": 3, "enisa": 3, "ncsc": 3, "mass exploitation": 5,
    "emergency patch": 5, "web shell": 3, "wordpress": 2, "critical flaw": 3, "critical vulnerabilit": 3,
    "taken down": 2, "shut down": 2, "worldwide": 1, "millions of": 2,
}
JUNK = ("sponsored", "webinar", "podcast", "weekly recap", "week in review", "newsletter",
        "top 10", "top 5", "best of", "job", "hiring", "register now", "giveaway", "[ainews]", "ainews:")
STOP = set("the a an of to in on for and or is are was be by with from at as it its this that new how why what after over into "
           "has can you and use not but all one get via who may now out say says just than more will".split())


ACTIVE_START, ACTIVE_END = 3, 21  # UTC hours the bot may post in
MIN_GAP_HOURS = float(os.environ.get("MIN_GAP_HOURS", "3.5"))


def should_post_now(now=None):
    """Gap-based gate: GitHub drops/delays cron runs, so post whenever enough time has passed
    since the last post instead of requiring an exact clock hour."""
    now = now or datetime.now(timezone.utc)
    if not (ACTIVE_START <= now.hour < ACTIVE_END):
        return False, f"outside active window ({ACTIVE_START:02d}-{ACTIVE_END:02d} UTC)"
    posts = _load()["posts"]
    if posts:
        gap = (now - datetime.fromisoformat(posts[-1]["ts"])).total_seconds() / 3600
        if gap < MIN_GAP_HOURS:
            return False, f"last post {gap:.1f}h ago (min gap {MIN_GAP_HOURS}h)"
    return True, "ok"


# ---------------------------------------------------------------- ranking
def _tokens(title):
    return {w for w in re.findall(r"[a-z0-9\-]+", title.lower()) if len(w) >= 3 and w not in STOP}


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


def _domain(e):
    try:
        return urlparse(e.get("link", "")).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _same_story(a, b, ratio=0.5):
    sh = a & b
    return len(sh) >= 2 and len(sh) / max(1, min(len(a), len(b))) >= ratio


def _recent_posted(hours=36):
    now = time.time()
    out = []
    for p in _load()["posts"]:
        try:
            age = (now - datetime.fromisoformat(p["ts"]).timestamp()) / 3600
        except Exception:
            continue
        if age <= hours:
            out.append((age, _tokens(p.get("title", ""))))
    return out


def breaking_gap_ok(min_hours=1.0):
    """Breaking news may skip the normal 3.5h gap / night window, but never spams: 1h minimum."""
    posts = _load()["posts"]
    if not posts:
        return True
    gap = (datetime.now(timezone.utc) - datetime.fromisoformat(posts[-1]["ts"])).total_seconds() / 3600
    return gap >= min_hours


def _breaking_clusters(entries, toks, recent):
    """Group the same story across outlets. Several independent outlets in the last 36h on a hot
    topic = breaking news. Returns (breaking flags, indexes to drop because we already covered it)."""
    n = len(entries)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    fresh = []
    for e in entries:
        a = _age_hours(e)
        fresh.append(a is None or a <= 36)
    for i in range(n):
        if not fresh[i] or not toks[i]:
            continue
        for j in range(i + 1, n):
            if fresh[j] and toks[j] and _same_story(toks[i], toks[j], 0.3):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(n):
        if fresh[i]:
            groups.setdefault(find(i), []).append(i)
    flags, drop = [False] * n, set()
    for members in groups.values():
        doms = {_domain(entries[i]) for i in members} - {""}
        text = " ".join(entries[i]["title"].lower() for i in members)
        heat = sum(w for k, w in HOT.items() if k in text)
        if not ((len(doms) >= 3 and heat >= 4) or (len(doms) >= 4 and _ai_hits(text) >= 6)):
            continue
        covered_recently = any(age < 8 and rt and _same_story(toks[m], rt, 0.3)
                               for m in members for age, rt in recent)
        if covered_recently:
            drop.update(members)  # already posted this story in the last 8h; do not spam it
            continue
        for i in members:
            flags[i] = True
        print(f"   [v5] BREAKING cluster: {len(doms)} outlets, heat {heat}: {entries[members[0]]['title'][:60]}")
    return flags, drop


def rank_entries(entries):
    toks = [_tokens(e["title"]) for e in entries]
    recent = _recent_posted(36)
    breaking, drop = _breaking_clusters(entries, toks, recent)
    scored = []
    for i, e in enumerate(entries):
        if i in drop:
            continue
        if not breaking[i] and any(rt and _same_story(toks[i], rt, 0.5) for _, rt in recent):
            continue  # same topic as something we posted in the last 36h
        text = (e["title"] + " " + (e.get("summary") or "")[:300]).lower()
        link = e.get("link", "")
        s = sum(w for k, w in HOT.items() if k in text)
        ai = _ai_hits(text)
        s += min(14, ai)
        if e.get("category") in AI_CATS:
            s += 6
        elif ai < 3 and not breaking[i]:
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
        if breaking[i]:
            s += 40
            e["_breaking"] = True
        s += random.uniform(0, 2)
        e["_score"] = s
        scored.append((s, e))
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
    """Link in the root post or in the last reply. Every tracked post so far had the link in the root and
    the reply variant was never tried, so favour 'reply' until it has enough samples to compare."""
    stats = _avg_by(_load()["posts"], "linkpos")
    if stats.get("reply", (0, 0))[1] < 8:
        return "reply" if random.random() < 0.7 else "root"
    return _weighted_pick("linkpos", ["root", "reply"])


# ---------------------------------------------------------------- generation
LEGAL = ("Legal safety: write in your own words and never copy sentences or distinctive phrasing from the source "
         "(a quoted phrase must be under 12 words and in quotation marks). Report allegations, attacks and "
         "attributions to named people, groups, companies or countries as reported claims ('reportedly', "
         "'researchers say'), never as proven fact. Never name a private individual. Give no legal, medical or "
         "financial advice and never tell anyone to buy or sell anything. Add no fact that is not in the material.\n")


def _gemini_json(prompt):
    import llm
    return llm.generate(prompt, json_mode=True, temperature=0.8, timeout=40)


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


def generate_post(title, body_text, category, fmt, note=None):
    related = (note or {}).get("related") or []
    if not body_text and related:
        body_text = "Headlines from several outlets on this story:\n" + "\n".join(related)
    if not body_text:
        return None
    want_fu = fmt in FOLLOWUP_FORMATS
    extra = ""
    if note and note.get("angle"):
        extra += f"Editor's angle (build the post around this point): {note['angle']}\n"
    if related and body_text and not body_text.startswith("Headlines from several"):
        extra += "Other outlets' headlines on the same story (facts stated here are usable too):\n" + "\n".join(related[:5]) + "\n"
    prompt = (
        "You write for an AI news account on Bluesky covering new models, releases, tooling, research and AI security. "
        "Readers are AI engineers, ML practitioners, developers and curious tech people.\n"
        f"Category: {category.replace('_', ' ')}\nHeadline: {title}\n"
        f"Article excerpt:\n{body_text[:3000]}\n{extra}\n"
        f"Post format: {FORMATS[fmt]}\n\n"
        'Return JSON with keys "hook", "body"' + (', "followup"' if want_fu else "") + ".\n"
        '- "hook": first line, max 90 chars. Stop the scroll with a concrete fact, number, name or '
        "consequence from the article. No clickbait, no 'BREAKING', no emoji at the start.\n"
        '- "body": 1-2 sentences, max 170 chars, the why-it-matters or the angle.\n'
        + ('- "followup": max 240 chars, 2-3 short numbered points a builder can act on or remember '
           '(what is new, limits or cost if stated, how to try or apply it). Facts from the excerpt only.\n' if want_fu else "")
        + "\n" + LEGAL + "Rules: use ONLY facts present in the excerpt or the listed headlines; never invent numbers, names, CVE ids or dates; "
        "if unsure, leave it out. No URLs, hashtags or source names. Plain words, active voice, sound like "
        "a sharp AI engineer sharing what they just read, not a press release. Avoid hype words like revolutionary, game-changing or groundbreaking. At most one emoji in the whole post, only if it adds meaning."
    )
    draft = parse_post_json(_gemini_json(prompt))
    return _critique(draft, title, body_text, note) if draft else draft


def _critique(draft, title, body_text, note):
    """Second look by a harsher reader: is the hook specific, is every fact in the source, would an engineer
    stop scrolling? Rewrites only when the draft is weak. Any failure keeps the original draft."""
    try:
        prompt = (
            "You are a ruthless social-media editor for an AI and AI-security account. Judge this draft post.\n"
            f"Headline: {title}\nSource material:\n{body_text[:2500]}\n"
            + (f"Intended angle: {note['angle']}\n" if note and note.get("angle") else "")
            + f"Draft JSON: {json.dumps(draft)}\n\n"
            'Score 1-10 on: specific hook (concrete fact, not vague), every fact present in the source material, '
            'a reason an engineer would stop scrolling, no hype words, no filler. '
            'Also score 5 or lower and rewrite if it copies sentences from the source, states an allegation as proven fact, names a private individual, or gives advice to buy or sell. '
            'If the score is 8 or higher, return {"score": <n>} only. Otherwise return {"score": <n>, "hook": ..., '
            '"body": ..., "followup": ...} with the same limits (hook max 90 chars, body max 170, followup max 240) '
            "fixing the weaknesses, still using only facts from the source material."
        )
        d = json.loads(re.sub(r"^```(?:json)?|```$", "", (_gemini_json(prompt) or "").strip(), flags=re.M).strip())
        if int(d.get("score", 10)) >= 8:
            return draft
        revised = parse_post_json(json.dumps(d))
        if revised:
            if "followup" in draft and "followup" not in revised:
                revised["followup"] = draft["followup"]
            print(f"   [v6] critic score {d.get('score')}: draft rewritten")
            return revised
    except Exception as ex:
        print(f"   [v6] critic skipped: {str(ex)[:60]}")
    return draft


def compose_post(v2, entry, hashtags, count, trunc, limit, link_in_root=True):
    link = entry["link"]
    tag = ""  # hashtags removed on purpose
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


# ---- X-native package (built from the open-sourced X ranking signals, see README notes in chat)
X_FORMATS = {
    "thread": "A 4-6 tweet breakdown thread. Tweet 1 is the hook. Each following tweet stands alone and is concrete "
              "(names, numbers, tradeoffs from the excerpt). Last tweet: the takeaway plus one open question.",
    "tldr": "ONE tweet: a bold factual first line, then 2-3 short lines (use the - character) of what matters, then one open question.",
    "hot_take": "ONE tweet: a sharp, defensible opinion about what this means for AI builders, backed by one fact from the "
                "excerpt, ending with a question that invites disagreement.",
    "list": "ONE saveable tweet: a one-line hook, then 3-5 short numbered points a builder would bookmark. No question needed.",
    "poll": "ONE tweet that frames the news in one line and asks a poll question, plus 2-4 poll options of at most 25 characters each.",
}
X_KIND = {
    "release": ["thread", "tldr", "list", "hot_take"],
    "ai": ["hot_take", "list", "tldr", "poll", "thread"],
    "paper": ["tldr", "list", "hot_take"],
    "other": ["tldr", "hot_take", "poll"],
}
X_PLAN = ("Post it soon, then stay ~15 min and reply to EVERY comment (author replies are the strongest signal). "
          "Link goes in the reply, never in the tweet.")


def _x_clip(t, limit=275):
    t = t.strip()
    if _x_len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(c) for c in ".!?\n")
    return cut[:end + 1].strip() if end >= 60 else cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."


def pick_x_format(entry):
    opts = X_KIND[story_kind(entry)]
    return random.choices(opts, weights=[len(opts) - i for i in range(len(opts))])[0]


def parse_x_json(raw, fmt):
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        d = json.loads(raw)
    except Exception:
        return None
    tweets = [_x_clip(str(t)) for t in d.get("tweets", []) if str(t).strip()]
    if not tweets or len(tweets[0]) < 20:
        return None
    tweets = tweets[:6] if fmt == "thread" else tweets[:1]
    poll = [str(o).strip()[:25] for o in d.get("poll_options", []) if str(o).strip()][:4]
    return {"tweets": tweets, "poll": poll if fmt == "poll" and len(poll) >= 2 else [],
            "image": str(d.get("image_idea", "") or "")[:160]}


def generate_x_package(entry, body_text, fmt):
    prompt = (
        "You are a top AI-engineering creator on X (Twitter) with a growing audience of AI engineers, ML researchers "
        "and builders. Write ONE post package for the story below.\n"
        f"Headline: {entry['title']}\nArticle excerpt:\n{body_text[:3000]}\n\n"
        f"Format: {X_FORMATS[fmt]}\n\n"
        'Return JSON: {"tweets": [..], "poll_options": [..], "image_idea": ".."}. poll_options only for the poll format.\n'
        "Rules:\n"
        "- Every tweet at most 270 characters. No hashtags, no links, no 'BREAKING', no thread emoji.\n"
        "- Tweet 1 first line: under 70 characters, a concrete fact, number or surprising claim from the excerpt that "
        "makes people stop and read on.\n"
        "- Where a question is called for, ask ONE specific question builders would answer from their own experience "
        "(never 'thoughts?').\n"
        "- Use ONLY facts in the excerpt. Never invent numbers, names, versions or dates. If unsure, leave it out. "
        "Opinions must read clearly as opinion.\n"
        "- Plain words, short lines, line breaks for readability, no hype words (revolutionary, game-changing). "
        "At most one emoji in total.\n"
        '- "image_idea": one short line naming a real screenshot or chart from the article to attach '
        "(benchmark table, pricing table, architecture diagram). Never AI-generated art."
    )
    return parse_x_json(_gemini_json(prompt), fmt)


def build_x_messages(pkg, entry, fmt):
    """Clean, paste-ready messages: each message is EXACTLY the text to paste into X, nothing else.
    Tweets first (one message per tweet), poll options (if any) as bare lines, then the bare link
    as its own message for the reply."""
    tweets = pkg["tweets"]
    msgs = list(tweets)
    if pkg.get("poll"):
        msgs.append("\n".join(pkg["poll"]))
    msgs.append(entry["link"])
    return msgs


def _cm_safe(text):
    """CallMeBot (Signal/WhatsApp) mangles some characters on its server: '$100k' loses '$1' (shell variable)
    and apostrophes get stripped. Defuse both before sending. The zero-width space after '$' is invisible
    and harmless when pasted into X; the typographic apostrophe is what X shows anyway."""
    text = text.replace("'", "\u2019")
    text = text.replace("$", "$\u200b")
    return text


def _deliver(msg):
    """Send one message to every configured channel (Signal / WhatsApp via CallMeBot, Telegram DM)."""
    msg_raw = msg
    sphone = os.environ.get("SIGNAL_PHONE", "").strip()
    skey = os.environ.get("SIGNAL_APIKEY", "").strip()
    if sphone and skey:
        try:
            r = requests.get("https://signal.callmebot.com/signal/send.php",
                             params={"phone": sphone, "apikey": skey, "text": _cm_safe(msg_raw)}, timeout=30)
            print(f"   [v5] X draft -> Signal: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] Signal draft failed: {str(ex)[:60]}")
    phone = os.environ.get("WHATSAPP_PHONE", "").strip()
    key = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if phone and key:
        try:
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": phone, "text": _cm_safe(msg_raw), "apikey": key}, timeout=30)
            print(f"   [v5] X draft -> WhatsApp: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] WhatsApp draft failed: {str(ex)[:60]}")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "").strip()
    if token and chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": msg, "disable_web_page_preview": True}, timeout=20)
            print(f"   [v5] X draft -> Telegram: HTTP {r.status_code}")
        except Exception as ex:
            print(f"   [v5] Telegram draft failed: {type(ex).__name__}")


def send_x_draft(v2, entry, fmt, hashtags, dry=False, body_text=""):
    """Build an X-native post (own prompt and formats) and send it for manual posting."""
    xfmt = pick_x_format(entry)
    pkg = generate_x_package(entry, body_text, xfmt) if body_text else None
    if pkg:
        msgs = build_x_messages(pkg, entry, xfmt)
        print(f"   [v5] X package: format={xfmt}, {len(pkg['tweets'])} tweet(s)")
    else:
        tweet, reply = build_x_draft(v2, entry, "")
        msgs = [tweet, entry["link"]]
        print("   [v5] X package generation failed - sending the fallback draft")
    if dry:
        print("   ---- X DRAFT (would be sent to Signal/WhatsApp/Telegram) ----")
        for m in msgs:
            print(m + "\n   ..")
        return
    for i, m in enumerate(msgs):
        _deliver(m)
        if i < len(msgs) - 1:
            time.sleep(2)  # CallMeBot asks for at most one message per second


# ---------------------------------------------------------------- v6: Bluesky thread (hook -> article -> question -> source)
def generate_thread(title, body_text, category, fmt, note=None):
    """A short native article for Bluesky: scroll-stopping hook + payoff, 3 body posts, closing question."""
    related = (note or {}).get("related") or []
    if not body_text and related:
        body_text = "Headlines from several outlets on this story:\n" + "\n".join(related)
    if not body_text:
        return None
    extra = ""
    if note and note.get("angle"):
        extra += f"Editor's angle (build the thread around this point): {note['angle']}\n"
    if related and not body_text.startswith("Headlines from several"):
        extra += "Other outlets' headlines on the same story (facts stated here are usable too):\n" + "\n".join(related[:5]) + "\n"
    prompt = (
        "You write a Bluesky account for AI engineers and developers. Turn the story below into a short native "
        "THREAD that reads like a mini article, so people get the full value without clicking anything.\n"
        f"Category: {category.replace('_', ' ')}\nHeadline: {title}\n"
        f"Article text:\n{body_text[:6000]}\n{extra}\n"
        f"Angle: {FORMATS[fmt]}\n\n"
        'Return JSON: {"hook": "..", "payoff": "..", "posts": ["..", "..", ".."], "question": "..", "alt": ".."}\n'
        "- hook: max 85 chars. A concrete fact, number, name or consequence from the article that makes a reader "
        "stop. It must work alone. No clickbait, no 'BREAKING', no emoji.\n"
        "- payoff: max 170 chars. Why this matters to someone building or using AI. It teases the thread without "
        "repeating the hook.\n"
        "- posts: exactly 3 replies, each max 270 chars, each adds ONE NEW fact or insight in this order: "
        "(1) what actually happened or changed, (2) how it works or the key number/limit/cost, "
        "(3) who it affects and what to do or watch next. Short lines are fine.\n"
        "- question: max 220 chars. A one-line takeaway, then ONE specific question that builders can answer from "
        "their own experience. Never 'thoughts?', never 'what do you think'.\n"
        "- alt: max 200 chars, plain description of a card image that carries the hook (for screen readers).\n"
        + LEGAL + "Rules: use ONLY facts present in the article text or the listed headlines; never invent numbers, names, versions, CVE ids or dates; "
        "if unsure, leave it out. No URLs, no hashtags, no source names. No engagement bait ('repost if', "
        "'like if', 'follow for more'). No hype words (revolutionary, game-changing, groundbreaking). "
        "Plain words, active voice, a sharp human tone. At most one emoji in the whole thread."
    )
    raw = _gemini_json(prompt)
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        d = json.loads(raw)
    except Exception:
        return None
    hook = str(d.get("hook", "")).strip()
    payoff = str(d.get("payoff", "")).strip()
    posts = [str(p).strip() for p in d.get("posts", []) if len(str(p).strip()) >= 30][:3]
    question = str(d.get("question", "")).strip()
    if len(hook) < 15 or len(payoff) < 20 or len(posts) < 2 or len(question) < 20:
        return None
    low = " ".join([hook, payoff, question] + posts).lower()
    if any(x in low for x in ("repost if", "like if", "follow for more", "retweet", "thoughts?", "what do you think")):
        return None
    return {"hook": hook[:100], "payoff": payoff[:200], "posts": posts, "question": question[:240],
            "alt": str(d.get("alt", "") or hook)[:250]}


def _fit(text, limit, count, trunc):
    if count(text) <= limit:
        return text
    cut = trunc(text, limit)
    end = max(cut.rfind(c) for c in ".!?")
    return cut[:end + 1] if end >= 40 else cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."


def compose_thread(t, entry, hashtags, count, trunc, limit, linkpos):
    """Returns [{'text','kind'}]: root, body posts, question, and (if linkpos == 'reply') a source post."""
    tag = ""  # hashtags removed on purpose
    link = entry["link"]
    foot = "\n".join(x for x in (tag, link if linkpos == "root" else "") if x)
    root = f"{t['hook']}\n\n{t['payoff']}"
    if foot and count(root) + count(foot) + 2 > limit:
        root = _fit(root, limit - count(foot) - 2, count, trunc)
    root = root + (f"\n\n{foot}" if foot else "")
    out = [{"text": root, "kind": "root"}]
    for p in t["posts"]:
        out.append({"text": _fit(p, limit, count, trunc), "kind": "body"})
    out.append({"text": _fit(t["question"], limit, count, trunc), "kind": "question"})
    if linkpos == "reply":
        out.append({"text": f"Source: {entry['source']}\n{link}", "kind": "source"})
    return out


# ---------------------------------------------------------------- v6: images
def prep_image(raw, max_w=1200, max_bytes=900_000):
    """Re-encode any downloaded image to a JPEG Bluesky will accept (<1MB). None if unusable or tiny."""
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(raw)).convert("RGB")
        if im.width < 400 or im.height < 200:
            return None
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)))
        for qual in (88, 78, 68, 58):
            buf = BytesIO()
            im.save(buf, "JPEG", quality=qual, optimize=True)
            if buf.tell() <= max_bytes:
                return buf.getvalue()
    except Exception as ex:
        print(f"   [v6] image prep failed: {str(ex)[:60]}")
    return None


def make_card(hook, source=""):
    """Clean 1200x630 headline card used when the article has no usable image."""
    try:
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont
        W, H = 1200, 630
        im = Image.new("RGB", (W, H), (11, 18, 32))
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, 14, H], fill=(56, 189, 248))
        fonts = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]

        def font(sz):
            for f in fonts:
                try:
                    return ImageFont.truetype(f, sz)
                except Exception:
                    pass
            return ImageFont.load_default()

        size = 66
        while size >= 40:
            f = font(size)
            lines, cur = [], ""
            for w in hook.split():
                t = (cur + " " + w).strip()
                if d.textlength(t, font=f) <= W - 160:
                    cur = t
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
            if len(lines) * (size + 16) <= H - 230:
                break
            size -= 4
        y = 90
        for ln in lines:
            d.text((80, y), ln, font=f, fill=(241, 245, 249))
            y += size + 16
        d.text((80, H - 110), "AISecurityDaily", font=font(34), fill=(56, 189, 248))
        if source:
            d.text((80, H - 62), source[:60], font=font(26), fill=(148, 163, 184))
        buf = BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue()
    except Exception as ex:
        print(f"   [v6] card failed: {str(ex)[:60]}")
        return None
