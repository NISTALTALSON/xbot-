#!/usr/bin/env python3
"""
AISecurityDaily — Redesigned Bot v2
- Full article content extraction + Gemini summarization
- Bluesky rich text facets (proper clickable links)
- Engagement: like + smart reply to relevant posts
- Source attribution at bottom, deemphasized
- Telegram + Mastodon improved format
"""

import os
import feedparser
import time
import random
import hashlib
import json
import requests
import re
from datetime import datetime
from bs4 import BeautifulSoup
from io import BytesIO
from urllib.parse import urljoin

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

POSTED_FILE   = "posted_items.json"
ENGAGED_FILE  = "engaged_items.json"   # tracks posts we've liked/replied to
MAX_HISTORY   = 2000

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Posts per run
MIN_POSTS = 4
MAX_POSTS = 6

# Engagement per run
LIKES_PER_RUN   = 5   # how many posts to like on Bluesky
REPLIES_PER_RUN = 2   # how many posts to reply to on Bluesky

# ─────────────────────────────────────────
#  RSS FEEDS  (unchanged from v1)
# ─────────────────────────────────────────

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
        "https://null-byte.wonderhowto.com/rss.xml",
        "https://hakin9.org/feed/",
        "https://www.hackingarticles.in/feed/",
    ],
    'data_breaches': [
        "https://www.databreaches.net/feed/",
        "https://www.bleepingcomputer.com/feed/tag/data-breach/",
    ],
    'business_tech': [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss",
        "https://arstechnica.com/feed/",
        "https://www.zdnet.com/news/rss.xml",
    ],
    'crypto_blockchain': [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
    ],
    'cloud_devops': [
        "https://aws.amazon.com/blogs/aws/feed/",
        "https://azure.microsoft.com/en-us/blog/feed/",
        "https://kubernetes.io/feed.xml",
        "https://www.docker.com/blog/feed/",
    ],
    'software_dev': [
        "https://github.blog/feed/",
        "https://stackoverflow.blog/feed/",
        "https://news.ycombinator.com/rss",
        "https://dev.to/feed/",
    ],
    'startups_vc': [
        "https://techcrunch.com/category/startups/feed/",
        "https://news.crunchbase.com/feed/",
    ],
    'science_research': [
        "https://www.sciencedaily.com/rss/top/technology.xml",
        "https://phys.org/rss-feed/technology-news/",
    ]
}

# Hashtags per category
HASHTAGS = {
    'artificial_intelligence': "#AI #MachineLearning",
    'cybersecurity':           "#CyberSecurity #InfoSec",
    'ethical_hacking':         "#EthicalHacking #Security",
    'data_breaches':           "#DataBreach #Privacy",
    'business_tech':           "#Tech #Business",
    'stocks_finance':          "#Finance #Markets",
    'crypto_blockchain':       "#Crypto #Web3",
    'cloud_devops':            "#Cloud #DevOps",
    'software_dev':            "#Programming #Dev",
    'startups_vc':             "#Startups #VC",
    'science_research':        "#Science #Research",
}

# Search terms to find relevant posts on Bluesky for engagement
ENGAGEMENT_SEARCH = {
    'artificial_intelligence': ["AI", "LLM", "MachineLearning", "GPT"],
    'cybersecurity':           ["CyberSecurity", "InfoSec", "hacking"],
    'ethical_hacking':         ["pentesting", "bugbounty", "security"],
    'data_breaches':           ["databreach", "privacy", "leak"],
    'business_tech':           ["tech", "startup"],
    'crypto_blockchain':       ["crypto", "web3", "defi"],
    'cloud_devops':            ["devops", "cloud", "kubernetes"],
    'software_dev':            ["programming", "coding", "developer"],
    'startups_vc':             ["startup", "founder"],
    'science_research':        ["research", "science"],
}

# Smart reply templates per category (Gemini fills these in if available)
REPLY_TEMPLATES = {
    'cybersecurity':   ["This is why patching matters.", "Classic attack vector. Stay safe out there.", "Threat actors getting more sophisticated every week."],
    'artificial_intelligence': ["Wild how fast this space is moving.", "Interesting implications here.", "The race is on."],
    'ethical_hacking': ["Good find. PoC out yet?", "Solid research.", "CTF players are gonna love this."],
    'data_breaches':   ["Affected users should rotate credentials ASAP.", "Another one. Companies need to do better.", "Hope people use unique passwords."],
    'crypto_blockchain': ["Market's watching this closely.", "Interesting on-chain implications.", "DYOR as always."],
    'software_dev':    ["This is a nice pattern.", "Love seeing OSS move fast.", "Good DX improvement."],
    'cloud_devops':    ["Infrastructure getting smarter.", "This simplifies a lot of pipelines.", "Good update."],
    'business_tech':   ["Big moves in the industry.", "Worth keeping an eye on.", "Things are shifting."],
    'startups_vc':     ["Smart raise.", "Interesting market bet.", "Founders are building in a tough macro."],
    'science_research':["The research implications are huge.", "Peer review will be interesting on this.", "Solid methodology."],
}

# ─────────────────────────────────────────
#  PERSISTENCE
# ─────────────────────────────────────────

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except:
            pass
    return []

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)

def get_item_id(entry):
    s = entry.get('link', '') + entry.get('title', '')
    return hashlib.md5(s.encode()).hexdigest()

# ─────────────────────────────────────────
#  ARTICLE CONTENT FETCHING
# ─────────────────────────────────────────

def clean_text(text):
    """Normalize whitespace and remove junk"""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\[.*?\]', '', text)   # remove [tags]
    return text.strip()

def scrape_article_body(url):
    """
    Attempt to extract meaningful body text from an article URL.
    Returns cleaned text string (up to ~1500 chars) or empty string.
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.content, 'html.parser')

        # Remove noise
        for tag in soup(['script', 'style', 'nav', 'footer', 'header',
                         'aside', 'form', 'iframe', 'noscript', 'ads',
                         '[class*="ad-"]', '[class*="sidebar"]', '[class*="cookie"]']):
            tag.decompose()

        # Try article-specific containers first
        candidates = soup.select(
            'article, [class*="article-body"], [class*="post-body"], '
            '[class*="entry-content"], [class*="story-body"], '
            'main, [role="main"], .content, #content'
        )

        body_text = ""
        if candidates:
            # Pick the longest one
            best = max(candidates, key=lambda x: len(x.get_text()))
            paragraphs = best.find_all('p')
            body_text = ' '.join(p.get_text() for p in paragraphs if len(p.get_text()) > 40)

        # Fallback: all paragraphs on the page
        if len(body_text) < 100:
            paragraphs = soup.find_all('p')
            body_text = ' '.join(p.get_text() for p in paragraphs if len(p.get_text()) > 40)

        body_text = clean_text(body_text)
        return body_text[:3000]   # cap for Gemini prompt

    except Exception as e:
        print(f"   ⚠ Scrape failed: {str(e)[:50]}")
        return ""

def get_rss_summary(entry):
    """Pull summary text already in the RSS entry"""
    summary = entry.get('summary', '') or entry.get('description', '')
    if summary:
        soup = BeautifulSoup(summary, 'html.parser')
        return clean_text(soup.get_text())[:1500]
    content_list = entry.get('content', [])
    if content_list:
        soup = BeautifulSoup(content_list[0].get('value', ''), 'html.parser')
        return clean_text(soup.get_text())[:1500]
    return ""

# ─────────────────────────────────────────
#  GEMINI SUMMARIZATION
# ─────────────────────────────────────────

def gemini_summarize(title, body_text, category):
    """
    Ask Gemini to produce a tight 2-3 sentence summary suitable for a social post.
    Returns string or None if Gemini unavailable.
    """
    if not GEMINI_API_KEY or not body_text:
        return None

    prompt = (
        f"You are writing a concise social media post for a tech/security news account.\n"
        f"Category: {category.replace('_', ' ')}\n"
        f"Headline: {title}\n\n"
        f"Article excerpt:\n{body_text[:2000]}\n\n"
        f"Write 2-3 punchy, informative sentences (max 220 characters total) that:\n"
        f"- Tell the reader WHAT happened and WHY it matters\n"
        f"- Are written in plain English, no hype, no click-bait\n"
        f"- Do NOT start with 'In a', 'According to', or the source name\n"
        f"- Do NOT include any URL\n"
        f"Output ONLY the summary text, nothing else."
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=20
        )
        resp.raise_for_status()
        data = resp.json()
        text = data['candidates'][0]['content']['parts'][0]['text'].strip()
        return text
    except Exception as e:
        print(f"   ⚠ Gemini error: {str(e)[:60]}")
        return None

def gemini_reply(post_text, category):
    """Generate a thoughtful short reply to another user's post."""
    if not GEMINI_API_KEY:
        return None

    prompt = (
        f"You are a tech/security enthusiast on Bluesky replying to this post:\n\n"
        f"\"{post_text[:400]}\"\n\n"
        f"Write ONE short, genuine reply (1-2 sentences, max 100 chars). "
        f"Be conversational, add value or a quick thought. "
        f"No hashtags. No emojis unless it really fits. "
        f"Output ONLY the reply text."
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        return data['candidates'][0]['content']['parts'][0]['text'].strip()
    except:
        return None

# ─────────────────────────────────────────
#  POST FORMATTING
# ─────────────────────────────────────────

LEAD_EMOJIS = {
    'artificial_intelligence': ['🤖', '🧠', '⚡', '🔮'],
    'cybersecurity':           ['🛡️', '🔐', '⚠️', '🚨'],
    'ethical_hacking':         ['🔓', '🕵️', '💀', '🧩'],
    'data_breaches':           ['🚨', '🔴', '⛔', '💥'],
    'business_tech':           ['📡', '💡', '📰', '🔧'],
    'crypto_blockchain':       ['⛓️', '💎', '🚀', '📊'],
    'cloud_devops':            ['☁️', '🐳', '🔧', '⚙️'],
    'software_dev':            ['💻', '🛠️', '🐙', '📦'],
    'startups_vc':             ['🚀', '💡', '📈', '🏗️'],
    'science_research':        ['🔬', '🧬', '📡', '🌐'],
}

def clean_title(title):
    """Strip site names, extra punctuation from title"""
    title = title.replace('...', '').strip()
    for sep in [' - ', ' | ', ' — ', ' :: ']:
        if sep in title:
            title = title.split(sep)[0].strip()
    return title


def build_post_text(entry, summary):
    """
    Build the final post text.

    Format:
      EMOJI  Headline

      [summary text]

      HASHTAGS

      via Source ↗ URL
    """
    category  = entry['category']
    title     = clean_title(entry['title'])
    link      = entry['link']
    source    = entry['source']
    hashtags  = HASHTAGS.get(category, "#Tech")
    emoji     = random.choice(LEAD_EMOJIS.get(category, ['📰']))

    # Build body
    if summary:
        body = summary
    else:
        # Fallback: just use cleaned title as the body too
        body = title

    # "via Source ↗" — URL goes here at the bottom
    source_line = f"via {source} ↗"

    post = f"{emoji} {title}\n\n{body}\n\n{hashtags}\n\n{source_line}\n{link}"

    # Trim if over 300 chars (Bluesky + Mastodon limit)
    # URL is outside the text char count on Bluesky but Mastodon counts it
    # We'll keep the full form; Bluesky facets handle the link separately
    return post


# ─────────────────────────────────────────
#  BLUESKY — RICH TEXT + FACETS
# ─────────────────────────────────────────

def text_to_bytes(text):
    """Bluesky uses UTF-8 byte offsets for facets"""
    return text.encode('utf-8')

def find_byte_offsets(full_text, substring):
    """Find start/end byte offsets of a substring within full text"""
    full_bytes = text_to_bytes(full_text)
    sub_bytes  = text_to_bytes(substring)
    start = full_bytes.find(sub_bytes)
    if start == -1:
        return None, None
    return start, start + len(sub_bytes)

def build_bluesky_record(post_text, link, image_blob=None):
    """
    Build a Bluesky post record with proper facets so the URL
    and any #hashtags are clickable.
    """
    facets = []

    # 1. Detect URL in post text and make it a proper link facet
    url_pattern = re.compile(r'https?://\S+')
    for match in url_pattern.finditer(post_text):
        url    = match.group()
        start  = len(post_text[:match.start()].encode('utf-8'))
        end    = len(post_text[:match.end()].encode('utf-8'))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{
                "$type": "app.bsky.richtext.facet#link",
                "uri": url
            }]
        })

    # 2. Hashtag facets
    hashtag_pattern = re.compile(r'#(\w+)')
    for match in hashtag_pattern.finditer(post_text):
        tag   = match.group(1)
        start = len(post_text[:match.start()].encode('utf-8'))
        end   = len(post_text[:match.end()].encode('utf-8'))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{
                "$type": "app.bsky.richtext.facet#tag",
                "tag": tag
            }]
        })

    record = {
        "$type":     "app.bsky.feed.post",
        "text":      post_text,
        "createdAt": datetime.utcnow().isoformat() + "Z",
        "langs":     ["en"],
    }

    if facets:
        record["facets"] = facets

    if image_blob:
        record["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": [{"alt": "Article image", "image": image_blob}]
        }

    return record

# ─────────────────────────────────────────
#  BLUESKY API HELPERS
# ─────────────────────────────────────────

BSKY_BASE = "https://bsky.social/xrpc"

def bsky_create_session(handle, password):
    try:
        r = requests.post(f"{BSKY_BASE}/com.atproto.server.createSession",
                          json={"identifier": handle, "password": password})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Bluesky auth error: {e}")
        return None

def bsky_upload_blob(image_bytes, session):
    try:
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.uploadBlob",
            headers={"Authorization": f"Bearer {session['accessJwt']}",
                     "Content-Type": "image/jpeg"},
            data=image_bytes
        )
        r.raise_for_status()
        return r.json()['blob']
    except:
        return None

def bsky_post(record, session):
    """Create a post record on Bluesky"""
    try:
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"],
                  "collection": "app.bsky.feed.post",
                  "record": record}
        )
        r.raise_for_status()
        data = r.json()
        return data.get('uri'), data.get('cid')
    except Exception as e:
        print(f"   Bluesky post error: {e}")
        return None, None

def bsky_like(uri, cid, session):
    """Like a post by URI + CID"""
    try:
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.like",
                "record": {
                    "$type":     "app.bsky.feed.like",
                    "subject":   {"uri": uri, "cid": cid},
                    "createdAt": datetime.utcnow().isoformat() + "Z"
                }
            }
        )
        r.raise_for_status()
        return True
    except:
        return False

def bsky_reply(text, parent_uri, parent_cid, root_uri, root_cid, session):
    """Post a reply to a Bluesky post"""
    try:
        record = {
            "$type":     "app.bsky.feed.post",
            "text":      text[:300],
            "createdAt": datetime.utcnow().isoformat() + "Z",
            "langs":     ["en"],
            "reply": {
                "root":   {"uri": root_uri,   "cid": root_cid},
                "parent": {"uri": parent_uri, "cid": parent_cid}
            }
        }
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"],
                  "collection": "app.bsky.feed.post",
                  "record": record}
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Reply error: {e}")
        return False

def bsky_search_posts(query, limit=20, session=None):
    """Search Bluesky posts by keyword"""
    try:
        params = {"q": query, "limit": limit}
        headers = {}
        if session:
            headers["Authorization"] = f"Bearer {session['accessJwt']}"
        r = requests.get(f"{BSKY_BASE}/app.bsky.feed.searchPosts",
                         params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get('posts', [])
    except:
        return []

# ─────────────────────────────────────────
#  BLUESKY ENGAGEMENT
# ─────────────────────────────────────────

def run_engagement(session, categories_posted):
    """
    Like and reply to relevant posts on Bluesky.
    Picks search terms based on what categories were posted this run.
    """
    if not session:
        return

    engaged = load_json(ENGAGED_FILE)
    likes_done   = 0
    replies_done = 0

    # Build search queries from active categories
    queries = []
    for cat in categories_posted:
        terms = ENGAGEMENT_SEARCH.get(cat, [])
        queries.extend(terms)
    queries = list(set(queries))
    random.shuffle(queries)

    print(f"\n🤝 Engagement run — queries: {queries[:4]}")

    candidate_posts = []
    for q in queries[:4]:
        posts = bsky_search_posts(q, limit=15, session=session)
        candidate_posts.extend(posts)
        time.sleep(1)

    # Deduplicate by URI
    seen_uris = set()
    unique_posts = []
    for p in candidate_posts:
        uri = p.get('uri', '')
        if uri and uri not in seen_uris and uri not in engaged:
            seen_uris.add(uri)
            unique_posts.append(p)

    random.shuffle(unique_posts)

    for post in unique_posts:
        if likes_done >= LIKES_PER_RUN and replies_done >= REPLIES_PER_RUN:
            break

        uri = post.get('uri', '')
        cid = post.get('cid', '')
        author_handle = post.get('author', {}).get('handle', '')
        post_text = post.get('record', {}).get('text', '')

        # Skip our own posts
        if session.get('handle', '') in author_handle:
            continue
        # Skip posts with no text
        if not post_text or len(post_text) < 20:
            continue

        # ── LIKE ──────────────────────────────
        if likes_done < LIKES_PER_RUN:
            if bsky_like(uri, cid, session):
                likes_done += 1
                engaged.append(uri)
                print(f"   ❤️  Liked @{author_handle}: {post_text[:60]}...")
                time.sleep(random.uniform(2, 4))

        # ── REPLY ─────────────────────────────
        if replies_done < REPLIES_PER_RUN:
            # Determine category from post content (rough match)
            matched_cat = 'cybersecurity'
            for cat, terms in ENGAGEMENT_SEARCH.items():
                if any(t.lower() in post_text.lower() for t in terms):
                    matched_cat = cat
                    break

            # Try Gemini first; fallback to templates
            reply_text = gemini_reply(post_text, matched_cat)
            if not reply_text:
                reply_text = random.choice(REPLY_TEMPLATES.get(matched_cat, ["Interesting!"]))

            # The root is the same as parent for top-level posts
            reply_record = post.get('record', {})
            # Check if post itself is a reply (get root if so)
            parent_reply = reply_record.get('reply', {})
            root_uri = parent_reply.get('root', {}).get('uri', uri)
            root_cid = parent_reply.get('root', {}).get('cid', cid)

            if bsky_reply(reply_text, uri, cid, root_uri, root_cid, session):
                replies_done += 1
                print(f"   💬 Replied to @{author_handle}: \"{reply_text}\"")
                time.sleep(random.uniform(5, 10))   # longer wait between replies

    # Save updated engaged list
    save_json(ENGAGED_FILE, engaged[-MAX_HISTORY:])
    print(f"   ✅ Engagement done — {likes_done} likes, {replies_done} replies\n")

# ─────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────

def format_telegram(entry, summary):
    """Telegram supports HTML formatting"""
    title   = clean_title(entry['title'])
    source  = entry['source']
    link    = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji   = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))

    body = summary if summary else title

    # Telegram HTML
    post = (
        f"{emoji} <b>{title}</b>\n\n"
        f"{body}\n\n"
        f"{hashtags}\n\n"
        f"<a href=\"{link}\">Read on {source} ↗</a>"
    )
    return post

def post_to_telegram(text, bot_token, channel_id, image_bytes=None):
    base = f"https://api.telegram.org/bot{bot_token}"
    try:
        if image_bytes:
            files = {'photo': BytesIO(image_bytes)}
            data  = {'chat_id': channel_id, 'caption': text,
                     'parse_mode': 'HTML'}
            r = requests.post(f"{base}/sendPhoto", data=data, files=files)
        else:
            r = requests.post(f"{base}/sendMessage", json={
                "chat_id":    channel_id,
                "text":       text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            })
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Telegram error: {e}")
        return False

# ─────────────────────────────────────────
#  MASTODON
# ─────────────────────────────────────────

def format_mastodon(entry, summary):
    """Mastodon: plain text, 500 char limit"""
    title    = clean_title(entry['title'])
    link     = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))
    source   = entry['source']

    body = summary if summary else title

    post = f"{emoji} {title}\n\n{body}\n\n{hashtags}\n\nvia {source}\n{link}"

    if len(post) > 490:
        allowed = 490 - len(f"{emoji} {title}\n\n\n\n{hashtags}\n\nvia {source}\n{link}") - 3
        if allowed > 20:
            post = f"{emoji} {title}\n\n{body[:allowed]}...\n\n{hashtags}\n\nvia {source}\n{link}"
        else:
            post = f"{emoji} {title}\n\n{hashtags}\n\nvia {source}\n{link}"

    return post

def upload_mastodon_media(image_bytes, token, instance):
    try:
        r = requests.post(
            f"https://{instance}/api/v2/media",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": BytesIO(image_bytes)}
        )
        r.raise_for_status()
        return r.json()['id']
    except:
        return None

def post_to_mastodon(text, token, instance="mastodon.social", image_bytes=None):
    try:
        data = {"status": text}
        headers = {"Authorization": f"Bearer {token}"}
        if image_bytes:
            mid = upload_mastodon_media(image_bytes, token, instance)
            if mid:
                data["media_ids"] = [mid]
        r = requests.post(f"https://{instance}/api/v1/statuses",
                          headers=headers, json=data)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Mastodon error: {e}")
        return False

# ─────────────────────────────────────────
#  IMAGE UTILS
# ─────────────────────────────────────────

def extract_image_from_entry(entry):
    if hasattr(entry, 'media_content') and entry.media_content:
        return entry.media_content[0].get('url')
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        return entry.media_thumbnail[0].get('url')
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    content = (entry.get('content', [{}]) or [{}])[0].get('value', '') \
              or entry.get('summary', '')
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
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        for prop in ['og:image', 'twitter:image']:
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if tag and tag.get('content'):
                return urljoin(url, tag['content'])
    except:
        pass
    return None

def download_image(url):
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        r.raise_for_status()
        if 'image' not in r.headers.get('content-type', ''):
            return None
        if len(r.content) > 5 * 1024 * 1024:
            return None
        return r.content
    except:
        return None

# ─────────────────────────────────────────
#  NEWS FETCHING
# ─────────────────────────────────────────

def fetch_news():
    all_entries = []
    total = sum(len(v) for v in RSS_FEEDS.values())
    n = 0
    for category, feeds in RSS_FEEDS.items():
        for url in feeds:
            n += 1
            try:
                print(f"  [{n}/{total}] {url[:65]}...")
                feed = feedparser.parse(url)
                for e in feed.entries[:5]:
                    all_entries.append({
                        'title':     e.get('title', 'No title'),
                        'link':      e.get('link', ''),
                        'summary':   e.get('summary', ''),   # raw RSS summary
                        'content':   e.get('content', []),
                        'published': e.get('published', ''),
                        'source':    feed.feed.get('title', 'Unknown'),
                        'category':  category,
                        'image_url': extract_image_from_entry(e),
                        'id':        get_item_id(e),
                        '_entry':    e,    # keep raw entry for extra fields
                    })
            except Exception as e:
                print(f"  ⚠ {str(e)[:50]}")
    return all_entries

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print(f"🤖 AISecurityDaily Bot v2 — Rich Posts + Engagement")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    # Credentials
    bsky_handle   = os.environ.get('BLUESKY_HANDLE')
    bsky_password = os.environ.get('BLUESKY_APP_PASSWORD')
    tg_token      = os.environ.get('TELEGRAM_BOT_TOKEN')
    tg_channel    = os.environ.get('TELEGRAM_CHANNEL_ID')
    masto_token   = os.environ.get('MASTODON_ACCESS_TOKEN')

    platforms = []
    bsky_session = None

    if bsky_handle and bsky_password:
        bsky_session = bsky_create_session(bsky_handle, bsky_password)
        if bsky_session:
            print("✅ Bluesky — authenticated")
            platforms.append('bluesky')
        else:
            print("❌ Bluesky — auth failed")

    if tg_token and tg_channel:
        print("✅ Telegram — ready")
        platforms.append('telegram')

    if masto_token:
        print("✅ Mastodon — ready")
        platforms.append('mastodon')

    if GEMINI_API_KEY:
        print("✅ Gemini — ready (article summarization on)")
    else:
        print("⚠️  Gemini key missing — summaries will use RSS excerpts")

    if not platforms:
        print("❌ No platforms configured. Exiting.")
        return

    print(f"\n📰 Fetching RSS feeds…\n")
    entries = fetch_news()
    print(f"\n📊 Total entries: {len(entries)}")

    posted  = load_json(POSTED_FILE)
    new_entries = [e for e in entries if e['id'] not in posted]
    print(f"✨ Unposted: {len(new_entries)}\n")

    if not new_entries:
        print("ℹ️ Nothing new to post.")
        # Still run engagement even if no new posts
        if bsky_session:
            cats = list(RSS_FEEDS.keys())
            run_engagement(bsky_session, random.sample(cats, min(3, len(cats))))
        return

    random.shuffle(new_entries)
    to_post = new_entries[:random.randint(MIN_POSTS, MAX_POSTS)]
    categories_posted = list({e['category'] for e in to_post})

    print(f"🎯 Posting {len(to_post)} items\n{'─'*70}")

    for i, entry in enumerate(to_post, 1):
        title    = clean_title(entry['title'])
        link     = entry['link']
        category = entry['category']

        print(f"\n[{i}/{len(to_post)}] {title[:60]}…")
        print(f"   📂 {category}  |  🔗 {link[:55]}…")

        # ── 1. Get article content ──────────────────────────────────────
        # First try RSS summary, then scrape if it's too thin
        rss_body = get_rss_summary(entry)
        if len(rss_body) < 150:
            print(f"   🌐 Scraping article…")
            scraped = scrape_article_body(link)
            body_text = scraped if len(scraped) > len(rss_body) else rss_body
        else:
            body_text = rss_body

        # ── 2. Summarize ────────────────────────────────────────────────
        summary = None
        if body_text:
            print(f"   🧠 Summarizing ({len(body_text)} chars)…")
            summary = gemini_summarize(title, body_text, category)
            if summary:
                print(f"   ✍  Summary: {summary[:80]}…")
            else:
                # Fallback: trim RSS body to ~200 chars at sentence boundary
                cut = body_text[:220]
                last_period = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'))
                summary = cut[:last_period+1] if last_period > 80 else cut + "…"
                print(f"   ✍  Fallback summary used")

        # ── 3. Image ────────────────────────────────────────────────────
        image_bytes = None
        image_url   = entry.get('image_url') or fetch_og_image(link)
        if image_url:
            image_bytes = download_image(image_url)
            if image_bytes:
                print(f"   🖼️  Image: {len(image_bytes)//1024}KB")

        # ── 4. Post to each platform ────────────────────────────────────
        successes = []

        # Bluesky
        if 'bluesky' in platforms:
            post_text = build_post_text(entry, summary)
            blob      = bsky_upload_blob(image_bytes, bsky_session) if image_bytes else None
            record    = build_bluesky_record(post_text, link, blob)
            uri, cid  = bsky_post(record, bsky_session)
            if uri:
                successes.append('Bluesky')

        # Telegram
        if 'telegram' in platforms:
            tg_text = format_telegram(entry, summary)
            if post_to_telegram(tg_text, tg_token, tg_channel, image_bytes):
                successes.append('Telegram')

        # Mastodon
        if 'mastodon' in platforms:
            masto_text = format_mastodon(entry, summary)
            if post_to_mastodon(masto_text, masto_token, image_bytes=image_bytes):
                successes.append('Mastodon')

        # ── 5. Save & wait ──────────────────────────────────────────────
        if successes:
            posted.append(entry['id'])
            save_json(POSTED_FILE, posted[-MAX_HISTORY:])
            print(f"   ✅ Posted → {', '.join(successes)}")
        else:
            print(f"   ❌ All platforms failed")

        if i < len(to_post):
            wait = random.randint(18, 30)
            print(f"   ⏳ Waiting {wait}s…")
            time.sleep(wait)

    # ── 6. Engagement pass ──────────────────────────────────────────────
    if bsky_session:
        run_engagement(bsky_session, categories_posted)

    print(f"\n{'='*70}")
    print(f"✅ Done — {len(to_post)} posts, next run in 1 hour")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
