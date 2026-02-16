#!/usr/bin/env python3
"""
Bluesky News Bot - Automatically posts AI and Cybersecurity news to Bluesky
"""

import os
import feedparser
import time
from datetime import datetime
import random
import hashlib
import json
import requests

# RSS Feeds for AI and Cybersecurity news
RSS_FEEDS = [
    # AI News
    "https://rss.arxiv.org/rss/cs.AI",
    "https://blog.google/technology/ai/rss/",
    "https://openai.com/blog/rss.xml",
    
    # Cybersecurity & Ethical Hacking
    "https://www.bleepingcomputer.com/feed/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.darkreading.com/rss.xml",
    "https://krebsonsecurity.com/feed/",
    "https://www.schneier.com/blog/atom.xml",
    "https://threatpost.com/feed/",
]

POSTED_FILE = "posted_items.json"

def load_posted_items():
    """Load previously posted item IDs"""
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, 'r') as f:
            return json.load(f)
    return []

def save_posted_item(item_id):
    """Save posted item ID to avoid duplicates"""
    posted = load_posted_items()
    posted.append(item_id)
    posted = posted[-500:]
    with open(POSTED_FILE, 'w') as f:
        json.dump(posted, f)

def get_item_id(entry):
    """Generate unique ID for a feed entry"""
    unique_string = entry.get('link', '') + entry.get('title', '')
    return hashlib.md5(unique_string.encode()).hexdigest()

def fetch_news():
    """Fetch news from all RSS feeds"""
    all_entries = []
    
    for feed_url in RSS_FEEDS:
        try:
            print(f"Fetching from: {feed_url}")
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:
                all_entries.append({
                    'title': entry.get('title', 'No title'),
                    'link': entry.get('link', ''),
                    'published': entry.get('published', ''),
                    'source': feed.feed.get('title', 'Unknown'),
                    'id': get_item_id(entry)
                })
        except Exception as e:
            print(f"Error fetching {feed_url}: {e}")
            continue
    
    return all_entries

def format_post(entry):
    """Format entry into a Bluesky post (300 char limit)"""
    title = entry['title']
    link = entry['link']
    hashtags = "\n\n#AI #CyberSecurity #InfoSec"
    max_title_length = 300 - len(link) - len(hashtags) - 3
    
    if len(title) > max_title_length:
        title = title[:max_title_length-3] + "..."
    
    post = f"{title}\n\n{link}{hashtags}"
    return post

def create_bluesky_session(handle, app_password):
    """Create authenticated session with Bluesky"""
    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password}
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Error creating session: {e}")
        return None

def post_to_bluesky(post_text, session):
    """Post to Bluesky"""
    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": post_text,
                    "createdAt": datetime.utcnow().isoformat() + "Z"
                }
            }
        )
        resp.raise_for_status()
        print(f"✓ Post published successfully!")
        return True
    except Exception as e:
        print(f"✗ Error posting: {e}")
        return False

def main():
    """Main bot logic"""
    print(f"\n{'='*50}")
    print(f"Bluesky News Bot - Starting at {datetime.now()}")
    print(f"{'='*50}\n")
    
    handle = os.environ.get('BLUESKY_HANDLE')
    app_password = os.environ.get('BLUESKY_APP_PASSWORD')
    
    if not handle or not app_password:
        print("ERROR: Missing Bluesky credentials!")
        return
    
    print("Authenticating with Bluesky...")
    session = create_bluesky_session(handle, app_password)
    
    if not session:
        print("Failed to authenticate. Exiting.")
        return
    
    print("✓ Authentication successful!\n")
    
    print("Fetching news from RSS feeds...")
    entries = fetch_news()
    print(f"Found {len(entries)} total entries\n")
    
    if not entries:
        print("No entries found. Exiting.")
        return
    
    posted_items = load_posted_items()
    new_entries = [e for e in entries if e['id'] not in posted_items]
    print(f"Found {len(new_entries)} new entries\n")
    
    if not new_entries:
        print("No new entries to post. Exiting.")
        return
    
    random.shuffle(new_entries)
    to_post = new_entries[:random.randint(2, 3)]
    
    for i, entry in enumerate(to_post, 1):
        print(f"\n[{i}/{len(to_post)}] Posting:")
        print(f"  Title: {entry['title'][:60]}...")
        print(f"  Source: {entry['source']}")
        
        post_text = format_post(entry)
        
        if post_to_bluesky(post_text, session):
            save_posted_item(entry['id'])
            print("  Status: ✓ Posted and saved")
        else:
            print("  Status: ✗ Failed to post")
        
        if i < len(to_post):
            wait_time = random.randint(10, 20)
            print(f"  Waiting {wait_time}s before next post...")
            time.sleep(wait_time)
    
    print(f"\n{'='*50}")
    print(f"Bot finished at {datetime.now()}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
