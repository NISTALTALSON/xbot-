#!/usr/bin/env python3
"""Delete the bot's Bluesky posts that have ZERO engagement.

Dry run by default. Add --delete (and set BLUESKY_HANDLE / BLUESKY_APP_PASSWORD) to really delete.

Rules:
  - only posts older than MIN_AGE_HOURS (new posts have not had time to get engagement)
  - likes + reposts + replies + quotes must all be 0
  - a thread reply is kept if its root post (also ours) has any engagement, so live threads stay intact
"""
import os, sys, time, requests
from datetime import datetime, timezone

DID = os.environ.get("BSKY_DID", "did:plc:skxhoh2rbegclv5fsqwenun4")
MIN_AGE_HOURS = float(os.environ.get("MIN_AGE_HOURS", "24"))
PDS = "https://bsky.social/xrpc"
PUB = "https://public.api.bsky.app/xrpc"


def list_records():
    out, cursor = [], None
    while True:
        p = {"repo": DID, "collection": "app.bsky.feed.post", "limit": 100}
        if cursor:
            p["cursor"] = cursor
        for attempt in range(6):
            r = requests.get(f"{PDS}/com.atproto.repo.listRecords", params=p, timeout=30)
            if r.status_code < 500:
                break
            time.sleep(2 * (attempt + 1))
        r.raise_for_status()
        d = r.json()
        out += d["records"]
        cursor = d.get("cursor")
        if not cursor or not d["records"]:
            return out


def metrics(uris):
    m = {}
    for i in range(0, len(uris), 25):
        chunk = uris[i:i + 25]
        r = requests.get(f"{PUB}/app.bsky.feed.getPosts", params=[("uris", u) for u in chunk], timeout=30)
        r.raise_for_status()
        for x in r.json().get("posts", []):
            m[x["uri"]] = (x.get("likeCount", 0) + x.get("repostCount", 0)
                           + x.get("replyCount", 0) + x.get("quoteCount", 0))
        time.sleep(0.2)
    return m


def main():
    do_delete = "--delete" in sys.argv
    recs = list_records()
    print(f"Total posts on account: {len(recs)}")
    eng = metrics([r["uri"] for r in recs])
    now = datetime.now(timezone.utc)
    victims, kept_young, kept_engaged, kept_thread = [], 0, 0, 0
    for r in recs:
        uri, v = r["uri"], r["value"]
        created = datetime.fromisoformat(v["createdAt"].replace("Z", "+00:00"))
        if (now - created).total_seconds() / 3600 < MIN_AGE_HOURS:
            kept_young += 1
            continue
        if uri not in eng:
            kept_young += 1  # metrics unavailable -> never delete blind
            continue
        if eng.get(uri, 0) > 0:
            kept_engaged += 1
            continue
        root = (v.get("reply") or {}).get("root", {}).get("uri")
        if root and root != uri and root.startswith(f"at://{DID}/") and eng.get(root, 0) > 0:
            kept_thread += 1
            continue
        victims.append(r)
    print(f"Keep: {kept_engaged} with engagement, {kept_thread} thread replies of engaged roots, {kept_young} under {MIN_AGE_HOURS:.0f}h old")
    print(f"Zero-engagement to delete: {len(victims)}")
    for r in victims[:5]:
        print("   e.g.", r["value"].get("text", "")[:80].replace("\n", " "))
    if not do_delete:
        print("\nDRY RUN. Nothing deleted. Re-run with --delete to delete.")
        return
    handle, pw = os.environ["BLUESKY_HANDLE"], os.environ["BLUESKY_APP_PASSWORD"]
    s = requests.post(f"{PDS}/com.atproto.server.createSession",
                      json={"identifier": handle, "password": pw}, timeout=20)
    s.raise_for_status()
    s = s.json()
    hdr = {"Authorization": f"Bearer {s['accessJwt']}"}
    done = 0
    for i in range(0, len(victims), 100):
        batch = victims[i:i + 100]
        writes = [{"$type": "com.atproto.repo.applyWrites#delete",
                   "collection": "app.bsky.feed.post", "rkey": r["uri"].rsplit("/", 1)[1]} for r in batch]
        rr = requests.post(f"{PDS}/com.atproto.repo.applyWrites", headers=hdr,
                           json={"repo": s["did"], "writes": writes}, timeout=60)
        if rr.status_code == 429:
            print("rate limited, sleeping 60s")
            time.sleep(60)
            rr = requests.post(f"{PDS}/com.atproto.repo.applyWrites", headers=hdr,
                               json={"repo": s["did"], "writes": writes}, timeout=60)
        rr.raise_for_status()
        done += len(batch)
        print(f"deleted {done}/{len(victims)}")
        time.sleep(1)
    print("Done.")


if __name__ == "__main__":
    main()

