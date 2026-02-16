#!/usr/bin/env python3
"""
X News Bot - Automatically posts AI and Cybersecurity news to X/Twitter
"""

import os
import feedparser
import tweepy
import time
from datetime import datetime
import random
import hashlib
import json

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
    # Keep only last 500 items to prevent file from growing too large
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
            for entry in feed.entries[:5]:  # Get top 5 from each feed
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

def format_tweet(entry):
    """Format entry into a tweet (280 char limit)"""
    title = entry['title']
    link = entry['link']
    
    # Add relevant hashtags
    hashtags = "\n\n#AI #CyberSecurity #InfoSec"
    
    # Calculate available space
    max_title_length = 280 - len(link) - len(hashtags) - 3  # -3 for spacing
    
    if len(title) > max_title_length:
        title = title[:max_title_length-3] + "..."
    
    tweet = f"{title}\n\n{link}{hashtags}"
    
    return tweet

def post_to_x(tweet_text):
    """Post tweet to X using API v2"""
    try:
        # Get credentials from environment variables
        consumer_key = os.environ.get('X_CONSUMER_KEY')
        consumer_secret = os.environ.get('X_CONSUMER_SECRET')
        access_token = os.environ.get('X_ACCESS_TOKEN')
        access_token_secret = os.environ.get('X_ACCESS_TOKEN_SECRET')
        
        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            print("ERROR: Missing API credentials!")
            return False
        
        # Authenticate
        client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_token_secret
        )
        
        # Post tweet
        response = client.create_tweet(text=tweet_text)
        print(f"✓ Tweet posted successfully! ID: {response.data['id']}")
        return True
        
    except Exception as e:
        print(f"✗ Error posting tweet: {e}")
        return False

def main():
    """Main bot logic"""
    print(f"\n{'='*50}")
    print(f"X News Bot - Starting at {datetime.now()}")
    print(f"{'='*50}\n")
    
    # Fetch news
    print("Fetching news from RSS feeds...")
    entries = fetch_news()
    print(f"Found {len(entries)} total entries\n")
    
    if not entries:
        print("No entries found. Exiting.")
        return
    
    # Load previously posted items
    posted_items = load_posted_items()
    
    # Filter out already posted items
    new_entries = [e for e in entries if e['id'] not in posted_items]
    print(f"Found {len(new_entries)} new entries\n")
    
    if not new_entries:
        print("No new entries to post. Exiting.")
        return
    
    # Shuffle and pick random entries to post (2-3 tweets per run)
    random.shuffle(new_entries)
    to_post = new_entries[:random.randint(2, 3)]
    
    # Post tweets
    for i, entry in enumerate(to_post, 1):
        print(f"\n[{i}/{len(to_post)}] Posting:")
        print(f"  Title: {entry['title'][:60]}...")
        print(f"  Source: {entry['source']}")
        
        tweet_text = format_tweet(entry)
        
        if post_to_x(tweet_text):
            save_posted_item(entry['id'])
            print("  Status: ✓ Posted and saved")
        else:
            print("  Status: ✗ Failed to post")
        
        # Rate limiting: wait between tweets
        if i < len(to_post):
            wait_time = random.randint(30, 60)
            print(f"  Waiting {wait_time}s before next tweet...")
            time.sleep(wait_time)
    
    print(f"\n{'='*50}")
    print(f"Bot finished at {datetime.now()}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
