#!/usr/bin/env python3
"""
AISecurityDaily Bot v3
- Posts every 1 hour via GitHub Actions cron
- Rich, longer post format (not just 2 sentences)
- Non-repetitive, human-sounding replies using Gemini
- Sensitive topic filter (no political/religious/tragedy replies)
- Replies to 7+ top engaging posts per run
- Engagement-optimized post copy
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

POSTED_FILE      = "posted_items.json"
ENGAGED_FILE     = "engaged_items.json"
USED_REPLIES_FILE = "used_replies.json"   # tracks recently used reply phrases
MAX_HISTORY      = 2000

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Posts per run (1hr = 1 run, post 1-2 items to feel natural)
MIN_POSTS = 1
MAX_POSTS = 2

# Engagement per run
LIKES_PER_RUN   = 8    # like more posts
REPLIES_PER_RUN = 7    # reply to 7+ posts per run

# How many recent replies to remember (to avoid repetition)
REPLY_MEMORY = 50

# ─────────────────────────────────────────
#  SENSITIVE TOPIC FILTER
# ─────────────────────────────────────────

SENSITIVE_KEYWORDS = [
    # Politics
    "trump", "biden", "democrat", "republican", "election", "vote", "congress",
    "senate", "political", "politician", "president", "prime minister", "modi",
    "boris", "abortion", "gun control", "immigration",
    # Religion
    "islam", "muslim", "christian", "hindu", "jew", "jewish", "religion",
    "god", "allah", "church", "mosque", "temple", "prayer", "faith",
    # Tragedy / violence
    "shooting", "massacre", "genocide", "terrorist", "attack", "bombing",
    "killed", "murdered", "death toll", "victims", "suicide", "self-harm",
    "war", "invasion", "missile", "hostage", "kidnap",
    # Controversial social
    "racism", "racist", "sexist", "lgbtq", "transgender", "pronoun",
    "white supremacy", "nazi", "extremist",
]

def is_sensitive_post(text):
    """Returns True if a post touches sensitive topics we should skip."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in SENSITIVE_KEYWORDS)

# ─────────────────────────────────────────
#  RSS FEEDS
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

HASHTAGS = {
    'artificial_intelligence': "#AI #MachineLearning #LLM",
    'cybersecurity':           "#CyberSecurity #InfoSec #Hacking",
    'ethical_hacking':         "#EthicalHacking #PenTest #BugBounty",
    'data_breaches':           "#DataBreach #Privacy #InfoSec",
    'business_tech':           "#Tech #BigTech #Innovation",
    'stocks_finance':          "#Finance #Markets #Investing",
    'crypto_blockchain':       "#Crypto #Web3 #DeFi",
    'cloud_devops':            "#Cloud #DevOps #Infrastructure",
    'software_dev':            "#Programming #Dev #OpenSource",
    'startups_vc':             "#Startups #VC #Founders",
    'science_research':        "#Science #Research #Tech",
}

ENGAGEMENT_SEARCH = {
    'artificial_intelligence': ["AI model", "LLM", "machine learning", "GPT", "Claude AI"],
    'cybersecurity':           ["cybersecurity", "InfoSec", "zero-day", "vulnerability"],
    'ethical_hacking':         ["pentesting", "bug bounty", "exploit", "CTF"],
    'data_breaches':           ["data breach", "privacy leak", "data exposed"],
    'business_tech':           ["tech layoffs", "startup funding", "big tech"],
    'crypto_blockchain':       ["crypto crash", "web3", "DeFi protocol"],
    'cloud_devops':            ["kubernetes", "cloud native", "DevOps pipeline"],
    'software_dev':            ["open source", "developer tools", "new framework"],
    'startups_vc':             ["startup founder", "seed round", "YC batch"],
    'science_research':        ["new research", "study finds", "breakthrough"],
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
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()

def scrape_article_body(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/120.0.0.0 Safari/537.36'
        }
        resp = requests.get(url, headers=headers, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header',
                         'aside', 'form', 'iframe', 'noscript']):
            tag.decompose()
        candidates = soup.select(
            'article, [class*="article-body"], [class*="post-body"], '
            '[class*="entry-content"], [class*="story-body"], '
            'main, [role="main"], .content, #content'
        )
        body_text = ""
        if candidates:
            best = max(candidates, key=lambda x: len(x.get_text()))
            paragraphs = best.find_all('p')
            body_text = ' '.join(p.get_text() for p in paragraphs if len(p.get_text()) > 40)
        if len(body_text) < 100:
            paragraphs = soup.find_all('p')
            body_text = ' '.join(p.get_text() for p in paragraphs if len(p.get_text()) > 40)
        body_text = clean_text(body_text)
        return body_text[:4000]
    except Exception as e:
        print(f"   ⚠ Scrape failed: {str(e)[:50]}")
        return ""

def get_rss_summary(entry):
    summary = entry.get('summary', '') or entry.get('description', '')
    if summary:
        soup = BeautifulSoup(summary, 'html.parser')
        return clean_text(soup.get_text())[:2000]
    content_list = entry.get('content', [])
    if content_list:
        soup = BeautifulSoup(content_list[0].get('value', ''), 'html.parser')
        return clean_text(soup.get_text())[:2000]
    return ""

# ─────────────────────────────────────────
#  GEMINI — LONG-FORM SUMMARIZATION
# ─────────────────────────────────────────

def gemini_summarize(title, body_text, category):
    """
    Produces a longer, engagement-optimized post body (4-6 sentences).
    Ends with a hook question to drive replies.
    """
    if not GEMINI_API_KEY or not body_text:
        return None

    prompt = (
        f"You are writing a social media post for a tech/security news account called AISecurityDaily.\n"
        f"Category: {category.replace('_', ' ')}\n"
        f"Headline: {title}\n\n"
        f"Article content:\n{body_text[:3000]}\n\n"
        f"Write a post body (4-6 sentences, max 500 characters total) that:\n"
        f"1. Opens with what happened — be direct and specific\n"
        f"2. Explains WHY it matters in plain terms (impact, scale, who's affected)\n"
        f"3. Adds one surprising or lesser-known detail from the article\n"
        f"4. Ends with ONE short engaging question that invites replies (e.g. 'What's your take?', 'Has your org patched this yet?', 'Will this change how you think about X?')\n"
        f"Rules:\n"
        f"- Plain English, no corporate jargon, no hype words\n"
        f"- Do NOT start with 'In a', 'According to', or the source name\n"
        f"- Do NOT include any URL\n"
        f"- No hashtags in the body\n"
        f"Output ONLY the post body text, nothing else."
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=25
        )
        resp.raise_for_status()
        data = resp.json()
        text = data['candidates'][0]['content']['parts'][0]['text'].strip()
        return text
    except Exception as e:
        print(f"   ⚠ Gemini summarize error: {str(e)[:60]}")
        return None

# ─────────────────────────────────────────
#  GEMINI — UNIQUE HUMAN-SOUNDING REPLIES
# ─────────────────────────────────────────

def gemini_reply(post_text, category, used_replies):
    """
    Generates a unique, human-sounding reply.
    Passes recently used replies to Gemini so it avoids repeating them.
    Skips if post is on sensitive topics.
    """
    if not GEMINI_API_KEY:
        return None

    if is_sensitive_post(post_text):
        print(f"   🚫 Skipping reply — sensitive topic detected")
        return None

    recent = used_replies[-20:] if used_replies else []
    avoid_str = "\n".join(f"- {r}" for r in recent) if recent else "None"

    prompt = (
        f"You are a real person who works in tech/security, casually browsing Bluesky.\n"
        f"You just read this post:\n\n\"{post_text[:500]}\"\n\n"
        f"Write ONE short reply (1-2 sentences, max 120 characters). Rules:\n"
        f"- Sound like a real human, not a bot\n"
        f"- Add genuine value: a quick insight, a follow-up thought, a question, or a relatable reaction\n"
        f"- Vary your style: sometimes curious, sometimes direct, sometimes slightly humorous\n"
        f"- NO hashtags, NO emojis unless it really fits naturally\n"
        f"- NEVER start with 'Great', 'Interesting', 'Wow', 'This is', 'Indeed', 'Absolutely'\n"
        f"- Do NOT repeat or closely echo any of these recently used replies:\n{avoid_str}\n\n"
        f"Output ONLY the reply text, nothing else."
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data['candidates'][0]['content']['parts'][0]['text'].strip()

        # Final guard: reject if it starts with banned openers
        banned_openers = ["great", "interesting", "wow", "this is", "indeed", "absolutely", "fascinating"]
        if any(reply.lower().startswith(b) for b in banned_openers):
            return None

        return reply
    except Exception as e:
        print(f"   ⚠ Gemini reply error: {str(e)[:60]}")
        return None

# ─────────────────────────────────────────
#  FALLBACK REPLY POOL (used when Gemini fails)
#  Large diverse pool — picked randomly, tracked to avoid repeats
# ─────────────────────────────────────────

FALLBACK_REPLIES = {
    'cybersecurity': [
        "Patching schedule needs to be tighter than this.",
        "Attack surface just got wider. Thanks for sharing.",
        "The disclosure timeline here is worth reading closely.",
        "Nation-state level tactics showing up in commodity attacks now.",
        "Anyone running this in prod should check their logs.",
        "Threat intel teams are gonna have a busy week.",
        "Zero-days don't wait for your patch window.",
        "The lateral movement potential here is the scary part.",
        "Detection engineering folks — this one's for you.",
        "Vendor response time matters as much as the fix itself.",
    ],
    'artificial_intelligence': [
        "The benchmark numbers are impressive but real-world deployment is always the real test.",
        "Curious how this holds up against adversarial inputs.",
        "The compute requirements here tell an interesting story.",
        "Fine-tuning behavior at scale is still an unsolved problem.",
        "Safety alignment research can't move fast enough tbh.",
        "Training data provenance is the question nobody wants to answer.",
        "The gap between paper results and production is often enormous.",
        "Inference costs are the hidden bottleneck everyone ignores.",
        "Open weights vs closed — that debate is not going away.",
        "Whoever cracks efficient reasoning first wins the decade.",
    ],
    'ethical_hacking': [
        "PoC timing always sparks a debate. Responsible disclosure done right here though.",
        "Bug bounty programs need to pay better for this class of vuln.",
        "The write-up quality on this is solid.",
        "Chaining these together is where it gets dangerous.",
        "Classic misconfig leading somewhere it shouldn't.",
        "CVSS score doesn't tell the full exploitation story.",
        "The recon phase described here is textbook.",
        "Scope creep during pentests finds the best bugs.",
        "Purple team exercises would've caught this earlier.",
        "Vendor gave a CVE but no credit. Classic.",
    ],
    'data_breaches': [
        "Notification timeline is the part that needs scrutiny.",
        "Third-party vendor risk is the blind spot that keeps delivering.",
        "Affected users should assume credentials are already circulating.",
        "The breach is bad. The cover-up attempt is worse.",
        "GDPR clock starts ticking at discovery, not disclosure.",
        "Password reuse makes a breach's blast radius 10x bigger.",
        "Data minimization would've limited exposure here significantly.",
        "Insurance claim incoming. Cyber premiums won't survive this decade.",
        "Breach fatigue is real but this one warrants attention.",
        "The forensic timeline in the disclosure is unusually honest.",
    ],
    'crypto_blockchain': [
        "On-chain forensics will trace this faster than people expect.",
        "Liquidity pool design flaws are the gift that keeps giving.",
        "The audit was there. Nobody read it.",
        "Bridge exploits remain the most reliable attack surface in DeFi.",
        "Rug or hack — the outcome for users is the same.",
        "MEV extraction strategies are getting creative.",
        "Regulatory clarity would actually help here ironically.",
        "zkProof adoption can't come fast enough for privacy.",
        "The tokenomics were always the red flag.",
        "Smart contract immutability cuts both ways.",
    ],
    'software_dev': [
        "Supply chain risk hides in the transitive dependencies.",
        "Docs are wrong again. Codebase wins.",
        "The PR description is half the value of the feature.",
        "Technical debt compounds like interest. Nobody budgets for it.",
        "Observability built in from day one vs bolted on later — night and day.",
        "Type safety at this level of the stack changes everything.",
        "Feature flags should be in every deployment pipeline by now.",
        "The test coverage tells a more honest story than the architecture diagram.",
        "OSS maintainer burnout is a supply chain vulnerability.",
        "Nobody uses the happy path in production.",
    ],
    'cloud_devops': [
        "Egress costs are the hidden tax on every cloud migration.",
        "IAM misconfiguration is still the #1 cloud breach vector.",
        "FinOps should be mandatory reading for every infra team.",
        "Multi-cloud is a strategy until the abstractions leak.",
        "Drift detection in IaC saves weeks of debugging.",
        "Service mesh complexity is real. Not always worth it.",
        "RBAC at this granularity is the right move.",
        "Backup restoration drills need to be quarterly, not yearly.",
        "Observability without context is just noise.",
        "Cold start latency is still the serverless elephant in the room.",
    ],
    'business_tech': [
        "Pivot or die is a real strategy now.",
        "The real story is in the executive departures footnote.",
        "Consolidation was inevitable. Watch who absorbs what next.",
        "Margins under pressure across the whole sector.",
        "Regulatory pressure is reshaping product roadmaps in real time.",
        "The enterprise sales cycle is longer than any runway.",
        "Distribution is the moat nobody talks about.",
        "Workforce reduction announcements always spike hiring for competitors.",
        "Platform lock-in is back as a strategy. Deliberately.",
        "The market is pricing in a lot of optimism here.",
    ],
    'startups_vc': [
        "Seed extension rounds are telling a more honest story than the headline.",
        "PMF before scaling — still the rule, still ignored.",
        "The cap table complexity at Series A is already alarming.",
        "Founder-market fit matters more than the idea at this stage.",
        "Burn rate discipline is back in fashion.",
        "Customer acquisition cost at this growth rate is unsustainable.",
        "The problem is real. The defensibility question remains.",
        "Building in a down cycle filters signal from noise.",
        "Acqui-hires are back. Team was the product.",
        "Revenue-based financing making a quiet comeback.",
    ],
    'science_research': [
        "Sample size and replication will be the follow-up questions.",
        "The peer review timeline on this one was unusually fast.",
        "Translation from lab results to clinical application is where most die.",
        "Methodology section is the most honest part of any paper.",
        "Industry funding disclosure is buried but worth reading.",
        "The null result buried in supplementary materials is the interesting part.",
        "Reproducibility crisis or genuine breakthrough — time will tell.",
        "Citation graph on this paper is worth exploring.",
        "The real-world constraints aren't in the abstract.",
        "Preprint vs peer-reviewed distinction matters a lot here.",
    ],
}

def get_fallback_reply(category, used_replies):
    """Get a fallback reply that hasn't been used recently."""
    pool = FALLBACK_REPLIES.get(category, FALLBACK_REPLIES['business_tech'])
    unused = [r for r in pool if r not in used_replies]
    if not unused:
        unused = pool  # reset if all used
    return random.choice(unused)

# ─────────────────────────────────────────
#  POST FORMATTING
# ─────────────────────────────────────────

LEAD_EMOJIS = {
    'artificial_intelligence': ['🤖', '🧠', '⚡', '🔮', '🚀'],
    'cybersecurity':           ['🛡️', '🔐', '⚠️', '🚨', '🔴'],
    'ethical_hacking':         ['🔓', '🕵️', '💀', '🧩', '🎯'],
    'data_breaches':           ['🚨', '🔴', '⛔', '💥', '🕳️'],
    'business_tech':           ['📡', '💡', '📰', '🔧', '🌐'],
    'crypto_blockchain':       ['⛓️', '💎', '🚀', '📊', '🔗'],
    'cloud_devops':            ['☁️', '🐳', '🔧', '⚙️', '🛠️'],
    'software_dev':            ['💻', '🛠️', '🐙', '📦', '🔩'],
    'startups_vc':             ['🚀', '💡', '📈', '🏗️', '💰'],
    'science_research':        ['🔬', '🧬', '📡', '🌐', '🔭'],
}

def clean_title(title):
    title = title.replace('...', '').strip()
    for sep in [' - ', ' | ', ' — ', ' :: ']:
        if sep in title:
            title = title.split(sep)[0].strip()
    return title

def build_post_text(entry, summary):
    """
    Engagement-optimized format:

      EMOJI  Headline

      [rich body — 4-6 sentences with hook question at end]

      HASHTAGS

      Source: Name
      🔗 URL
    """
    category  = entry['category']
    title     = clean_title(entry['title'])
    link      = entry['link']
    source    = entry['source']
    hashtags  = HASHTAGS.get(category, "#Tech")
    emoji     = random.choice(LEAD_EMOJIS.get(category, ['📰']))

    body = summary if summary else title

    # Source at the very bottom, deemphasized
    post = f"{emoji} {title}\n\n{body}\n\n{hashtags}\n\nSource: {source}\n{link}"

    return post

# ─────────────────────────────────────────
#  BLUESKY RICH TEXT
# ─────────────────────────────────────────

def build_bluesky_record(post_text, link, image_blob=None):
    facets = []
    url_pattern = re.compile(r'https?://\S+')
    for match in url_pattern.finditer(post_text):
        url   = match.group()
        start = len(post_text[:match.start()].encode('utf-8'))
        end   = len(post_text[:match.end()].encode('utf-8'))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
        })
    hashtag_pattern = re.compile(r'#(\w+)')
    for match in hashtag_pattern.finditer(post_text):
        tag   = match.group(1)
        start = len(post_text[:match.start()].encode('utf-8'))
        end   = len(post_text[:match.end()].encode('utf-8'))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]
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
#  BLUESKY API
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

def bsky_search_posts(query, limit=25, session=None):
    """Search Bluesky posts — larger limit to find top engaging posts."""
    try:
        params = {"q": query, "limit": limit, "sort": "top"}  # sort=top for most engaged
        headers = {}
        if session:
            headers["Authorization"] = f"Bearer {session['accessJwt']}"
        r = requests.get(f"{BSKY_BASE}/app.bsky.feed.searchPosts",
                         params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json().get('posts', [])
    except:
        return []

def get_post_engagement_score(post):
    """Score a post by like + reply + repost count for ranking."""
    counts = post.get('likeCount', 0) + post.get('replyCount', 0) * 2 + post.get('repostCount', 0)
    return counts

# ─────────────────────────────────────────
#  ENGAGEMENT ENGINE — 7+ REPLIES
# ─────────────────────────────────────────

def run_engagement(session, categories_posted):
    """
    Like and reply to top engaging relevant posts on Bluesky.
    - Targets 7+ replies per run
    - Filters sensitive topics
    - Tracks used replies to avoid repetition
    - Sorts candidates by engagement score
    """
    if not session:
        return

    engaged      = load_json(ENGAGED_FILE)
    used_replies = load_json(USED_REPLIES_FILE)
    likes_done   = 0
    replies_done = 0

    # Build search queries from active categories
    queries = []
    for cat in categories_posted:
        terms = ENGAGEMENT_SEARCH.get(cat, [])
        queries.extend(random.sample(terms, min(2, len(terms))))
    # Add a few extra broad terms to fill the 7 reply target
    queries += ["cybersecurity news", "AI model released", "tech startup", "data breach 2025"]
    queries = list(set(queries))
    random.shuffle(queries)

    print(f"\n🤝 Engagement run — {REPLIES_PER_RUN}+ replies targeted")
    print(f"   Queries: {queries[:6]}")

    candidate_posts = []
    for q in queries[:8]:  # search more queries to get enough candidates
        posts = bsky_search_posts(q, limit=25, session=session)
        candidate_posts.extend(posts)
        time.sleep(0.8)

    # Deduplicate by URI
    seen_uris = set()
    unique_posts = []
    for p in candidate_posts:
        uri = p.get('uri', '')
        if uri and uri not in seen_uris and uri not in engaged:
            seen_uris.add(uri)
            unique_posts.append(p)

    # Sort by engagement score — target TOP posts
    unique_posts.sort(key=get_post_engagement_score, reverse=True)

    print(f"   Found {len(unique_posts)} unique candidate posts\n")

    for post in unique_posts:
        if likes_done >= LIKES_PER_RUN and replies_done >= REPLIES_PER_RUN:
            break

        uri           = post.get('uri', '')
        cid           = post.get('cid', '')
        author_handle = post.get('author', {}).get('handle', '')
        post_text     = post.get('record', {}).get('text', '')
        eng_score     = get_post_engagement_score(post)

        # Skip our own posts
        if session.get('handle', '') in author_handle:
            continue
        # Skip posts with no meaningful text
        if not post_text or len(post_text) < 30:
            continue
        # Skip sensitive topics
        if is_sensitive_post(post_text):
            print(f"   🚫 Skip (sensitive): {post_text[:50]}...")
            continue

        # ── LIKE ──────────────────────────────────────────────────────
        if likes_done < LIKES_PER_RUN:
            if bsky_like(uri, cid, session):
                likes_done += 1
                engaged.append(uri)
                print(f"   ❤️  Liked [{eng_score}pts] @{author_handle}: {post_text[:55]}...")
                time.sleep(random.uniform(1.5, 3))

        # ── REPLY ─────────────────────────────────────────────────────
        if replies_done < REPLIES_PER_RUN:
            # Detect category
            matched_cat = 'business_tech'
            for cat, terms in ENGAGEMENT_SEARCH.items():
                if any(t.lower() in post_text.lower() for t in terms):
                    matched_cat = cat
                    break

            # Try Gemini first for unique reply
            reply_text = gemini_reply(post_text, matched_cat, used_replies)

            # Fallback: large diverse pool, avoiding recently used
            if not reply_text:
                reply_text = get_fallback_reply(matched_cat, used_replies)

            if not reply_text:
                continue

            # Get thread root info
            reply_record = post.get('record', {})
            parent_reply = reply_record.get('reply', {})
            root_uri = parent_reply.get('root', {}).get('uri', uri)
            root_cid = parent_reply.get('root', {}).get('cid', cid)

            if bsky_reply(reply_text, uri, cid, root_uri, root_cid, session):
                replies_done += 1
                # Track this reply text to avoid reusing it
                used_replies.append(reply_text)
                print(f"   💬 [{replies_done}/{REPLIES_PER_RUN}] @{author_handle}: \"{reply_text}\"")
                time.sleep(random.uniform(6, 12))  # human-like gap between replies

    # Save state
    save_json(ENGAGED_FILE, engaged[-MAX_HISTORY:])
    save_json(USED_REPLIES_FILE, used_replies[-REPLY_MEMORY:])
    print(f"\n   ✅ Engagement done — {likes_done} likes, {replies_done} replies\n")

# ─────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────

def format_telegram(entry, summary):
    title    = clean_title(entry['title'])
    source   = entry['source']
    link     = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))
    body     = summary if summary else title
    post = (
        f"{emoji} <b>{title}</b>\n\n"
        f"{body}\n\n"
        f"{hashtags}\n\n"
        f"Source: {source}\n"
        f"<a href=\"{link}\">Read full article ↗</a>"
    )
    return post

def post_to_telegram(text, bot_token, channel_id, image_bytes=None):
    base = f"https://api.telegram.org/bot{bot_token}"
    try:
        if image_bytes:
            files = {'photo': BytesIO(image_bytes)}
            data  = {'chat_id': channel_id, 'caption': text, 'parse_mode': 'HTML'}
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
    title    = clean_title(entry['title'])
    link     = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))
    source   = entry['source']
    body     = summary if summary else title
    post = f"{emoji} {title}\n\n{body}\n\n{hashtags}\n\nSource: {source}\n{link}"
    if len(post) > 490:
        allowed = 490 - len(f"{emoji} {title}\n\n\n\n{hashtags}\n\nSource: {source}\n{link}") - 3
        post = f"{emoji} {title}\n\n{body[:max(20,allowed)]}...\n\n{hashtags}\n\nSource: {source}\n{link}"
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
                        'summary':   e.get('summary', ''),
                        'content':   e.get('content', []),
                        'published': e.get('published', ''),
                        'source':    feed.feed.get('title', 'Unknown'),
                        'category':  category,
                        'image_url': extract_image_from_entry(e),
                        'id':        get_item_id(e),
                        '_entry':    e,
                    })
            except Exception as e:
                print(f"  ⚠ {str(e)[:50]}")
    return all_entries

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────

def main():
    print(f"\n{'='*70}")
    print(f"🤖 AISecurityDaily Bot v3 — Hourly | Human Replies | Sensitive Filter")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")

    bsky_handle   = os.environ.get('BLUESKY_HANDLE')
    bsky_password = os.environ.get('BLUESKY_APP_PASSWORD')
    tg_token      = os.environ.get('TELEGRAM_BOT_TOKEN')
    tg_channel    = os.environ.get('TELEGRAM_CHANNEL_ID')
    masto_token   = os.environ.get('MASTODON_ACCESS_TOKEN')

    platforms    = []
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
        print("✅ Gemini — ready (long-form summaries + unique reply generation)")
    else:
        print("⚠️  Gemini key missing — using fallback summaries and reply pool")

    if not platforms:
        print("❌ No platforms configured. Exiting.")
        return

    print(f"\n📰 Fetching RSS feeds…\n")
    entries = fetch_news()
    print(f"\n📊 Total entries fetched: {len(entries)}")

    posted      = load_json(POSTED_FILE)
    new_entries = [e for e in entries if e['id'] not in posted]
    print(f"✨ Unposted: {len(new_entries)}\n")

    if not new_entries:
        print("ℹ️  Nothing new to post.")
        if bsky_session:
            cats = list(RSS_FEEDS.keys())
            run_engagement(bsky_session, random.sample(cats, min(4, len(cats))))
        return

    random.shuffle(new_entries)
    to_post = new_entries[:random.randint(MIN_POSTS, MAX_POSTS)]
    categories_posted = list({e['category'] for e in to_post})

    print(f"🎯 Posting {len(to_post)} item(s) this hour\n{'─'*70}")

    for i, entry in enumerate(to_post, 1):
        title    = clean_title(entry['title'])
        link     = entry['link']
        category = entry['category']

        print(f"\n[{i}/{len(to_post)}] {title[:65]}…")
        print(f"   📂 {category}  |  🔗 {link[:55]}…")

        # 1. Fetch article body
        rss_body = get_rss_summary(entry)
        if len(rss_body) < 200:
            print(f"   🌐 Scraping for more content…")
            scraped  = scrape_article_body(link)
            body_text = scraped if len(scraped) > len(rss_body) else rss_body
        else:
            body_text = rss_body
        print(f"   📄 Body: {len(body_text)} chars")

        # 2. Summarize (longer, engagement-optimized)
        summary = None
        if body_text:
            print(f"   🧠 Generating rich summary…")
            summary = gemini_summarize(title, body_text, category)
            if summary:
                print(f"   ✍  Summary ({len(summary)} chars): {summary[:90]}…")
            else:
                # Fallback: longer sentence-aware trim
                cut = body_text[:450]
                last = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'))
                summary = cut[:last+1] if last > 80 else cut + "…"
                print(f"   ✍  Fallback summary used ({len(summary)} chars)")

        # 3. Image
        image_bytes = None
        image_url   = entry.get('image_url') or fetch_og_image(link)
        if image_url:
            image_bytes = download_image(image_url)
            if image_bytes:
                print(f"   🖼️  Image: {len(image_bytes)//1024}KB")

        # 4. Post to platforms
        successes = []

        if 'bluesky' in platforms:
            post_text = build_post_text(entry, summary)
            blob      = bsky_upload_blob(image_bytes, bsky_session) if image_bytes else None
            record    = build_bluesky_record(post_text, link, blob)
            uri, cid  = bsky_post(record, bsky_session)
            if uri:
                successes.append('Bluesky')

        if 'telegram' in platforms:
            tg_text = format_telegram(entry, summary)
            if post_to_telegram(tg_text, tg_token, tg_channel, image_bytes):
                successes.append('Telegram')

        if 'mastodon' in platforms:
            masto_text = format_mastodon(entry, summary)
            if post_to_mastodon(masto_text, masto_token, image_bytes=image_bytes):
                successes.append('Mastodon')

        # 5. Save
        if successes:
            posted.append(entry['id'])
            save_json(POSTED_FILE, posted[-MAX_HISTORY:])
            print(f"   ✅ Posted → {', '.join(successes)}")
        else:
            print(f"   ❌ All platforms failed for this item")

        if i < len(to_post):
            wait = random.randint(15, 25)
            print(f"   ⏳ {wait}s before next post…")
            time.sleep(wait)

    # 6. Engagement
    if bsky_session:
        run_engagement(bsky_session, categories_posted)

    print(f"\n{'='*70}")
    print(f"✅ Run complete — {len(to_post)} post(s) published")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
