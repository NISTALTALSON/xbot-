"""editor.py - an LLM editor-in-chief on top of brain.py.

brain.py gives the bot reflexes (what the world is on, surprise, memory, timing).
This gives it judgment. Before anything is posted, a language model plays the editor:
it sees the candidates, what the world is talking about, what we posted recently and how each
post performed, then decides WHICH story (if any) is worth posting and what the sharp angle is.
The angle is passed to the writer so the post makes a point instead of paraphrasing a headline.

Guardrails: the editor never overrides a multi-outlet breaking story (it may only choose which
article covers it), the refractory period still applies, and any failure falls back to the rules.
"""
import json
import os
import re
import requests

import quality as Q

MODELS = (os.environ.get("EDITOR_MODEL", "gemini-2.5-flash"), "gemini-2.0-flash")


def _gemini(prompt, temperature=0.3):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    for model in MODELS:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": key},
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}},
                timeout=60)
            r.raise_for_status()
            raw = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
            return json.loads(raw)
        except Exception as ex:
            print(f"   [editor] {model} failed: {str(ex)[:70]}")
    return None


def performance_digest(n=40):
    """What actually worked: engagement on our own recent posts (already tracked in analytics.json)."""
    posts = [p for p in Q._load()["posts"] if p.get("checked")][-n:]
    rows = []
    for p in posts:
        eng = p.get("likes", 0) + 2 * (p.get("reposts", 0) + p.get("replies", 0) + p.get("quotes", 0))
        rows.append((eng, p.get("title", "")[:75]))
    if len(rows) < 6:
        return "Not enough history yet to say what works."
    best = [f"  {e} | {t}" for e, t in sorted(rows, reverse=True)[:4] if e > 0]
    flop = [f"  0 | {t}" for e, t in rows if e == 0][:4]
    return ("Best performing recent posts (engagement | title):\n" + ("\n".join(best) or "  none") +
            "\nPosts that got nothing:\n" + ("\n".join(flop) or "  none"))


def review(ranked, verdict):
    """Ask the editor. Returns dict(action, pick, urgency, why, angle) or None on any failure."""
    if not ranked:
        return None
    gap = verdict.get("gap")
    top = ranked[0]
    if gap is not None and gap < 0.75 and not (top.get("_breaking") or top.get("_duty")):
        return None  # just spoke; no need to spend a model call
    cands = ranked[:10]
    lines = []
    for i, e in enumerate(cands):
        age = Q._age_hours(e)
        lines.append(f"[{i}] age {'?' if age is None else f'{age:.0f}h'} | {e.get('source', '')[:28]} | "
                     f"signals: {e.get('_why', 'routine')} | {e['title'][:120]} | "
                     f"{(e.get('summary') or '')[:200].replace(chr(10), ' ')}")
    recent = []
    for p in Q._load()["posts"][-8:]:
        recent.append(f"  - {p.get('title', '')[:90]}")
    world = "\n".join(f"  - {t[:100]} ({n} outlets)" for t, n in verdict.get("world", [])[:6]) or "  (unavailable)"
    prompt = (
        "You are the editor-in-chief of a small AI and AI-security news account on Bluesky. The audience is AI "
        "engineers, ML practitioners, security people and developers. The goal is to become the account people trust "
        "to flag what matters first, so posts earn replies, reposts and follows.\n\n"
        f"Hours since our last post: {'none yet' if gap is None else f'{gap:.1f}'}\n"
        f"What the wider world is covering right now (outlet counts):\n{world}\n\n"
        f"Our most recent posts (do not repeat these topics):\n" + ("\n".join(recent) or "  none") + "\n\n"
        + performance_digest() + "\n\n"
        "Candidate stories from our feeds:\n" + "\n".join(lines) + "\n\n"
        "Decide what, if anything, to post in this slot.\n"
        "Prefer: the biggest relevant story we have not covered; first-hand facts such as new model releases, actively "
        "exploited vulnerabilities, breaches with concrete impact; stories where an engineer can learn or do something.\n"
        "Reject: topics we already posted, newsletters and roundups, listicles, vendor marketing, vague opinion, "
        "clickbait, anything without a concrete fact. If nothing is worth posting, choose skip.\n\n"
        'Return JSON: {"action": "post" or "skip", "pick": <candidate number or -1>, "urgency": <1-10, how bad it '
        'is to wait>, "why": "<one sentence>", "angle": "<one sentence: the specific point for this audience '
        '- the consequence, who is affected, or what to do. Use only facts present in the candidate info above; '
        'never invent numbers, names or CVE ids>"}'
    )
    d = _gemini(prompt)
    if not isinstance(d, dict):
        return None
    action = "post" if str(d.get("action", "")).lower() == "post" else "skip"
    try:
        pick = int(d.get("pick", -1))
    except Exception:
        pick = -1
    if action == "post" and not (0 <= pick < len(cands)):
        return None
    try:
        urgency = max(1, min(10, int(d.get("urgency", 5))))
    except Exception:
        urgency = 5
    return {"action": action, "pick": pick, "urgency": urgency,
            "why": str(d.get("why", ""))[:200], "angle": str(d.get("angle", ""))[:300]}


def apply(ranked, verdict, ed):
    """Merge the editor's judgment into the rule-based verdict, within the guardrails."""
    if not ed or not ranked:
        return ranked, verdict
    top = ranked[0]
    protected = bool(top.get("_duty") or top.get("_breaking"))
    gap = verdict.get("gap")
    if ed["action"] == "post":
        pick = ranked[ed["pick"]]
        if protected and not (pick.get("_duty") or pick.get("_breaking")):
            pick = top  # the editor cannot bury a story the whole world is covering
        ranked = [pick] + [e for e in ranked if e is not pick]
        pick["_editor_note"] = {"angle": ed["angle"], "why": ed["why"]}
        if not verdict["fire"] and ed["urgency"] >= 8 and (gap is None or gap >= 1.0):
            verdict["fire"] = True
            verdict["why"] = f"editor override (urgency {ed['urgency']}): {ed['why']}"
        elif verdict["fire"]:
            verdict["why"] = f"{verdict['why']} | editor: {ed['why']}"
    elif verdict["fire"] and not protected and (gap is None or gap < 10):
        # the editor may pass, but never let it silence the account for 10+ hours
        verdict["fire"] = False
        verdict["why"] = f"editor passed: {ed['why']}"
    return ranked, verdict
