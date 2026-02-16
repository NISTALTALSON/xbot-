#!/usr/bin/env python3
"""
Multi-Platform News Bot with Images - HUMANIZED VERSION
Natural, engaging posts that don't feel like bot spam
Bluesky + Telegram + Mastodon - Posts every hour
"""

import os
import feedparser
import time
from datetime import datetime
import random
import hashlib
import json
import requests
from bs4 import BeautifulSoup
from io import BytesIO
from urllib.parse import urljoin

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

# HUMAN-LIKE INTRO PHRASES
INTROS = {
    'artificial_intelligence': [
        "Just spotted this:",
        "Interesting AI development:",
        "Worth a look:",
        "This caught my attention:",
        "AI news:",
        "New in ML:",
        "Check this out:",
        "🔥",
        "👀",
    ],
    
    'cybersecurity': [
        "Security alert:",
        "Heads up:",
        "🚨",
        "New threat:",
        "This is concerning:",
        "FYI:",
        "Security update:",
        "Just saw this:",
        "⚠️",
    ],
    
    'ethical_hacking': [
        "New technique:",
        "Interesting find:",
        "Security researchers found:",
        "Worth knowing:",
        "🔓",
        "New exploit:",
        "Just dropped:",
    ],
    
    'data_breaches': [
        "🚨 Breach alert:",
        "Data leak:",
        "This is bad:",
        "Major breach:",
        "Compromised:",
        "⚠️ Alert:",
        "Security incident:",
    ],
    
    'business_tech': [
        "Tech news:",
        "Interesting:",
        "Just announced:",
        "Big move:",
        "Industry update:",
        "Worth reading:",
        "📰",
    ],
    
    'stocks_finance': [
        "Market update:",
        "📊",
        "Finance news:",
        "Worth watching:",
        "Market moving:",
        "Investment alert:",
        "💰",
    ],
    
    'crypto_blockchain': [
        "Crypto update:",
        "Web3 news:",
        "🚀",
        "Blockchain development:",
        "Crypto markets:",
        "DeFi update:",
        "💎",
    ],
    
    'cloud_devops': [
        "Cloud update:",
        "New from AWS/Azure/GCP:",
        "DevOps news:",
        "Infrastructure update:",
        "☁️",
        "Just released:",
    ],
    
    'software_dev': [
        "Dev news:",
        "For developers:",
        "Code update:",
        "Programming:",
        "💻",
        "New release:",
        "Tech update:",
    ],
    
    'startups_vc': [
        "Startup news:",
        "💡",
        "Funding alert:",
        "Entrepreneurship:",
        "New venture:",
        "Startup update:",
        "🚀",
    ],
    
    'science_research': [
        "Research:",
        "New study:",
        "Science update:",
        "🔬",
        "Interesting research:",
        "Study shows:",
    ]
}

# CASUAL COMMENTS (randomly added sometimes)
CASUAL_COMMENTS = [
    "Thoughts?",
    "What do you think?",
    "Interesting times.",
    "This is huge.",
    "Wild.",
    "Big if true.",
    "Worth a read.",
    "This matters.",
    "Keep an eye on this.",
    "Game changer?",
]

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

def extract_image_from_entry(entry):
    """Extract image URL from RSS entry"""
    if 'media_content' in entry and entry.media_content:
        return entry.media_content[0].get('url')
    
    if 'media_thumbnail' in entry and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    
    if 'enclosures' in entry and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    
    content = entry.get('content', [{}])[0].get('value', '') or entry.get('summary', '')
    if content and '<img' in content:
        try:
            soup = BeautifulSoup(content, 'html.parser')
            img = soup.find('img')
            if img and img.get('src'):
                return img['src']
        except:
            pass
    
    return None

def fetch_og_image(url):
    """Fetch Open Graph image from article URL"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.content, 'html.parser')
        
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            return urljoin(url, og_image['content'])
        
        twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter_image and twitter_image.get('content'):
            return urljoin(url, twitter_image['content'])
        
        img = soup.find('img')
        if img and img.get('src'):
            img_url = img['src']
            if not img_url.startswith('data:') and len(img_url) > 10:
                return urljoin(url, img_url)
    except:
        pass
    
    return None

def download_image(image_url):
    """Download image and return bytes"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        resp = requests.get(image_url, headers=headers, timeout=15)
        resp.raise_for_status()
        
        content_type = resp.headers.get('content-type', '')
        if 'image' not in content_type.lower():
            return None
        
        if len(resp.content) > 5 * 1024 * 1024:
            return None
        
        return resp.content
    except:
        return None

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
                    image_url = extract_image_from_entry(entry)
                    
                    all_entries.append({
                        'title': entry.get('title', 'No title'),
                        'link': entry.get('link', ''),
                        'published': entry.get('published', ''),
                        'source': feed.feed.get('title', 'Unknown'),
                        'category': category,
                        'image_url': image_url,
                        'id': get_item_id(entry)
                    })
            except Exception as e:
                print(f"  ⚠ Error: {str(e)[:40]}")
                continue
    
    return all_entries

def get_hashtags(category):
    """Get hashtags for category"""
    hashtag_map = {
        'artificial_intelligence': "#AI #MachineLearning",
        'cybersecurity': "#CyberSecurity #InfoSec",
        'ethical_hacking': "#Hacking #Security",
        'data_breaches': "#DataBreach #Privacy",
        'business_tech': "#Tech #Business",
        'stocks_finance': "#Finance #Markets",
        'crypto_blockchain': "#Crypto #Web3",
        'cloud_devops': "#Cloud #DevOps",
        'software_dev': "#Programming #Dev",
        'startups_vc': "#Startups",
        'science_research': "#Science #Research"
    }
    return hashtag_map.get(category, "#Tech")

def humanize_post(entry):
    """Create a natural, human-sounding post"""
    category = entry['category']
    title = entry['title']
    link = entry['link']
    
    # Clean up title (remove site names, extra punctuation)
    title = title.replace('...', '').strip()
    if ' - ' in title:
        title = title.split(' - ')[0].strip()
    if ' | ' in title:
        title = title.split(' | ')[0].strip()
    
    # Get random intro
    intros = INTROS.get(category, ["Check this out:"])
    intro = random.choice(intros)
    
    # Decide if we add a casual comment (30% chance)
    add_comment = random.random() < 0.3
    comment = random.choice(CASUAL_COMMENTS) if add_comment else ""
    
    # Get hashtags
    hashtags = get_hashtags(category)
    
    # Build post in different styles
    style = random.randint(1, 4)
    
    if style == 1:
        # Style 1: Intro + Title + Link + Comment + Hashtags
        post = f"{intro} {title}\n\n{link}"
        if comment:
            post += f"\n\n{comment}"
        post += f"\n\n{hashtags}"
    
    elif style == 2:
        # Style 2: Just emoji intro + Title + Link + Hashtags (cleaner)
        if intro in ['🔥', '👀', '🚨', '⚠️', '📰', '📊', '💰', '🚀', '💎', '☁️', '💻', '💡', '🔬', '🔓']:
            post = f"{intro} {title}\n\n{link}\n\n{hashtags}"
        else:
            post = f"{title}\n\n{link}\n\n{hashtags}"
    
    elif style == 3:
        # Style 3: Title + Link + Comment/Hashtags
        post = f"{title}\n\n{link}"
        if comment:
            post += f"\n\n{comment} {hashtags}"
        else:
            post += f"\n\n{hashtags}"
    
    else:
        # Style 4: Casual intro + Title only + Link below
        post = f"{intro}\n\n{title}\n\n{link}\n\n{hashtags}"
    
    # Ensure it fits (300 chars for Bluesky/Mastodon)
    if len(post) > 300:
        # Shorten title
        max_title = 300 - len(intro) - len(link) - len(hashtags) - (len(comment) if comment else 0) - 10
        title_short = title[:max_title] + "..."
        post = f"{intro} {title_short}\n\n{link}\n\n{hashtags}"
    
    return post

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

def upload_image_to_bluesky(image_bytes, session):
    """Upload image to Bluesky"""
    try:
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
            headers={
                "Authorization": f"Bearer {session['accessJwt']}",
                "Content-Type": "image/jpeg"
            },
            data=image_bytes
        )
        resp.raise_for_status()
        return resp.json()['blob']
    except:
        return None

def post_to_bluesky(text, session, image_bytes=None):
    """Post to Bluesky"""
    try:
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.utcnow().isoformat() + "Z"
        }
        
        if image_bytes:
            blob = upload_image_to_bluesky(image_bytes, session)
            if blob:
                record["embed"] = {
                    "$type": "app.bsky.embed.images",
                    "images": [{"alt": "Article image", "image": blob}]
                }
        
        resp = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": record
            }
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Bluesky error: {e}")
        return False

# ==================== TELEGRAM ====================

def post_to_telegram(text, bot_token, channel_id, image_bytes=None):
    """Post to Telegram"""
    try:
        base_url = f"https://api.telegram.org/bot{bot_token}"
        
        if image_bytes:
            files = {'photo': BytesIO(image_bytes)}
            data = {'chat_id': channel_id, 'caption': text}
            resp = requests.post(f"{base_url}/sendPhoto", data=data, files=files)
        else:
            resp = requests.post(f"{base_url}/sendMessage", json={
                "chat_id": channel_id,
                "text": text,
                "disable_web_page_preview": False
            })
        
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

# ==================== MASTODON ====================

def upload_image_to_mastodon(image_bytes, access_token, instance="mastodon.social"):
    """Upload image to Mastodon"""
    try:
        url = f"https://{instance}/api/v2/media"
        files = {'file': BytesIO(image_bytes)}
        headers = {"Authorization": f"Bearer {access_token}"}
        
        resp = requests.post(url, headers=headers, files=files)
        resp.raise_for_status()
        return resp.json()['id']
    except:
        return None

def post_to_mastodon(text, access_token, instance="mastodon.social", image_bytes=None):
    """Post to Mastodon"""
    try:
        url = f"https://{instance}/api/v1/statuses"
        headers = {"Authorization": f"Bearer {access_token}"}
        data = {"status": text}
        
        if image_bytes:
            media_id = upload_image_to_mastodon(image_bytes, access_token, instance)
            if media_id:
                data["media_ids"] = [media_id]
        
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Mastodon error: {e}")
        return False

# ==================== MAIN ====================

def main():
    """Main bot logic"""
    print(f"\n{'='*70}")
    print(f"🤖 Humanized Multi-Platform News Bot")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    
    # Get credentials
    bluesky_handle = os.environ.get('BLUESKY_HANDLE')
    bluesky_password = os.environ.get('BLUESKY_APP_PASSWORD')
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    telegram_channel = os.environ.get('TELEGRAM_CHANNEL_ID')
    mastodon_token = os.environ.get('MASTODON_ACCESS_TOKEN')
    
    platforms = []
    if bluesky_handle and bluesky_password:
        platforms.append('Bluesky')
    if telegram_token and telegram_channel:
        platforms.append('Telegram')
    if mastodon_token:
        platforms.append('Mastodon')
    
    if not platforms:
        print("❌ No credentials")
        return
    
    print(f"📱 Platforms: {', '.join(platforms)}\n")
    
    # Auth Bluesky
    bluesky_session = None
    if 'Bluesky' in platforms:
        bluesky_session = create_bluesky_session(bluesky_handle, bluesky_password)
        if bluesky_session:
            print("✅ Bluesky ready")
        else:
            platforms.remove('Bluesky')
    
    if 'Telegram' in platforms:
        print("✅ Telegram ready")
    if 'Mastodon' in platforms:
        print("✅ Mastodon ready")
    
    print(f"\n📰 Fetching news...\n")
    
    entries = fetch_news()
    print(f"\n📊 Total: {len(entries)}")
    
    if not entries:
        return
    
    posted_items = load_posted_items()
    new_entries = [e for e in entries if e['id'] not in posted_items]
    print(f"✨ New: {len(new_entries)}\n")
    
    if not new_entries:
        print("ℹ️ No new content")
        return
    
    random.shuffle(new_entries)
    num_posts = random.randint(4, 6)
    to_post = new_entries[:num_posts]
    
    print(f"🎯 Posting {len(to_post)} items\n{'='*70}\n")
    
    for i, entry in enumerate(to_post, 1):
        print(f"📤 [{i}/{len(to_post)}] {entry['title'][:50]}...")
        
        # Get image
        image_bytes = None
        image_url = entry.get('image_url')
        
        if not image_url:
            image_url = fetch_og_image(entry['link'])
        
        if image_url:
            image_bytes = download_image(image_url)
            if image_bytes:
                print(f"   🖼️  Image: {len(image_bytes)//1024}KB")
        
        # Create humanized post
        post_text = humanize_post(entry)
        successes = []
        
        # Post
        if bluesky_session:
            if post_to_bluesky(post_text, bluesky_session, image_bytes):
                successes.append('Bluesky')
        
        if 'Telegram' in platforms:
            if post_to_telegram(post_text, telegram_token, telegram_channel, image_bytes):
                successes.append('Telegram')
        
        if 'Mastodon' in platforms:
            if post_to_mastodon(post_text, mastodon_token, "mastodon.social", image_bytes):
                successes.append('Mastodon')
        
        if successes:
            save_posted_item(entry['id'])
            print(f"   ✅ {', '.join(successes)}")
        else:
            print(f"   ❌ Failed")
        
        if i < len(to_post):
            wait = random.randint(15, 25)
            print(f"   ⏳ {wait}s...\n")
            time.sleep(wait)
        else:
            print()
    
    print(f"{'='*70}\n✅ Done! Next run in 1 hour\n{'='*70}\n")

if __name__ == "__main__":
    main()
