#!/usr/bin/env python3
"""
Multi-Platform News Bot - Bluesky + Telegram + Mastodon
Comprehensive AI, Cybersecurity, Business, Tech, Finance news from 70+ sources
Posts every 2 hours - 100% Free Forever
"""

import os
import feedparser
import time
from datetime import datetime
import random
import hashlib
import json
import requests

# COMPREHENSIVE RSS FEEDS - 70+ sources across 11 categories
RSS_FEEDS = {
    'artificial_intelligence': [
        "https://rss.arxiv.org/rss/cs.AI",
        "https://rss.arxiv.org/rss/cs.LG",
        "https://blog.google/technology/ai/rss/",
        "https://openai.com/blog/rss.xml",
        "https://www.technologyreview.com/feed/",
        "https://venturebeat.com/category/ai/feed/",
        "https://blogs.nvidia.com/feed/",
        "https://www.deepmind.com/blog/rss.xml",
        "https://machinelearningmastery.com/feed/",
        "https://ai.googleblog.com/feeds/posts/default",
        "https://www.unite.ai/feed/",
    ],
    
    'cybersecurity': [
        "https://www.bleepingcomputer.com/feed/",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.darkreading.com/rss.xml",
        "https://krebsonsecurity.com/feed/",
        "https://www.schneier.com/blog/atom.xml",
        "https://threatpost.com/feed/",
        "https://www.securityweek.com/feed/",
        "https://www.csoonline.com/feed/",
        "https://www.infosecurity-magazine.com/rss/news/",
        "https://www.cyberscoop.com/feed/",
        "https://www.helpnetsecurity.com/feed/",
    ],
    
    'ethical_hacking': [
        "https://www.reddit.com/r/netsec/.rss",
        "https://portswigger.net/blog/rss",
        "https://www.offensive-security.com/blog/feed/",
        "https://null-byte.wonderhowto.com/rss.xml",
        "https://hakin9.org/feed/",
        "https://www.hackingarticles.in/feed/",
    ],
    
    'data_breaches': [
        "https://www.databreaches.net/feed/",
        "https://www.bleepingcomputer.com/feed/tag/data-breach/",
        "https://www.privacyaffairs.com/feed/",
    ],
    
    'business_tech': [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss",
        "https://arstechnica.com/feed/",
        "https://www.engadget.com/rss.xml",
        "https://www.cnet.com/rss/news/",
        "https://www.zdnet.com/news/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    ],
    
    'stocks_finance': [
        "https://www.marketwatch.com/rss/topstories",
        "https://finance.yahoo.com/news/rssindex",
        "https://seekingalpha.com/feed.xml",
        "https://www.investing.com/rss/news.rss",
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "https://www.fool.com/feeds/index.aspx",
        "https://www.benzinga.com/feed",
    ],
    
    'crypto_blockchain': [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
        "https://blog.ethereum.org/feed.xml",
        "https://bitcoinmagazine.com/.rss/full/",
    ],
    
    'cloud_devops': [
        "https://aws.amazon.com/blogs/aws/feed/",
        "https://azure.microsoft.com/en-us/blog/feed/",
        "https://cloud.google.com/blog/rss",
        "https://kubernetes.io/feed.xml",
        "https://www.docker.com/blog/feed/",
    ],
    
    'software_dev': [
        "https://github.blog/feed/",
        "https://stackoverflow.blog/feed/",
        "https://news.ycombinator.com/rss",
        "https://www.reddit.com/r/programming/.rss",
        "https://dev.to/feed/",
    ],
    
    'startups_vc': [
        "https://techcrunch.com/category/startups/feed/",
        "https://www.producthunt.com/feed",
        "https://news.crunchbase.com/feed/",
        "https://www.entrepreneur.com/latest.rss",
    ],
    
    'science_research': [
        "https://www.sciencedaily.com/rss/top/technology.xml",
        "https://www.nature.com/nature.rss",
        "https://www.science.org/rss/news_current.xml",
        "https://phys.org/rss-feed/technology-news/",
    ]
}

POSTED_FILE = "posted_items.json"

def load_posted_items():
    """Load previously posted item IDs"""
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_posted_item(item_id):
    """Save posted item ID to avoid duplicates"""
    posted = load_posted_items()
    posted.append(item_id)
    posted = posted[-2000:]
    with open(POSTED_FILE, 'w') as f:
        json.dump(posted, f)

def get_item_id(entry):
    """Generate unique ID for a feed entry"""
    unique_string = entry.get('link', '') + entry.get('title', '')
    return hashlib.md5(unique_string.encode()).hexdigest()

def fetch_news():
    """Fetch news from ALL RSS feeds"""
    all_entries = []
    total_feeds = sum(len(feeds) for feeds in RSS_FEEDS.values())
    current_feed = 0
    
    for category, feeds in RSS_FEEDS.items():
        for feed_url in feeds:
            current_feed += 1
            try:
                print(f"[{current_feed}/{total_feeds}] {feed_url[:60]}...")
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries[:5]:
                    all_entries.append({
                        'title': entry.get('title', 'No title'),
                        'link': entry.get('link', ''),
                        'published': entry.get('published', ''),
                        'source': feed.feed.get('title', 'Unknown'),
                        'category': category,
                        'id': get_item_id(entry)
                    })
            except Exception as e:
                print(f"  ⚠ Error: {str(e)[:40]}")
                continue
    
    return all_entries

def get_hashtags(category):
    """Get smart hashtags based on category"""
    hashtag_map = {
        'artificial_intelligence': "#AI #MachineLearning #DeepLearning",
        'cybersecurity': "#CyberSecurity #InfoSec #Hacking",
        'ethical_hacking': "#EthicalHacking #PenTesting #InfoSec",
        'data_breaches': "#DataBreach #Privacy #Security",
        'business_tech': "#TechNews #Business #Innovation",
        'stocks_finance': "#Stocks #Finance #Markets #Investing",
        'crypto_blockchain': "#Crypto #Blockchain #Web3",
        'cloud_devops': "#Cloud #DevOps #AWS #Kubernetes",
        'software_dev': "#Programming #Development #Coding",
        'startups_vc': "#Startups #Entrepreneurship #VC",
        'science_research': "#Science #Research #Technology"
    }
    return hashtag_map.get(category, "#Tech #News")

def format_post(entry, char_limit=300):
    """Format entry into a post"""
    title = entry['title']
    link = entry['link']
    hashtags = "\n\n" + get_hashtags(entry['category'])
    
    max_title_length = char_limit - len(link) - len(hashtags) - 5
    
    if len(title) > max_title_length:
        title = title[:max_title_length-3] + "..."
    
    return f"{title}\n\n{link}{hashtags}"

# ==================== BLUESKY ====================

def create_bluesky_session(handle, app_password):
    """Create Bluesky session"""
    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password}
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"Bluesky auth error: {e}")
        return None

def post_to_bluesky(text, session):
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
                    "text": text,
                    "createdAt": datetime.utcnow().isoformat() + "Z"
                }
            }
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Bluesky post error: {e}")
        return False

# ==================== TELEGRAM ====================

def post_to_telegram(text, bot_token, channel_id):
    """Post to Telegram"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": channel_id,
            "text": text,
            "disable_web_page_preview": False
        })
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram post error: {e}")
        return False

# ==================== MASTODON ====================

def post_to_mastodon(text, access_token, instance="mastodon.social"):
    """Post to Mastodon"""
    try:
        url = f"https://{instance}/api/v1/statuses"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"status": text}
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Mastodon post error: {e}")
        return False

# ==================== MAIN ====================

def main():
    """Main bot logic"""
    print(f"\n{'='*70}")
    print(f"🤖 Multi-Platform News Bot")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    
    # Get credentials
    bluesky_handle = os.environ.get('BLUESKY_HANDLE')
    bluesky_password = os.environ.get('BLUESKY_APP_PASSWORD')
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    telegram_channel = os.environ.get('TELEGRAM_CHANNEL_ID')
    mastodon_token = os.environ.get('MASTODON_ACCESS_TOKEN')
    
    # Check credentials
    platforms = []
    if bluesky_handle and bluesky_password:
        platforms.append('Bluesky')
    if telegram_token and telegram_channel:
        platforms.append('Telegram')
    if mastodon_token:
        platforms.append('Mastodon')
    
    if not platforms:
        print("❌ No platform credentials found!")
        return
    
    print(f"📱 Active platforms: {', '.join(platforms)}\n")
    
    # Authenticate Bluesky
    bluesky_session = None
    if 'Bluesky' in platforms:
        print("🔐 Authenticating Bluesky...")
        bluesky_session = create_bluesky_session(bluesky_handle, bluesky_password)
        if bluesky_session:
            print("✅ Bluesky ready")
        else:
            print("❌ Bluesky failed")
            platforms.remove('Bluesky')
    
    if 'Telegram' in platforms:
        print("✅ Telegram ready")
    if 'Mastodon' in platforms:
        print("✅ Mastodon ready")
    
    print(f"\n📰 Fetching from {sum(len(f) for f in RSS_FEEDS.values())} feeds...\n")
    
    # Fetch news
    entries = fetch_news()
    print(f"\n📊 Total entries: {len(entries)}")
    
    if not entries:
        print("⚠ No entries found")
        return
    
    # Filter new entries
    posted_items = load_posted_items()
    new_entries = [e for e in entries if e['id'] not in posted_items]
    print(f"✨ New entries: {len(new_entries)}\n")
    
    if not new_entries:
        print("ℹ️ No new content to post")
        return
    
    # Select posts
    random.shuffle(new_entries)
    num_posts = random.randint(4, 6)
    to_post = new_entries[:num_posts]
    
    print(f"🎯 Posting {len(to_post)} items\n")
    print(f"{'='*70}\n")
    
    # Post to all platforms
    for i, entry in enumerate(to_post, 1):
        print(f"📤 [{i}/{len(to_post)}]")
        print(f"   📁 {entry['category'].replace('_', ' ').title()}")
        print(f"   📰 {entry['title'][:65]}...")
        print(f"   🔗 {entry['source']}")
        
        post_text = format_post(entry)
        successes = []
        
        # Post to each platform
        if bluesky_session:
            if post_to_bluesky(post_text, bluesky_session):
                successes.append('Bluesky')
        
        if 'Telegram' in platforms:
            if post_to_telegram(post_text, telegram_token, telegram_channel):
                successes.append('Telegram')
        
        if 'Mastodon' in platforms:
            if post_to_mastodon(post_text, mastodon_token):
                successes.append('Mastodon')
        
        if successes:
            save_posted_item(entry['id'])
            print(f"   ✅ Posted to: {', '.join(successes)}")
        else:
            print(f"   ❌ Failed all platforms")
        
        # Wait between posts
        if i < len(to_post):
            wait = random.randint(15, 25)
            print(f"   ⏳ Waiting {wait}s...\n")
            time.sleep(wait)
        else:
            print()
    
    print(f"{'='*70}")
    print(f"✅ Session complete!")
    print(f"⏰ Next run in 2 hours")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
