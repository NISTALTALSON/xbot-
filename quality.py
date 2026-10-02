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
    "stakes": "Lead with the single most alarming concrete fact or number from the story, then say who is exposed and why they should care.",
    "action": "Lead with who is affected, then give the reader something to DO today (patch, rotate, disable, check).",
    "plain": "Explain what happened in plain English using one vivid, accurate analogy. Zero jargon.",
    "take": "Give a sharp, defensible opinion on what this really signals for the industry, backed by one fact from the story.",
    "question": "State the story in one punchy line, then end with a real question practitioners would argue about.",
}
FOLLOWUP_FORMATS = {"stakes", "action"}

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


def rank_entries(entries):
    toks = [_tokens(e["title"]) for e in entries]
    scored = []
    for i, e in enumerate(entries):
        text = (e["title"] + " " + (e.get("summary") or "")[:300]).lower()
        s = sum(w for k, w in HOT.items() if k in text)
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
        print(f"        {s:5.1f}  {e['title'][:70]}")
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


def record_post(uri, category, fmt, title):
    d = _load()
    now = datetime.now(timezone.utc)
    d["posts"].append({"uri": uri, "ts": now.isoformat(), "hour": now.hour, "category": category,
                       "format": fmt, "title": title[:80], "score": 0, "likes": 0, "reposts": 0,
                       "replies": 0, "quotes": 0, "checked": None})
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
    for key in ("format", "category", "hour"):
        rows = sorted(_avg_by(done, key).items(), key=lambda kv: kv[1][0], reverse=True)[:5]
        print(f"        by {key}: " + ", ".join(f"{k}={a:.1f} (n={n})" for k, (a, n) in rows))
    best = sorted(done, key=lambda p: p["score"], reverse=True)[:3]
    for p in best:
        print(f"        top post: score {p['score']} | {p['format']} | {p['title']}")


def pick_format():
    stats = _avg_by(_load()["posts"], "format")
    weights = []
    for f in FORMATS:
        avg, n = stats.get(f, (0, 0))
        weights.append(1.0 + avg if n >= 3 else 2.0)  # unproven formats keep getting tried
    return random.choices(list(FORMATS), weights=weights)[0]


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
        "You write for AISecurityDaily, a cybersecurity and AI-security news account on Bluesky. "
        "Readers are practitioners, students and curious tech people.\n"
        f"Category: {category.replace('_', ' ')}\nHeadline: {title}\n"
        f"Article excerpt:\n{body_text[:3000]}\n\n"
        f"Post format: {FORMATS[fmt]}\n\n"
        'Return JSON with keys "hook", "body"' + (', "followup"' if want_fu else "") + ".\n"
        '- "hook": first line, max 90 chars. Stop the scroll with a concrete fact, number, name or '
        "consequence from the article. No clickbait, no 'BREAKING', no emoji at the start.\n"
        '- "body": 1-2 sentences, max 170 chars, the why-it-matters or the angle.\n'
        + ('- "followup": max 240 chars, 2-3 concrete steps a reader can take today, numbered.\n' if want_fu else "")
        + "\nRules: use ONLY facts present in the excerpt; never invent numbers, names, CVE ids or dates; "
        "if unsure, leave it out. No URLs, hashtags or source names. Plain words, active voice, sound like "
        "a sharp practitioner, not a press release. At most one emoji in the whole post, only if it adds meaning."
    )
    return parse_post_json(_gemini_json(prompt))


def compose_post(v2, entry, hashtags, count, trunc, limit):
    link = entry["link"]
    tag = (hashtags or "").split()[0] if hashtags else ""
    footer = f"{tag}\n{link}" if tag else link
    hook, body = v2["hook"], v2["body"]
    room = limit - count(f"{hook}\n\n\n\n{footer}")
    if room >= 40:
        if count(body) > room:
            cut = trunc(body, room)
            ends = [cut.rfind(c) for c in ".!?"]
            end = max(ends)
            body = cut[:end + 1] if end >= 30 else cut.rsplit(" ", 1)[0].rstrip(",;:- ") + "..."
        post = f"{hook}\n\n{body}\n\n{footer}"
    else:
        post = f"{hook}\n\n{footer}"
    if count(post) > limit:
        post = f"{trunc(hook, limit - count(link) - 2)}\n\n{link}"
    return post
