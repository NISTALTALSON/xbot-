"""llm.py - one place that talks to Gemini, and survives Google retiring models.

gemini-2.0-flash was shut down on 1 June 2026 and gemini-2.5-flash in October 2026, which silently
broke every model call in this bot (it fell back to template text). Instead of hard-coding a model
name, ask the API which models this key can use, prefer the newest stable Flash, and fall through the
list on failure. The result of the last health check is written to llm_status.json so a failure is
visible in the repo instead of hiding in a log.
"""
import json
import os
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"
STATIC_FALLBACK = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
STATUS_FILE = "llm_status.json"
_state = {"models": None, "last_error": "", "last_model": ""}


def _version(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)-flash", name)
    return float(m.group(1)) if m else 0.0


def models(key):
    """Newest stable Flash first, then Flash-Lite, then static fallbacks. Cached per process."""
    if _state["models"] is not None:
        return _state["models"]
    out = []
    try:
        r = requests.get(f"{API}/models", params={"key": key, "pageSize": 200}, timeout=15)
        r.raise_for_status()
        names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", [])]
        flash = sorted((n for n in names if re.fullmatch(r"gemini-\d+(?:\.\d+)?-flash", n)), key=_version, reverse=True)
        lite = sorted((n for n in names if re.fullmatch(r"gemini-\d+(?:\.\d+)?-flash-lite", n)), key=_version, reverse=True)
        out = flash + lite
    except Exception as ex:
        _state["last_error"] = f"model list failed: {str(ex)[:80]}"
        print(f"   [llm] {_state['last_error']}")
    pref = os.environ.get("GEMINI_MODEL", "").strip()
    chain = ([pref] if pref else []) + out + STATIC_FALLBACK
    seen, final = set(), []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            final.append(m)
    _state["models"] = final[:5]
    return _state["models"]


def generate(prompt, json_mode=True, temperature=0.7, timeout=45):
    """Returns the model's text or None. Tries each available model in turn."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        _state["last_error"] = "GEMINI_API_KEY not set"
        return None
    cfg = {"temperature": temperature}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    for model in models(key):
        try:
            r = requests.post(f"{API}/models/{model}:generateContent", params={"key": key},
                              json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg},
                              timeout=timeout)
            if r.status_code != 200:
                _state["last_error"] = f"{model}: HTTP {r.status_code} {r.text[:80]}"
                print(f"   [llm] {_state['last_error']}")
                continue
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            _state["last_model"], _state["last_error"] = model, ""
            return text
        except Exception as ex:
            _state["last_error"] = f"{model}: {str(ex)[:80]}"
            print(f"   [llm] {_state['last_error']}")
    return None


def health_check():
    """Tiny live call; records the outcome in llm_status.json. Returns True if a model answered."""
    t = generate('Reply with the JSON {"ok": true}', json_mode=True, temperature=0, timeout=30)
    ok = bool(t)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": ok,
                       "model": _state["last_model"], "tried": _state["models"],
                       "error": _state["last_error"]}, f)
    except Exception:
        pass
    print(f"   [llm] health: {'OK ' + _state['last_model'] if ok else 'FAILED - ' + _state['last_error']}")
    return ok
