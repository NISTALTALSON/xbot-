"""brain.py - the newsroom brain for AISecurityDaily.

A feed reader posts "the next item". A person running a news account does something different:
they look at what the *world* is talking about, notice when something suddenly blows up, remember
what they already said, and decide whether the moment is worth speaking in. This models that:

  attention   world_signals(): what Hacker News, Google News and Bluesky trending are on RIGHT NOW
  surprise    burst detection: a term that jumps far above its own baseline across many outlets
  convergence the same story from many independent outlets (quality._breaking_clusters)
  memory      what we covered, when, and how big the story was then (habituation + "developing story")
  duty        if the biggest relevant story in the world is one we have NOT covered, we cover it
  decision    integrate-and-fire: salience must cross a threshold that is high just after we spoke
              (refractory period), falls as silence grows, is higher at night, and is bypassed by
              genuinely big news. Slight random jitter so the rhythm is not robotic.

Everything fails soft: if the brain errors, bot.py falls back to the classic scheduler.
"""
import json
import math
import random
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser
import requests

import quality as Q

STATE_FILE = "brain_state.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; AISecurityDailyBrain/1.0)"}

GN_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
GN_QUERIES = [
    "cybersecurity+OR+vulnerability+OR+hackers+OR+breach+when:1d",
    "zero-day+OR+ransomware+OR+exploited+OR+outage+OR+patch+when:1d",
    "AI+OR+OpenAI+OR+Anthropic+OR+Gemini+OR+LLM+when:1d",
]
HN_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40"
BSKY_TRENDING = "https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics?limit=25"


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- memory
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    s.setdefault("runs", 0)
    s.setdefault("ema", {})
    s.setdefault("best_ema", 20.0)
    s.setdefault("covered", [])
    return s


def save_state(s):
    s["ema"] = {k: round(v, 3) for k, v in sorted(s["ema"].items(), key=lambda kv: -kv[1])[:4000] if v >= 0.02}
    s["covered"] = s["covered"][-60:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f)


# ---------------------------------------------------------------- attention: what is the world on?
def _get(url, timeout=12):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def _clean_headline(t):
    return re.sub(r"\s+[-\u2013|]\s+[^-\u2013|]{2,40}$", "", t or "").strip()


def world_signals():
    """Returns (items, trending_token_sets). Each item: {tokens, outlet, weight, title}."""
    items, trending = [], []
    try:  # Hacker News front page: real humans voting
        for h in _get(HN_URL).json().get("hits", []):
            title = h.get("title") or ""
            url = h.get("url") or ""
            outlet = urlparse(url).netloc.lower().replace("www.", "") or "news.ycombinator.com"
            items.append({"tokens": Q._tokens(title), "outlet": outlet, "title": title,
                          "weight": 1 + math.log10((h.get("points") or 0) + 1)})
    except Exception as ex:
        print(f"   [brain] HN signal unavailable: {str(ex)[:50]}")
    for q in GN_QUERIES:  # Google News: what mainstream outlets are all running
        try:
            feed = feedparser.parse(_get(GN_URL.format(q=q)).content)
            for e in feed.entries[:40]:
                src = (e.get("source") or {}).get("title") or urlparse(e.get("link", "")).netloc
                title = _clean_headline(e.get("title", ""))
                items.append({"tokens": Q._tokens(title), "outlet": src.lower(), "title": title, "weight": 1.0})
        except Exception as ex:
            print(f"   [brain] Google News signal unavailable: {str(ex)[:50]}")
    try:  # Bluesky's own trending topics
        for t in _get(BSKY_TRENDING).json().get("topics", []):
            tk = Q._tokens(t.get("topic", ""))
            if tk:
                trending.append(tk)
    except Exception as ex:
        print(f"   [brain] Bluesky trending unavailable: {str(ex)[:50]}")
    return items, trending


def world_clusters(items):
    """Group headlines about the same story. Big clusters = what everyone is talking about."""
    n = len(items)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        if not items[i]["tokens"]:
            continue
        for j in range(i + 1, n):
            if items[j]["tokens"] and Q._same_story(items[i]["tokens"], items[j]["tokens"], 0.3):
                parent[find(j)] = find(i)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        if len(members) < 3:
            continue
        outlets = {items[i]["outlet"] for i in members}
        counts = {}
        for i in members:
            for t in items[i]["tokens"]:
                counts[t] = counts.get(t, 0) + 1
        need = max(2, math.ceil(0.3 * len(members)))
        core = {t for t, c in counts.items() if c >= need}
        text = " ".join(items[i]["title"].lower() for i in members)
        relevant = sum(w for k, w in Q.HOT.items() if k in text) >= 4 or Q._ai_hits(text) >= 6
        if len(core) >= 2 and relevant:
            rep = max(members, key=lambda i: len(items[i]["tokens"] & core))
            out.append({"core": core, "outlets": len(outlets), "weight": sum(items[i]["weight"] for i in members),
                        "title": items[rep]["title"]})
    out.sort(key=lambda c: (c["outlets"], c["weight"]), reverse=True)
    return out[:12]


def _match(tokens, core):
    ov = len(tokens & core)
    return ov >= 2 and (ov >= 3 or ov / max(1, len(core)) >= 0.25)


# ---------------------------------------------------------------- surprise: burst detection
def _distinct_domain_counts(entries):
    seen = {}
    for e in entries:
        a = Q._age_hours(e)
        if a is not None and a > 24:
            continue
        d = Q._domain(e)
        for t in Q._tokens(e["title"]):
            seen.setdefault(t, set()).add(d)
    return {t: len(ds) for t, ds in seen.items()}


def _burst(tokens, cur, ema):
    best = 0.0
    for t in tokens:
        c = cur.get(t, 0)
        if c >= 3:
            best = max(best, (c - ema.get(t, 0.0)) / (math.sqrt(ema.get(t, 0.0)) + 1))
    return best


# ---------------------------------------------------------------- memory: have we covered it?
def _cover_info(core, st):
    """(hours since we last covered this story or None, outlet count back then)."""
    best_age, outlets = None, 0
    now = time.time()
    for c in st["covered"]:
        if len(set(c["tokens"]) & core) >= 2:
            age = (now - c["ts"]) / 3600
            if best_age is None or age < best_age:
                best_age, outlets = age, c.get("outlets", 0)
    for age, rt in Q._recent_posted(72):
        if rt and len(rt & core) >= 2 and (best_age is None or age < best_age):
            best_age = age
    return best_age, outlets


def after_post(entry):
    """Remember that we spoke about this, and how big the story was at that moment."""
    try:
        st = load_state()
        cl = entry.get("_cluster")
        st["covered"].append({"tokens": sorted(cl["core"]) if cl else sorted(Q._tokens(entry["title"]))[:8],
                              "ts": time.time(), "outlets": cl["outlets"] if cl else 0})
        save_state(st)
    except Exception as ex:
        print(f"   [brain] after_post skipped: {str(ex)[:60]}")


# ---------------------------------------------------------------- decision: integrate and fire
def _hours_since_last_post(now):
    posts = Q._load()["posts"]
    if not posts:
        return None
    return (now - datetime.fromisoformat(posts[-1]["ts"])).total_seconds() / 3600


def _fire(best, st, gap, now):
    v = best["_sal"]
    breaking = best.get("_breaking") or best.get("_duty")
    if breaking:
        if gap is None or gap >= 0.4:
            return True, f"{best.get('_why', 'breaking')} (salience {v:.0f})"
        return False, f"breaking story waiting out the refractory period ({gap:.1f}h since last post)"
    if v < 8:
        return False, f"nothing worth saying (best salience {v:.0f})"
    mean = max(10.0, st["best_ema"])
    night = not (3 <= now.hour < 21)
    if gap is None:
        a = 0.7
    elif gap < 1.0:
        a = 9.0
    elif gap < 2.5:
        a = 1.7
    elif gap < 4:
        a = 1.25
    elif gap < 7:
        a = 1.0
    elif gap < 12:
        a = 0.8
    else:
        a = 0.5
    theta = mean * a * (1.45 if night else 1.0) * random.uniform(0.92, 1.08)
    gaptxt = "no previous post" if gap is None else f"{gap:.1f}h since last post"
    return v >= theta, f"salience {v:.0f} vs threshold {theta:.0f} ({gaptxt}{', night' if night else ''})"


# ---------------------------------------------------------------- the whole loop
def think(new_entries, all_entries=None, persist=True):
    """Rank the unposted entries with world awareness and decide whether to speak now.
    Returns (ranked_entries, verdict). verdict = {fire, why, log}."""
    now = _now()
    st = load_state()
    all_entries = all_entries or new_entries
    log = []

    items, trending = world_signals()
    clusters = world_clusters(items)
    for c in clusters[:5]:
        log.append(f"world: {c['outlets']:>2} outlets | {c['title'][:70]}")

    ranked = Q.rank_entries(new_entries) if new_entries else []
    cur = _distinct_domain_counts(all_entries)
    warm = st["runs"] >= 12  # need a baseline before "surprise" means anything

    for e in ranked:
        toks = Q._tokens(e["title"])
        why = []
        sal = e.get("_score", 0.0)
        z = _burst(toks, cur, st["ema"]) if warm else 0.0
        if z >= 1.5:
            sal += min(12.0, 2.5 * z)
            why.append(f"burst x{z:.1f}")
        for c in clusters:
            if _match(toks, c["core"]):
                e["_cluster"] = {"core": c["core"], "outlets": c["outlets"]}
                if c["outlets"] >= 3:
                    sal += min(30.0, 3.0 * c["outlets"])
                    why.append(f"world story ({c['outlets']} outlets)")
                break
        if any(len(toks & t) >= 2 or (len(t) == 1 and (toks & t)) for t in trending):
            sal += 5
            why.append("trending on Bluesky")
        if e.get("_breaking"):
            why.append("multi-outlet breaking cluster")
        e["_sal"] = sal
        e["_why"] = ", ".join(why) or "routine"

    # duty: the biggest relevant story in the world, if we have not covered it, is ours to cover
    for c in clusters[:5]:
        if c["outlets"] < 4:
            continue
        age, was = _cover_info(c["core"], st)
        update = age is not None and age >= 8 and c["outlets"] >= 8 and c["outlets"] >= 1.8 * max(was, 1)
        if age is not None and not update:
            continue
        cands = [e for e in ranked if _match(Q._tokens(e["title"]), c["core"])
                 and not any(j in e["title"].lower() for j in Q.JUNK)]  # never newsletters/roundups
        if cands:
            # the entry that best represents the story, not just the one with the loudest score
            top = max(cands, key=lambda e: (len(Q._tokens(e["title"]) & c["core"]), e["_sal"]))
            top["_duty"] = True
            top["_breaking"] = True
            top["_sal"] += 60
            top["_why"] = ("developing story, bigger than when we last covered it" if update
                           else f"the world is talking about this ({c['outlets']} outlets) and we have not covered it")
            log.append(f"duty: {top['_why']} -> {top['title'][:60]}")
            break

    ranked.sort(key=lambda e: e.get("_sal", 0), reverse=True)
    for e in ranked[:4]:
        log.append(f"cand: {e['_sal']:5.1f} [{e['_why']}] {e['title'][:60]}")

    if ranked:
        gap = _hours_since_last_post(now)
        fire, why = _fire(ranked[0], st, gap, now)
        v = min(ranked[0]["_sal"], 2 * max(10.0, st["best_ema"]))  # one huge story must not warp the baseline
        st["best_ema"] = 0.9 * st["best_ema"] + 0.1 * v
    else:
        fire, why = False, "nothing new"

    # habituation: every term's baseline drifts toward what we saw this run
    ema = st["ema"]
    for t in list(ema):
        ema[t] *= 0.98
    for t, c in cur.items():
        ema[t] = ema.get(t, 0.0) + 0.02 * c
    st["runs"] += 1
    if persist:
        save_state(st)
    return ranked, {"fire": fire, "why": why, "log": log}
