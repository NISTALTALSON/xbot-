"""llm.py - one place that talks to Gemini, and survives Google retiring models.

gemini-2.0-flash was shut down on 1 June 2026 and gemini-2.5-flash in October 2026, which silently
broke every model call in this bot (it fell back to template text). Instead of hard-coding a model
name, ask the API which models this key can use, prefer the newest stable Flash, and fall through the
list on failure. The result of the last health check is written to llm_status.json so a failure is
visible in the repo instead of hiding in a log.

v2: transient errors (429/5xx) are retried with a short backoff before moving to the next model,
retired or 404 models are skipped, every model's last error is recorded (not just the final one),
and a Signal/Telegram alert goes out when Gemini goes down or comes back.
"""
import json
import os
import random
import re
import time

import requests

API = "https://generativelanguage.googleapis.com/v1beta"
STATIC_FALLBACK = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
RETIRED = {"gemini-2.0-flash", "gemini-2.5-flash"}
RETRY_CODES = {429, 500, 502, 503, 504}
STATUS_FILE = "llm_status.json"
_state = {"models": None, "last_error": "", "last_model": "", "errors": {}, "dead": set()}


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
        if m and m not in seen and m not in RETIRED:
            seen.add(m)
            final.append(m)
    _state["models"] = final[:5]
    return _state["models"]


def _note(model, msg):
    _state["errors"][model] = msg
    _state["last_error"] = f"{model}: {msg}"
    print(f"   [llm] {_state['last_error']}")


def generate(prompt, json_mode=True, temperature=0.7, timeout=45):
    """Returns the model's text or None. Retries transient errors, then tries the next model."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        _state["last_error"] = "GEMINI_API_KEY not set"
        return None
    cfg = {"temperature": temperature}
    if json_mode:
        cfg["responseMimeType"] = "application/json"
    deadline = time.monotonic() + max(timeout * 2.5, 60)  # one call never stalls a run for minutes
    for model in models(key):
        if model in _state["dead"]:
            continue
        for attempt in range(3):
            if time.monotonic() > deadline:
                return None
            try:
                r = requests.post(f"{API}/models/{model}:generateContent", params={"key": key},
                                  json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg},
                                  timeout=timeout)
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    _state["last_model"], _state["last_error"] = model, ""
                    _state["errors"].pop(model, None)
                    return text
                _note(model, f"HTTP {r.status_code} {r.text[:80]}")
                if r.status_code == 404:
                    _state["dead"].add(model)  # retired or unavailable for this key: stop asking this run
                    break
                if r.status_code in RETRY_CODES and attempt < 2:
                    time.sleep(2 * (attempt + 1) + random.random())
                    continue
                break
            except Exception as ex:
                _note(model, str(ex)[:80])
                if attempt < 2:
                    time.sleep(2 * (attempt + 1) + random.random())
                    continue
                break
    return None


def _alert(text):
    """Best-effort heads-up on Signal and the Telegram draft chat. Plain ASCII only (CallMeBot mangles $ and ')."""
    sphone = os.environ.get("SIGNAL_PHONE", "").strip()
    skey = os.environ.get("SIGNAL_APIKEY", "").strip()
    if sphone and skey:
        try:
            requests.get("https://signal.callmebot.com/signal/send.php",
                         params={"phone": sphone, "apikey": skey, "text": text}, timeout=20)
        except Exception:
            pass
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_DRAFT_CHAT_ID", "").strip()
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=20)
        except Exception:
            pass


def health_check():
    """Tiny live call; records the outcome in llm_status.json. Returns True if a model answered.
    Alerts only on a change (up -> down, down -> up) so a long outage does not spam you."""
    prev_ok = None
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            prev_ok = json.load(f).get("ok")
    except Exception:
        pass
    t = generate('Reply with the JSON {"ok": true}', json_mode=True, temperature=0, timeout=30)
    ok = bool(t)
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ok": ok,
                       "model": _state["last_model"], "tried": _state["models"],
                       "error": _state["last_error"], "errors": _state["errors"]}, f)
    except Exception:
        pass
    print(f"   [llm] health: {'OK ' + _state['last_model'] if ok else 'FAILED - ' + _state['last_error']}")
    if not ok and prev_ok is not False:
        detail = "; ".join(f"{m}: {e[:40]}" for m, e in list(_state["errors"].items())[:3]) or _state["last_error"]
        _alert("AISecurityDaily: Gemini is failing, so the bot is posting template text until it recovers. " + detail)
    elif ok and prev_ok is False:
        _alert(f"AISecurityDaily: Gemini is back ({_state['last_model']}), AI-written posts resumed.")
    return ok
