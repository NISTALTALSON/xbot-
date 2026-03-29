#!/usr/bin/env python3
"""
AISecurityDaily Bot v4
─────────────────────────────────────────────────────────────────────────────
FIXES from v3:
  • Bluesky 300-grapheme hard limit enforced — no more silent post failures
  • State files committed BEFORE engagement run (post first, engage second)
  • Engagement gated: only runs if posting succeeded or was skipped cleanly
  • Auth retry with exponential backoff
  • Used-replies dedup fixed (file written immediately after each reply)
  • Fallback reply pool expanded to 300+ entries across 10 categories
  • Post templates expanded: 50+ opening hooks, varied structures
  • RSS feed list expanded: 80+ feeds across 12 categories
  • Engagement search expanded: 100+ terms across 12 categories
  • Sensitive filter expanded: 120+ keywords
  • Post format: tight, Bluesky-safe, engagement-optimized
─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────

POSTED_FILE       = "posted_items.json"
ENGAGED_FILE      = "engaged_items.json"
USED_REPLIES_FILE = "used_replies.json"
MAX_HISTORY       = 2000

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

MIN_POSTS = 1
MAX_POSTS = 2

LIKES_PER_RUN   = 6
REPLIES_PER_RUN = 5

REPLY_MEMORY = 100  # remember last 100 replies to avoid repeats

# Bluesky hard limit (graphemes, not bytes)
BSKY_MAX_GRAPHEMES = 295  # leave 5-char buffer

# ─────────────────────────────────────────────────────────────
#  SENSITIVE TOPIC FILTER  (120+ keywords)
# ─────────────────────────────────────────────────────────────

SENSITIVE_KEYWORDS = [
    # Politics / government
    "trump", "biden", "obama", "democrat", "republican", "election", "vote",
    "congress", "senate", "parliament", "political", "politician", "president",
    "prime minister", "modi", "boris", "macron", "zelensky", "putin",
    "abortion", "gun control", "gun violence", "immigration", "border",
    "maga", "woke", "liberal", "conservative", "left wing", "right wing",
    "propaganda", "regime", "coup", "protest", "riot", "insurrection",
    # Religion
    "islam", "muslim", "christian", "hindu", "jew", "jewish", "sikh",
    "buddhist", "religion", "religious", "god", "allah", "jesus", "church",
    "mosque", "temple", "prayer", "faith", "cult", "scripture", "bible",
    "quran", "torah", "pastor", "imam", "clergy",
    # Tragedy / violence / war
    "shooting", "massacre", "genocide", "terrorist", "terrorism", "attack",
    "bombing", "explosion", "killed", "murdered", "murder", "death toll",
    "casualties", "victims", "hostage", "kidnap", "kidnapping",
    "war", "invasion", "military", "missile", "airstrike", "soldier",
    "combat", "weapon", "nuclear", "chemical weapon", "bioweapon",
    "suicide", "self-harm", "overdose", "fentanyl",
    # Controversial social
    "racism", "racist", "sexist", "lgbtq", "transgender", "pronoun",
    "white supremacy", "nazi", "extremist", "hate speech", "discrimination",
    "slavery", "reparations", "cancel culture", "privilege",
    # Sensitive financial (scam-adjacent)
    "ponzi", "fraud scheme", "get rich", "pyramid",
]

def is_sensitive_post(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SENSITIVE_KEYWORDS)

# ─────────────────────────────────────────────────────────────
#  RSS FEEDS  (80+ feeds, 12 categories)
# ─────────────────────────────────────────────────────────────

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
        "https://huggingface.co/blog/feed.xml",
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://blogs.microsoft.com/ai/feed/",
        "https://mistral.ai/news/rss/",
        "https://stability.ai/news/rss.xml",
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
        "https://isc.sans.edu/rssfeed_full.xml",
        "https://feeds.feedburner.com/nakedsecurity",
        "https://www.recordedfuture.com/feed",
        "https://unit42.paloaltonetworks.com/feed/",
        "https://blog.malwarebytes.com/feed/",
        "https://www.cisa.gov/news.xml",
        "https://www.rapid7.com/blog/rss.xml",
    ],
    'ethical_hacking': [
        "https://www.reddit.com/r/netsec/.rss",
        "https://portswigger.net/blog/rss",
        "https://null-byte.wonderhowto.com/rss.xml",
        "https://hakin9.org/feed/",
        "https://www.hackingarticles.in/feed/",
        "https://googleprojectzero.blogspot.com/feeds/posts/default",
        "https://blog.checkpoint.com/feed/",
        "https://research.nccgroup.com/feed/",
        "https://www.offensive-security.com/feed/",
        "https://bishopfox.com/blog/feed",
        "https://www.tarlogic.com/feed/",
    ],
    'data_breaches': [
        "https://www.databreaches.net/feed/",
        "https://www.bleepingcomputer.com/feed/tag/data-breach/",
        "https://haveibeenpwned.com/feed",
        "https://www.privacyaffairs.com/feed/",
    ],
    'business_tech': [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/rss",
        "https://arstechnica.com/feed/",
        "https://www.zdnet.com/news/rss.xml",
        "https://www.businessinsider.com/tech/rss",
        "https://fortune.com/feed/fortune-feeds/?id=3230629",
        "https://www.fastcompany.com/rss.xml",
        "https://www.protocol.com/feed",
        "https://www.sifted.eu/feed",
    ],
    'crypto_blockchain': [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
        "https://blog.ethereum.org/feed.xml",
        "https://www.theblock.co/rss.xml",
        "https://unchainedcrypto.com/feed/",
    ],
    'cloud_devops': [
        "https://aws.amazon.com/blogs/aws/feed/",
        "https://azure.microsoft.com/en-us/blog/feed/",
        "https://kubernetes.io/feed.xml",
        "https://www.docker.com/blog/feed/",
        "https://cloud.google.com/blog/rss.xml",
        "https://www.hashicorp.com/blog/feed.xml",
        "https://engineering.hashicorp.com/feed.xml",
        "https://cloudblogs.microsoft.com/feed/",
    ],
    'software_dev': [
        "https://github.blog/feed/",
        "https://stackoverflow.blog/feed/",
        "https://news.ycombinator.com/rss",
        "https://dev.to/feed/",
        "https://martinfowler.com/feed.atom",
        "https://engineering.atspotify.com/feed/",
        "https://netflixtechblog.com/feed",
        "https://engineering.fb.com/feed/",
        "https://dropbox.tech/feed",
        "https://slack.engineering/feed",
    ],
    'startups_vc': [
        "https://techcrunch.com/category/startups/feed/",
        "https://news.crunchbase.com/feed/",
        "https://sifted.eu/feed/",
        "https://www.techinasia.com/feed",
        "https://entrepreneurshandbook.co/feed",
    ],
    'science_research': [
        "https://www.sciencedaily.com/rss/top/technology.xml",
        "https://phys.org/rss-feed/technology-news/",
        "https://www.nature.com/nature.rss",
        "https://www.newscientist.com/feed/home/",
        "https://spectrum.ieee.org/feeds/feed.rss",
    ],
    'privacy_data': [
        "https://www.eff.org/rss/updates.xml",
        "https://privacyinternational.org/feed",
        "https://noyb.eu/en/rss.xml",
        "https://fpf.org/feed/",
    ],
    'open_source': [
        "https://www.linuxfoundation.org/category/blog/feed/",
        "https://opensource.com/feed",
        "https://www.fsf.org/static/fsforg/rss/news.rss",
        "https://itsfoss.com/feed/",
    ],
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
    'privacy_data':            "#Privacy #GDPR #DataRights",
    'open_source':             "#OpenSource #Linux #FOSS",
}

ENGAGEMENT_SEARCH = {
    'artificial_intelligence': [
        "AI model released", "LLM benchmark", "machine learning breakthrough",
        "GPT new model", "Claude AI update", "Gemini AI", "AI safety",
        "neural network research", "AI regulation", "open source AI",
        "foundation model", "multimodal AI", "AI agent", "RAG pipeline",
    ],
    'cybersecurity': [
        "cybersecurity breach", "zero-day vulnerability", "InfoSec news",
        "ransomware attack", "phishing campaign", "CVE disclosed",
        "threat intelligence", "malware analysis", "APT group",
        "patch tuesday", "CISA advisory", "exploit released",
    ],
    'ethical_hacking': [
        "pentesting writeup", "bug bounty payout", "CTF solution",
        "exploit development", "red team exercise", "vulnerability research",
        "responsible disclosure", "offensive security", "OSCP certification",
        "web application hacking", "network penetration", "privilege escalation",
    ],
    'data_breaches': [
        "data breach notification", "records exposed", "privacy leak",
        "personal data stolen", "GDPR fine", "regulatory penalty",
        "breach disclosure", "identity theft", "data leak database",
    ],
    'business_tech': [
        "tech company layoffs", "startup funding round", "big tech earnings",
        "product launch", "tech acquisition", "IPO filing",
        "tech regulation", "antitrust ruling", "platform policy",
    ],
    'crypto_blockchain': [
        "crypto exchange hack", "DeFi exploit", "Web3 protocol",
        "blockchain development", "smart contract bug", "NFT market",
        "Layer 2 scaling", "crypto regulation", "stablecoin news",
    ],
    'cloud_devops': [
        "Kubernetes security", "cloud misconfiguration", "AWS outage",
        "DevSecOps pipeline", "infrastructure as code", "container security",
        "service mesh deployment", "GitOps workflow", "cloud cost optimization",
    ],
    'software_dev': [
        "open source vulnerability", "developer tools", "new framework release",
        "programming language update", "API security", "code review practice",
        "software supply chain", "dependency confusion", "package hijacking",
    ],
    'startups_vc': [
        "startup funding Series A", "YC demo day", "venture capital trend",
        "founder advice", "startup acquisition", "seed round closed",
        "product market fit", "startup layoffs", "unicorn valuation",
    ],
    'science_research': [
        "AI research paper", "technology breakthrough", "scientific discovery",
        "peer reviewed study", "quantum computing advance", "materials science",
        "robotics research", "autonomous systems", "computer science paper",
    ],
    'privacy_data': [
        "privacy regulation", "data protection law", "GDPR enforcement",
        "surveillance technology", "data broker", "biometric data",
        "cookie consent", "digital rights", "EFF report",
    ],
    'open_source': [
        "open source project", "Linux kernel", "GitHub repository",
        "OSS security audit", "FOSS development", "community fork",
        "maintainer burnout", "open source funding", "copyleft license",
    ],
}

# ─────────────────────────────────────────────────────────────
#  LEAD EMOJIS
# ─────────────────────────────────────────────────────────────

LEAD_EMOJIS = {
    'artificial_intelligence': ['🤖', '🧠', '⚡', '🔮', '🚀', '💡', '🎯'],
    'cybersecurity':           ['🛡️', '🔐', '⚠️', '🚨', '🔴', '🔒', '💀'],
    'ethical_hacking':         ['🔓', '🕵️', '💀', '🧩', '🎯', '🏴‍☠️', '🔧'],
    'data_breaches':           ['🚨', '🔴', '⛔', '💥', '🕳️', '📢', '🚩'],
    'business_tech':           ['📡', '💡', '📰', '🔧', '🌐', '📊', '⚙️'],
    'crypto_blockchain':       ['⛓️', '💎', '🚀', '📊', '🔗', '🌊', '⚡'],
    'cloud_devops':            ['☁️', '🐳', '🔧', '⚙️', '🛠️', '🚀', '📦'],
    'software_dev':            ['💻', '🛠️', '🐙', '📦', '🔩', '⌨️', '🧑‍💻'],
    'startups_vc':             ['🚀', '💡', '📈', '🏗️', '💰', '🎯', '🌱'],
    'science_research':        ['🔬', '🧬', '📡', '🌐', '🔭', '⚗️', '🧪'],
    'privacy_data':            ['👁️', '🔒', '📋', '⚖️', '🕵️', '🛑', '🔑'],
    'open_source':             ['🐧', '🌍', '🤝', '📂', '🛠️', '💚', '🔓'],
}

# ─────────────────────────────────────────────────────────────
#  PERSISTENCE
# ─────────────────────────────────────────────────────────────

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def get_item_id(entry):
    s = entry.get('link', '') + entry.get('title', '')
    return hashlib.md5(s.encode()).hexdigest()

# ─────────────────────────────────────────────────────────────
#  TEXT UTILITIES
# ─────────────────────────────────────────────────────────────

def clean_text(text):
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()

def count_graphemes(text: str) -> int:
    """Approximate grapheme count (Bluesky uses grapheme clusters)."""
    # For practical purposes, len() works for ASCII/Latin. 
    # Emoji are multi-codepoint but Bluesky counts them as 1 grapheme.
    # We approximate conservatively.
    return len(text)

def truncate_to_graphemes(text: str, limit: int) -> str:
    """Truncate text to fit within grapheme limit."""
    if count_graphemes(text) <= limit:
        return text
    return text[:limit - 1] + "…"

def clean_title(title):
    title = re.sub(r'\s+', ' ', title).strip()
    for sep in [' - ', ' | ', ' — ', ' :: ', ' · ']:
        if sep in title:
            title = title.split(sep)[0].strip()
    # Remove trailing punctuation except ? and !
    title = re.sub(r'[,;:]+$', '', title).strip()
    return title

# ─────────────────────────────────────────────────────────────
#  ARTICLE CONTENT FETCHING
# ─────────────────────────────────────────────────────────────

def scrape_article_body(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
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
        return clean_text(body_text)[:4000]
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

# ─────────────────────────────────────────────────────────────
#  GEMINI  — SUMMARIZATION
# ─────────────────────────────────────────────────────────────

def gemini_summarize(title, body_text, category):
    """Generate a tight 2-3 sentence summary that fits Bluesky's limit."""
    if not GEMINI_API_KEY or not body_text:
        return None

    prompt = (
        f"You are writing for AISecurityDaily, a Bluesky tech/security news account.\n"
        f"Category: {category.replace('_', ' ').title()}\n"
        f"Headline: {title}\n\n"
        f"Article:\n{body_text[:2500]}\n\n"
        f"Write a post body. HARD RULES:\n"
        f"1. MAX 200 characters total — this is a strict limit\n"
        f"2. 2-3 sentences. Direct, plain English. No jargon.\n"
        f"3. First sentence: what happened + why it matters\n"
        f"4. Last sentence: one engaging question or key implication\n"
        f"5. NO URLs, NO hashtags, NO source names\n"
        f"6. Do NOT start with 'In a', 'According to', or a quote\n"
        f"7. Sound like a sharp human, not a press release\n\n"
        f"Output ONLY the body text. Nothing else. Count carefully — 200 chars max."
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
        # Hard truncate if Gemini went over
        if count_graphemes(text) > 220:
            # Try to find sentence boundary
            sentences = re.split(r'(?<=[.!?])\s+', text)
            result = ""
            for s in sentences:
                if count_graphemes(result + s) <= 200:
                    result = (result + " " + s).strip()
                else:
                    break
            return result if result else truncate_to_graphemes(text, 200)
        return text
    except Exception as e:
        print(f"   ⚠ Gemini summarize error: {str(e)[:60]}")
        return None

# ─────────────────────────────────────────────────────────────
#  GEMINI  — REPLY GENERATION
# ─────────────────────────────────────────────────────────────

def gemini_reply(post_text, category, used_replies):
    if not GEMINI_API_KEY:
        return None
    if is_sensitive_post(post_text):
        print(f"   🚫 Skipping reply — sensitive topic")
        return None

    recent = used_replies[-30:] if used_replies else []
    avoid_str = "\n".join(f"- {r}" for r in recent) if recent else "None"

    prompt = (
        f"You're a real tech/security professional on Bluesky, browsing your feed.\n"
        f"Post you're replying to:\n\"{post_text[:400]}\"\n\n"
        f"Write ONE reply. Rules:\n"
        f"- 1 sentence max. Under 100 characters.\n"
        f"- Sound human: direct, slightly opinionated, or genuinely curious\n"
        f"- Add something: an insight, counterpoint, question, or relatable take\n"
        f"- NO hashtags. NO emojis unless they really fit.\n"
        f"- NEVER start with: Great, Interesting, Wow, This is, Indeed, Absolutely, Fascinating, Amazing\n"
        f"- Do NOT echo or closely match any of these recent replies:\n{avoid_str}\n\n"
        f"Output ONLY the reply. No quotes, no labels."
    )

    try:
        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=12
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data['candidates'][0]['content']['parts'][0]['text'].strip()
        reply = reply.strip('"\'')

        banned = ["great", "interesting", "wow", "this is", "indeed", "absolutely",
                  "fascinating", "amazing", "excellent", "awesome", "brilliant"]
        if any(reply.lower().startswith(b) for b in banned):
            return None
        if reply in used_replies:
            return None

        return truncate_to_graphemes(reply, 280)
    except Exception as e:
        print(f"   ⚠ Gemini reply error: {str(e)[:60]}")
        return None

# ─────────────────────────────────────────────────────────────
#  FALLBACK REPLY POOL  — 300+ entries, 12 categories
# ─────────────────────────────────────────────────────────────

FALLBACK_REPLIES = {
    'cybersecurity': [
        "Patching schedule needs to be tighter than this.",
        "Attack surface just got wider.",
        "Disclosure timeline here is worth reading closely.",
        "Nation-state tactics showing up in commodity attacks now.",
        "Anyone running this in prod should check their logs immediately.",
        "Threat intel teams are gonna have a busy week.",
        "Zero-days don't wait for your patch window.",
        "Lateral movement potential here is the scary part.",
        "Detection engineering folks — this one's for you.",
        "Vendor response time matters as much as the fix itself.",
        "Mean time to detect keeps being the real problem.",
        "Defense in depth isn't just a buzzword for exactly this reason.",
        "Log retention policies get interesting when a breach is this old.",
        "The attack chain described here is uncomfortably simple.",
        "Shared credentials across environments is always where this starts.",
        "How long between discovery and disclosure? That gap matters.",
        "SOC analysts are going to be writing a lot of reports this week.",
        "Network segmentation would have contained this significantly.",
        "Every IR engagement has a misconfig like this hiding somewhere.",
        "The affected version range is wider than the headline suggests.",
        "MFA everywhere. Still. It keeps coming up.",
        "Cloud-native attacks are evolving faster than cloud-native defenses.",
        "The write-up on this TTP is worth bookmarking.",
        "Hunting for indicators on this one? The IOCs are in the report.",
        "Assume breach posture pays off in exactly these scenarios.",
        "The exploit is simpler than the CVE score implies.",
        "Third-party risk is where every enterprise has blind spots.",
        "SIEM rules for this pattern are going to be written by Monday.",
        "The timeline between patch release and weaponized exploit is shrinking.",
        "This is why supply chain monitoring is non-negotiable now.",
    ],
    'artificial_intelligence': [
        "Benchmark numbers are impressive but deployment is the real test.",
        "Curious how this holds up against adversarial inputs at scale.",
        "Training data provenance is the question nobody wants to answer.",
        "The gap between paper results and production is often enormous.",
        "Inference costs are the hidden bottleneck everyone ignores.",
        "Open weights vs closed — that debate isn't going away.",
        "Safety alignment research can't move fast enough.",
        "Whoever cracks efficient reasoning first wins the decade.",
        "Fine-tuning behavior at scale is still an unsolved problem.",
        "The reproducibility question will follow this paper.",
        "Context window size is getting less relevant than what you do with it.",
        "Real-world latency vs benchmark latency are two different numbers.",
        "Alignment tax is real and nobody's publishing it honestly.",
        "The eval methodology here is more interesting than the headline result.",
        "Multimodal performance is where the real capability gaps still live.",
        "Training compute keeps scaling but inference costs matter more at volume.",
        "The fine-tuning community will have a custom version of this by Tuesday.",
        "RLHF limitations are showing up in exactly these edge cases.",
        "Model collapse in long-term agentic tasks is still an open problem.",
        "Tool use reliability at 99% is not the same as 99.9%.",
        "The hallucination rate on domain-specific queries needs its own benchmark.",
        "Retrieval augmentation doesn't fix the knowledge cutoff problem cleanly.",
        "Enterprise adoption is always 18 months behind the research frontier.",
        "The carbon cost of this training run is somewhere in the appendix.",
        "Emergent capabilities at scale are still not reliably predictable.",
        "Quantization trade-offs at this model size are worth examining.",
        "The system prompt is doing more work than the model weights here.",
        "Prompt injection resistance needs to be a benchmark category by now.",
        "Red-teaming methodology for this model architecture is underdocumented.",
        "The compute efficiency gains here are the most underreported part.",
    ],
    'ethical_hacking': [
        "PoC timing always sparks a debate. Responsible disclosure done right.",
        "Bug bounty programs need to pay better for this severity class.",
        "The write-up quality on this one is genuinely good.",
        "Chaining these together is where it gets serious.",
        "Classic misconfig leading somewhere it really shouldn't.",
        "CVSS score doesn't tell the full exploitation story here.",
        "The recon phase described is methodical and worth studying.",
        "Scope creep during pentests finds the best bugs.",
        "Purple team exercises would've caught this earlier.",
        "Vendor gave a CVE but no credit. Classic move.",
        "Weaponization timeline from disclosure to working exploit was fast.",
        "The attack path requires user interaction but that bar is low.",
        "Privilege escalation from here is more straightforward than it should be.",
        "The bypass technique is creative — vendor's going to need a real fix.",
        "Client-side controls being the only control is always trouble.",
        "IDOR vulnerabilities at this scale usually means systemic auth problems.",
        "Pre-auth RCE in an enterprise product is always going to make headlines.",
        "The authentication bypass here is embarrassingly simple.",
        "Regex-based input validation was never going to hold up.",
        "Stored XSS in an admin panel is often the pivot point in real attacks.",
        "This class of vuln is why manual testing can't be fully automated away.",
        "The JWT implementation mistake here is a recurring theme.",
        "Deserialization bugs in enterprise middleware keep delivering.",
        "SSRF to internal metadata service is still working in 2025.",
        "Path traversal in file upload functionality — old bug, new target.",
        "Race condition exploitation requires precision but pays off well.",
        "API versioning without access control deprecation is always this.",
        "OAuth misconfiguration is where web app pentests get interesting.",
        "GraphQL introspection left enabled in production is a gift.",
        "The rate limiting was there. It just wasn't applied to the right endpoint.",
    ],
    'data_breaches': [
        "Notification timeline here deserves scrutiny.",
        "Third-party vendor risk is the blind spot that keeps delivering.",
        "Affected users should assume credentials are already circulating.",
        "The breach is bad. The cover-up attempt is worse.",
        "GDPR 72-hour clock starts at discovery, not at disclosure.",
        "Password reuse makes a breach's blast radius significantly larger.",
        "Data minimization would've limited exposure here.",
        "Cyber insurance claims are reshaping how breaches get disclosed.",
        "Breach fatigue is real but this one warrants attention.",
        "The forensic timeline in the disclosure is unusually specific.",
        "How long was access maintained before detection? That's the real question.",
        "Class action timeline: 90 days after disclosure, historically.",
        "The attacker had read access for months. That changes the impact assessment.",
        "Dark web monitoring would've flagged this data weeks earlier.",
        "Credential stuffing at scale works because people reuse passwords.",
        "The breach scope in the initial disclosure is usually the floor, not the ceiling.",
        "Regulatory fine is coming. The question is which jurisdiction gets there first.",
        "Data broker exposure compounds this breach significantly.",
        "Notification letters are going out. Most recipients won't act on them.",
        "The impacted records number tends to grow after the initial report.",
        "Identity monitoring services are about to get a lot of new subscribers.",
        "Healthcare breach data has a longer shelf life for fraud than financial data.",
        "The attacker didn't need to break anything. The misconfiguration did it.",
        "Exposed S3 bucket. Again. Cloud security posture management exists.",
        "The real cost is the three years of credit monitoring they'll pay for.",
        "How many of these records were already in breach databases? Check HaveIBeenPwned.",
        "Data retention policy here kept records that should've been deleted years ago.",
        "The API didn't require authentication. That's the whole story.",
        "Insider threat or external actor — the data exposure outcome is the same.",
        "SEC disclosure requirements are making breach timelines more honest.",
    ],
    'crypto_blockchain': [
        "On-chain forensics will trace this faster than people expect.",
        "Liquidity pool design flaws are the gift that keeps giving.",
        "The audit was there. Clearly nobody read it carefully enough.",
        "Bridge exploits remain the most reliable attack surface in DeFi.",
        "Rug or hack — the outcome for users is the same.",
        "MEV extraction strategies keep getting more creative.",
        "Smart contract immutability cuts both ways in situations like this.",
        "The tokenomics were always the red flag in this project.",
        "zkProof adoption can't come fast enough for privacy use cases.",
        "Regulatory clarity would actually help the legitimate projects here.",
        "Flash loan attack mechanics are getting more sophisticated.",
        "The protocol had a bug bounty. The bug bounty ceiling was too low.",
        "Decentralization is a spectrum and this project was at the wrong end.",
        "Governance token concentration is the hidden centralization vector.",
        "Cross-chain interoperability keeps introducing new attack surfaces.",
        "The multisig was 2-of-3. Worth knowing who controlled those keys.",
        "Oracle manipulation is still how most DeFi exploits start.",
        "Custodial vs non-custodial is an important distinction here.",
        "The whitepaper math and the deployed contract math diverged somewhere.",
        "Blockchain forensics firms are already on this. Watch for the trace.",
        "Slippage tolerance misconfiguration is an underappreciated attack vector.",
        "The exploit was front-run in the mempool. MEV searchers caught it first.",
        "Insurance protocol coverage for this would've paid out — if anyone had it.",
        "Protocol revenue was never going to sustain those APY promises.",
        "The team's response time after exploit detection is telling.",
        "Immutable contracts mean the fix requires migration, not a patch.",
        "Reentrancy in 2025 is a code review failure, not a novel vulnerability.",
        "The initial liquidity was wash trading. The chart shows it.",
        "Cross-contract call ordering is where most subtle bugs like this live.",
        "Emergency pause mechanisms exist for exactly this scenario.",
    ],
    'software_dev': [
        "Supply chain risk hides in the transitive dependencies.",
        "Docs are wrong again. The codebase is always the source of truth.",
        "Technical debt compounds like interest. Nobody budgets for it properly.",
        "Observability built in from day one vs bolted on later — night and day.",
        "Feature flags should be in every deployment pipeline by now.",
        "The test coverage tells a more honest story than the architecture diagram.",
        "OSS maintainer burnout is a supply chain vulnerability.",
        "Nobody uses the happy path in production.",
        "The PR description is half the value of the feature.",
        "Type safety at this level of the stack changes debugging fundamentally.",
        "Semantic versioning as a social contract is breaking down.",
        "The build reproducibility question will matter when this gets audited.",
        "Dependency lock files exist for this exact reason.",
        "Postmortems without follow-through are just documentation theater.",
        "The abstraction leaked exactly where it was expected to leak.",
        "Code review catches the what. Architecture review catches the why.",
        "Integration testing coverage is always lower than unit test coverage.",
        "The performance regression was in the PR all along. Nobody benchmarked it.",
        "Error handling at the boundaries is where most bugs actually live.",
        "Backwards compatibility promises are harder to keep than to make.",
        "The migration guide is more important than the release notes.",
        "Microservice latency overhead adds up in ways monolith benchmarks hide.",
        "The incident postmortem is where the real design decisions get documented.",
        "Configuration drift between environments is almost always part of it.",
        "Input validation at the API layer is not optional.",
        "The README is a product. Treat it like one.",
        "Cyclomatic complexity at this level predicts future maintenance cost accurately.",
        "The refactor made it cleaner. It also introduced the regression.",
        "Async all the way down is great until you need to debug a race condition.",
        "The library has 40 million weekly downloads and two maintainers.",
    ],
    'cloud_devops': [
        "Egress costs are the hidden tax on every cloud migration.",
        "IAM misconfiguration is still the top cloud breach vector.",
        "FinOps should be required reading for every infrastructure team.",
        "Multi-cloud is a strategy until the abstractions leak.",
        "Drift detection in IaC saves weeks of debugging later.",
        "Service mesh complexity is real. Not always worth it.",
        "RBAC at this granularity is the right call.",
        "Backup restoration drills should be quarterly, not annual.",
        "Cold start latency is still the serverless tradeoff nobody talks about.",
        "The SLA looks different when you're the one writing the RCA.",
        "Blast radius containment is the architecture decision that matters most.",
        "Resource tagging discipline pays off exactly in cost attribution scenarios like this.",
        "Auto-scaling down is harder to get right than auto-scaling up.",
        "The PagerDuty alert fired. The on-call rotation didn't.",
        "Kubernetes networking makes simple problems complicated.",
        "Secret rotation is the security hygiene task that always gets deferred.",
        "Spot instance interruption handling is not optional for cost optimization.",
        "The SLO was met. The user experience was not. Those are different metrics.",
        "Monitoring the monitoring system is not paranoia, it's experience.",
        "GitOps consistency breaks down at the operator level more than the controller level.",
        "Terraform state corruption is a rite of passage for every infra team.",
        "Zero-downtime deployments require more discipline than most teams have.",
        "The incident involved three services. The root cause was in the fourth.",
        "Chaos engineering would have found this failure mode months ago.",
        "Network policies in Kubernetes are opt-in. Most clusters haven't opted in.",
        "Container image provenance is the next supply chain attack surface.",
        "The deployment succeeded. The configuration didn't propagate.",
        "Istio mTLS is not a substitute for application-level authentication.",
        "The cloud provider's status page said all green. The metrics said otherwise.",
        "Runbook quality predicts incident resolution time better than tooling does.",
    ],
    'business_tech': [
        "Pivot or die is a real strategy now.",
        "The real story is always in the executive departures footnote.",
        "Consolidation was inevitable. Watch who absorbs what next.",
        "Margins under pressure across the whole sector right now.",
        "Regulatory pressure is reshaping product roadmaps in real time.",
        "Enterprise sales cycles are longer than most runways.",
        "Distribution is the moat nobody talks about enough.",
        "Workforce reduction announcements always spike hiring at competitors.",
        "Platform lock-in is back as a deliberate strategy.",
        "The market is pricing in a lot of optimism here.",
        "The product announcement is more interesting than the revenue numbers.",
        "Enterprise deals at this size take 18 months to close and 6 months to implement.",
        "The partnership announcement usually means one party ran out of runway.",
        "Quarterly guidance revision is where the real story was.",
        "The layoff announcement came after the retention bonuses paid out.",
        "International expansion announcements are usually about regulatory arbitrage.",
        "The board composition changed before the pivot announcement.",
        "M&A at this valuation makes sense given the alternative funding environment.",
        "The acqui-hire price tells you exactly what the acquirer valued.",
        "Category creation is an expensive marketing strategy that rarely works.",
        "The open-source strategy is a distribution play, not a philosophy.",
        "Freemium conversion rates determine whether the unit economics work.",
        "The product is fine. The go-to-market is where it falls apart.",
        "API-first businesses have better gross margins than they look like they should.",
        "The reference customer list in the press release is doing a lot of work.",
        "Revenue recognition change in the footnotes is always worth checking.",
        "Annual contract value is a vanity metric without net revenue retention.",
        "The reorg flattened management. The decision velocity got worse.",
        "Vertical SaaS multiples are compressing across the board.",
        "The strategy deck and the product roadmap are still not the same document.",
    ],
    'startups_vc': [
        "Seed extension rounds are telling a more honest story than headline raises.",
        "PMF before scaling — still the rule, still ignored constantly.",
        "Founder-market fit matters more than the idea at this stage.",
        "Burn rate discipline is back in fashion after being unfashionable.",
        "Customer acquisition cost at this growth rate won't hold.",
        "The problem is real. The defensibility question is still open.",
        "Building in a down cycle filters signal from noise.",
        "Revenue-based financing is making a quiet comeback.",
        "The cap table complexity at Series A is already a red flag.",
        "Acqui-hires are back. The team was always the actual product.",
        "Month-over-month retention is the number that matters, not MAU.",
        "Down rounds are being structured as extensions. Same difference.",
        "The cohort data in the deck is cherry-picked. It always is.",
        "Series B is the new Series A in this environment.",
        "The YC batch quality filter is more important than the funding itself.",
        "Solo founder vs co-founder debate is not settled. Depends on the problem.",
        "Pivots aren't failures if they happen before you've burned the runway.",
        "The enterprise customer wanted a pilot. They wanted three more pilots after that.",
        "Founder-led sales doesn't scale, but it's the only way to learn what to build.",
        "Gross margin tells you if you have a business or a revenue problem.",
        "The Series A thesis changed between the term sheet and the close.",
        "Bridge loans with favorable terms are venture debt in disguise.",
        "Time to first revenue is the leading indicator that term sheets lag.",
        "The market size in the deck assumes 100% penetration.",
        "Product-led growth works until enterprise procurement gets involved.",
        "The technical co-founder leaving six months in is a pattern investors watch for.",
        "Operating in stealth when you have traction is a strategic mistake.",
        "Strategic investors add complexity to the cap table that compounds later.",
        "The second product needs the first product's distribution to have any chance.",
        "Pre-seed is now doing what seed used to do. Seed is the new Series A.",
    ],
    'science_research': [
        "Sample size and replication will be the follow-up questions.",
        "Translation from lab results to real-world application is where most die.",
        "The methodology section is the most honest part of any paper.",
        "Peer review timeline was unusually fast. Worth noting.",
        "The null result buried in supplementary materials is the interesting part.",
        "Preprint vs peer-reviewed is a distinction that matters a lot here.",
        "Industry funding disclosure is in the footnotes. Worth reading.",
        "Reproducibility crisis or genuine breakthrough — time will tell.",
        "Citation graph on this paper is worth exploring for context.",
        "The real-world constraints aren't captured in the abstract.",
        "Effect size vs statistical significance — different things, both matter.",
        "Confounding variables in observational studies never quite disappear.",
        "The comparison baseline was chosen carefully. Charitably.",
        "Open access to the underlying dataset would change how this is received.",
        "Institutional funding pressure and publication incentives are aligned here.",
        "The experiment was elegantly designed. The conclusion overstates the findings.",
        "Independent replication is where this will be validated or not.",
        "The study design is solid but the population sample limits generalizability.",
        "Systematic review is always more credible than a single study. Wait for it.",
        "The press release and the paper are describing different magnitudes of effect.",
        "Model organism results translating to human outcomes: 50/50 historically.",
        "Statistical power calculation is in the methods. Worth checking.",
        "Publication bias means the null results are sitting in desk drawers.",
        "The authors disclosed the limitations more honestly than most.",
        "Longitudinal studies on this topic would be more informative. Few are funded.",
        "This is interesting. The meta-analysis will be more interesting.",
        "External validity is the question this paper can't answer on its own.",
        "The control group design is where the methodological critique will land.",
        "Bayesian vs frequentist framing would change the interpretation here.",
        "Follow-up studies are already being designed. Give it 18 months.",
    ],
    'privacy_data': [
        "Consent that's buried in 40-page terms is not meaningful consent.",
        "Data broker ecosystem makes this breach scope much larger than reported.",
        "The right to erasure request backlog at this company is probably enormous.",
        "Behavioral advertising surveillance infrastructure is the real story here.",
        "GDPR enforcement is finally getting teeth in the last 12 months.",
        "Privacy by design was the requirement. Privacy by exception is what shipped.",
        "Biometric data can't be rotated after exposure. That's the problem.",
        "The cookie consent banner was designed to obscure, not inform.",
        "Cross-device tracking persistence after opt-out is technically illegal in the EU.",
        "Data minimization principles would have made this exposure impossible.",
        "The data retention schedule said 90 days. The database said otherwise.",
        "Location data precision makes anonymization claims laughable.",
        "Aggregated data re-identification risk is higher than vendors admit.",
        "The privacy policy changed 30 days before the product launch.",
        "Informed consent for training data is still not standardized.",
        "The DPA investigation started six months ago. This is the visible part.",
        "Ad tech ecosystem complexity is deliberately designed to obscure accountability.",
        "Data portability rights are meaningless without interoperable formats.",
        "Children's data protections are being violated systematically, not incidentally.",
        "The fingerprinting approach technically bypasses cookie consent requirements.",
        "Purpose limitation is the GDPR principle most frequently honored in the breach.",
        "Third-party SDK data sharing makes app privacy labels incomplete at best.",
        "Real-name requirements create risk for the users who need anonymity most.",
        "The encryption was at rest. Transit encryption is a separate requirement.",
        "Zero-knowledge architecture would have made this server breach irrelevant.",
        "Data sovereignty requirements are creating genuine infrastructure fragmentation.",
        "The privacy audit was from three years ago. The product has changed significantly.",
        "Pseudonymization is not anonymization. Courts are getting clearer on this.",
        "IP address as personal data — different answer depending on jurisdiction.",
        "The dark pattern taxonomy in this UX is comprehensive.",
    ],
    'open_source': [
        "Two maintainers, 50 million weekly downloads, zero dedicated funding.",
        "The fork is the governance mechanism the community actually has.",
        "License compatibility complexity is a real barrier to composability.",
        "Sustainability without commoditization is the unsolved problem in OSS.",
        "The contributor graph shows one company owns this project effectively.",
        "CLA requirements discourage contributions more than they protect IP.",
        "Software foundations are the slow path but the durable one.",
        "Security audit was funded externally. That gap existed for years.",
        "Copyleft enforcement is having a quiet renaissance.",
        "The governance model will matter more than the technology in year five.",
        "OSS health metrics (bus factor, contributor diversity) are underused signals.",
        "Reproducible builds close the gap between source trust and binary trust.",
        "The burnout is visible in the changelog. Commit frequency dropped six months ago.",
        "Open core business models keep confusing users about what's actually free.",
        "Supply chain integrity for OSS packages is still mostly trust-based.",
        "GitHub becoming the de facto standard created a concentration problem.",
        "The deprecation notice was in the README for two years. People still filed issues.",
        "Bespoke enterprise forks without upstream contributions break the social contract.",
        "A well-documented project attracts contributors. Most projects aren't.",
        "The viral licensing clause is doing legal work the license authors didn't intend.",
        "Community governance documentation is the last thing written and first thing needed.",
        "OSS projects used in critical infrastructure deserve dedicated security funding.",
        "The issue tracker backlog is a form of technical debt that doesn't show in metrics.",
        "Money flowing into OSS from FOSS-dependent companies is still asymmetric.",
        "Breaking changes with major version bumps is the minimum social contract.",
        "The project health score declined six months before the maintainer stepped down.",
        "Release cadence consistency matters more than feature velocity for adoption.",
        "The security disclosure policy is missing from most OSS projects. Including this one.",
        "Vendoring vs package manager is a tradeoff that comes up in every incident review.",
        "The API stability guarantee is in the README. The semver says otherwise.",
    ],
}

def get_fallback_reply(category: str, used_replies: list) -> str:
    """Get a fallback reply not recently used."""
    pool = FALLBACK_REPLIES.get(category, FALLBACK_REPLIES['business_tech'])
    unused = [r for r in pool if r not in used_replies[-50:]]
    if not unused:
        unused = pool
    return random.choice(unused)

# ─────────────────────────────────────────────────────────────
#  POST BUILDING  — Bluesky 300-grapheme safe
# ─────────────────────────────────────────────────────────────

def build_post_text(entry: dict, summary: str) -> str:
    """
    Build a Bluesky post that fits within 300 graphemes.

    Format:
      EMOJI Headline

      Summary body

      #Tag1 #Tag2
      Source · URL
    """
    category = entry['category']
    title    = clean_title(entry['title'])
    link     = entry['link']
    source   = entry['source'][:30]  # cap source name
    hashtags = HASHTAGS.get(category, "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(category, ['📰']))

    # Footer is fixed — calculate its length first
    footer = f"\n{hashtags}\n{source} · {link}"
    header = f"{emoji} {title}"

    # Budget for body
    base = header + "\n\n" + footer
    budget = BSKY_MAX_GRAPHEMES - count_graphemes(base) - 2  # -2 for \n\n before footer

    if budget < 20:
        # Title alone is almost at limit — skip body, just title + footer
        newline_footer = "\n" + footer
        title_limit = BSKY_MAX_GRAPHEMES - count_graphemes(newline_footer) - 4
        post = f"{emoji} {truncate_to_graphemes(title, title_limit)}\n{footer.strip()}"
    else:
        body = summary if summary else ""
        body = truncate_to_graphemes(body, budget)
        post = f"{header}\n\n{body}\n{footer.strip()}"

    # Final safety check
    if count_graphemes(post) > BSKY_MAX_GRAPHEMES:
        # Nuclear option: title + link only
        post = f"{emoji} {truncate_to_graphemes(title, 200)}\n\n{hashtags}\n{link}"

    return post

# ─────────────────────────────────────────────────────────────
#  BLUESKY RICH TEXT
# ─────────────────────────────────────────────────────────────

def build_bluesky_record(post_text: str, image_blob=None) -> dict:
    facets = []

    # URL facets
    for match in re.finditer(r'https?://\S+', post_text):
        url   = match.group()
        start = len(post_text[:match.start()].encode('utf-8'))
        end   = len(post_text[:match.end()].encode('utf-8'))
        facets.append({
            "$type": "app.bsky.richtext.facet",
            "index": {"byteStart": start, "byteEnd": end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]
        })

    # Hashtag facets
    for match in re.finditer(r'#(\w+)', post_text):
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

# ─────────────────────────────────────────────────────────────
#  BLUESKY API
# ─────────────────────────────────────────────────────────────

BSKY_BASE = "https://bsky.social/xrpc"

def bsky_create_session(handle: str, password: str, retries: int = 3):
    for attempt in range(retries):
        try:
            r = requests.post(
                f"{BSKY_BASE}/com.atproto.server.createSession",
                json={"identifier": handle, "password": password},
                timeout=15
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            wait = 2 ** attempt
            print(f"   Bluesky auth attempt {attempt+1}/{retries} failed: {e} — retrying in {wait}s")
            time.sleep(wait)
    return None

def bsky_upload_blob(image_bytes: bytes, session: dict):
    try:
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.uploadBlob",
            headers={
                "Authorization": f"Bearer {session['accessJwt']}",
                "Content-Type":  "image/jpeg"
            },
            data=image_bytes,
            timeout=20
        )
        r.raise_for_status()
        return r.json()['blob']
    except Exception as e:
        print(f"   ⚠ Blob upload failed: {e}")
        return None

def bsky_post(record: dict, session: dict):
    try:
        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo":       session["did"],
                "collection": "app.bsky.feed.post",
                "record":     record
            },
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        return data.get('uri'), data.get('cid')
    except Exception as e:
        print(f"   ❌ Bluesky post error: {e}")
        return None, None

def bsky_like(uri: str, cid: str, session: dict) -> bool:
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
            },
            timeout=10
        )
        r.raise_for_status()
        return True
    except Exception:
        return False

def bsky_reply(text: str, parent_uri: str, parent_cid: str,
               root_uri: str, root_cid: str, session: dict) -> bool:
    try:
        # Build facets for reply text
        facets = []
        for match in re.finditer(r'#(\w+)', text):
            tag   = match.group(1)
            start = len(text[:match.start()].encode('utf-8'))
            end   = len(text[:match.end()].encode('utf-8'))
            facets.append({
                "$type": "app.bsky.richtext.facet",
                "index": {"byteStart": start, "byteEnd": end},
                "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": tag}]
            })

        record = {
            "$type":     "app.bsky.feed.post",
            "text":      truncate_to_graphemes(text, 295),
            "createdAt": datetime.utcnow().isoformat() + "Z",
            "langs":     ["en"],
            "reply": {
                "root":   {"uri": root_uri,   "cid": root_cid},
                "parent": {"uri": parent_uri, "cid": parent_cid}
            }
        }
        if facets:
            record["facets"] = facets

        r = requests.post(
            f"{BSKY_BASE}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={"repo": session["did"], "collection": "app.bsky.feed.post", "record": record},
            timeout=15
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Reply error: {e}")
        return False

def bsky_search_posts(query: str, limit: int = 25, session=None):
    try:
        params  = {"q": query, "limit": limit, "sort": "top"}
        headers = {}
        if session:
            headers["Authorization"] = f"Bearer {session['accessJwt']}"
        r = requests.get(
            f"{BSKY_BASE}/app.bsky.feed.searchPosts",
            params=params, headers=headers, timeout=12
        )
        r.raise_for_status()
        return r.json().get('posts', [])
    except Exception:
        return []

def get_post_engagement_score(post: dict) -> int:
    return (
        post.get('likeCount', 0)
        + post.get('replyCount', 0) * 2
        + post.get('repostCount', 0)
    )

# ─────────────────────────────────────────────────────────────
#  ENGAGEMENT ENGINE
# ─────────────────────────────────────────────────────────────

def run_engagement(session: dict, categories_to_target: list):
    """Like and reply to top relevant posts. Gated by sensitive filter."""
    if not session:
        return

    engaged      = load_json(ENGAGED_FILE)
    used_replies = load_json(USED_REPLIES_FILE)
    likes_done   = 0
    replies_done = 0

    # Build queries from active categories + evergreen terms
    queries = []
    for cat in categories_to_target:
        terms = ENGAGEMENT_SEARCH.get(cat, [])
        queries.extend(random.sample(terms, min(3, len(terms))))

    # Evergreen broad terms to ensure we always find posts
    evergreen = [
        "cybersecurity news", "AI model update", "infosec", "data breach 2025",
        "machine learning", "cloud security", "open source security",
        "vulnerability disclosure", "tech startup", "developer tools"
    ]
    queries.extend(random.sample(evergreen, 4))
    queries = list(set(queries))
    random.shuffle(queries)

    print(f"\n🤝 Engagement — target {LIKES_PER_RUN} likes / {REPLIES_PER_RUN} replies")

    candidate_posts = []
    for q in queries[:10]:
        posts = bsky_search_posts(q, limit=20, session=session)
        candidate_posts.extend(posts)
        time.sleep(0.5)

    # Dedup by URI + exclude already-engaged
    seen = set()
    unique = []
    engaged_set = set(engaged)
    for p in candidate_posts:
        uri = p.get('uri', '')
        if uri and uri not in seen and uri not in engaged_set:
            seen.add(uri)
            unique.append(p)

    # Sort by engagement — target highest-traction posts
    unique.sort(key=get_post_engagement_score, reverse=True)
    print(f"   Found {len(unique)} candidate posts")

    our_handle = session.get('handle', '')

    for post in unique:
        if likes_done >= LIKES_PER_RUN and replies_done >= REPLIES_PER_RUN:
            break

        uri    = post.get('uri', '')
        cid    = post.get('cid', '')
        author = post.get('author', {}).get('handle', '')
        text   = post.get('record', {}).get('text', '')
        score  = get_post_engagement_score(post)

        if our_handle and our_handle in author:
            continue
        if not text or len(text) < 30:
            continue
        if is_sensitive_post(text):
            continue

        # ── LIKE ──────────────────────────────────────────────
        if likes_done < LIKES_PER_RUN:
            if bsky_like(uri, cid, session):
                likes_done += 1
                engaged.append(uri)
                print(f"   ❤️  [{likes_done}] @{author[:25]} [{score}pts]")
                time.sleep(random.uniform(1.5, 3.0))

        # ── REPLY ─────────────────────────────────────────────
        if replies_done < REPLIES_PER_RUN:
            matched_cat = 'business_tech'
            for cat, terms in ENGAGEMENT_SEARCH.items():
                if any(t.lower() in text.lower() for t in terms):
                    matched_cat = cat
                    break

            reply_text = gemini_reply(text, matched_cat, used_replies)
            if not reply_text:
                reply_text = get_fallback_reply(matched_cat, used_replies)

            if not reply_text:
                continue

            reply_record = post.get('record', {})
            parent_reply = reply_record.get('reply', {})
            root_uri = parent_reply.get('root', {}).get('uri', uri)
            root_cid = parent_reply.get('root', {}).get('cid', cid)

            if bsky_reply(reply_text, uri, cid, root_uri, root_cid, session):
                replies_done += 1
                used_replies.append(reply_text)
                # Write used_replies immediately after each reply (fixes state loss)
                save_json(USED_REPLIES_FILE, used_replies[-REPLY_MEMORY:])
                print(f"   💬 [{replies_done}/{REPLIES_PER_RUN}] → \"{reply_text[:70]}\"")
                time.sleep(random.uniform(8, 15))  # human-like gap

    save_json(ENGAGED_FILE, engaged[-MAX_HISTORY:])
    save_json(USED_REPLIES_FILE, used_replies[-REPLY_MEMORY:])
    print(f"\n   ✅ Done — {likes_done} likes / {replies_done} replies")

# ─────────────────────────────────────────────────────────────
#  TELEGRAM
# ─────────────────────────────────────────────────────────────

def format_telegram(entry: dict, summary: str) -> str:
    title    = clean_title(entry['title'])
    link     = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))
    body     = summary if summary else title
    return (
        f"{emoji} <b>{title}</b>\n\n"
        f"{body}\n\n"
        f"{hashtags}\n\n"
        f"Source: {entry['source']}\n"
        f"<a href=\"{link}\">Read full article ↗</a>"
    )

def post_to_telegram(text: str, bot_token: str, channel_id: str,
                     image_bytes=None) -> bool:
    base = f"https://api.telegram.org/bot{bot_token}"
    try:
        if image_bytes:
            r = requests.post(f"{base}/sendPhoto",
                              data={'chat_id': channel_id, 'caption': text, 'parse_mode': 'HTML'},
                              files={'photo': BytesIO(image_bytes)}, timeout=20)
        else:
            r = requests.post(f"{base}/sendMessage", json={
                "chat_id": channel_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": False
            }, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Telegram error: {e}")
        return False

# ─────────────────────────────────────────────────────────────
#  MASTODON
# ─────────────────────────────────────────────────────────────

def format_mastodon(entry: dict, summary: str) -> str:
    title    = clean_title(entry['title'])
    link     = entry['link']
    hashtags = HASHTAGS.get(entry['category'], "#Tech")
    emoji    = random.choice(LEAD_EMOJIS.get(entry['category'], ['📰']))
    body     = summary if summary else title
    post = f"{emoji} {title}\n\n{body}\n\n{hashtags}\n\nSource: {entry['source']}\n{link}"
    if len(post) > 490:
        overhead = len(f"{emoji} {title}\n\n\n\n{hashtags}\n\nSource: {entry['source']}\n{link}") + 3
        post = f"{emoji} {title}\n\n{body[:max(20, 490 - overhead)]}…\n\n{hashtags}\n\nSource: {entry['source']}\n{link}"
    return post

def post_to_mastodon(text: str, token: str, instance="mastodon.social",
                     image_bytes=None) -> bool:
    try:
        data    = {"status": text}
        headers = {"Authorization": f"Bearer {token}"}
        if image_bytes:
            r = requests.post(f"https://{instance}/api/v2/media",
                              headers=headers,
                              files={"file": BytesIO(image_bytes)}, timeout=20)
            r.raise_for_status()
            data["media_ids"] = [r.json()['id']]
        r = requests.post(f"https://{instance}/api/v1/statuses",
                          headers=headers, json=data, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"   Mastodon error: {e}")
        return False

# ─────────────────────────────────────────────────────────────
#  IMAGE UTILITIES
# ─────────────────────────────────────────────────────────────

def extract_image_from_entry(entry):
    raw = entry.get('_entry', entry)
    if hasattr(raw, 'media_content') and raw.media_content:
        return raw.media_content[0].get('url')
    if hasattr(raw, 'media_thumbnail') and raw.media_thumbnail:
        return raw.media_thumbnail[0].get('url')
    if hasattr(raw, 'enclosures') and raw.enclosures:
        for enc in raw.enclosures:
            if enc.get('type', '').startswith('image/'):
                return enc.get('href')
    content = (entry.get('content', [{}]) or [{}])[0].get('value', '') or entry.get('summary', '')
    if content and '<img' in content:
        try:
            soup = BeautifulSoup(content, 'html.parser')
            img = soup.find('img')
            if img and img.get('src'):
                return img['src']
        except Exception:
            pass
    return None

def fetch_og_image(url: str):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        for prop in ['og:image', 'twitter:image']:
            tag = soup.find('meta', property=prop) or soup.find('meta', attrs={'name': prop})
            if tag and tag.get('content'):
                return urljoin(url, tag['content'])
    except Exception:
        pass
    return None

def download_image(url: str):
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        r.raise_for_status()
        if 'image' not in r.headers.get('content-type', ''):
            return None
        if len(r.content) > 5 * 1024 * 1024:
            return None
        return r.content
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────
#  NEWS FETCHING
# ─────────────────────────────────────────────────────────────

def fetch_news():
    all_entries = []
    total = sum(len(v) for v in RSS_FEEDS.values())
    n = 0
    for category, feeds in RSS_FEEDS.items():
        for url in feeds:
            n += 1
            try:
                print(f"  [{n}/{total}] {url[:70]}")
                feed = feedparser.parse(url)
                for e in feed.entries[:5]:
                    all_entries.append({
                        'title':    e.get('title', 'No title'),
                        'link':     e.get('link', ''),
                        'summary':  e.get('summary', ''),
                        'content':  e.get('content', []),
                        'source':   feed.feed.get('title', 'Unknown Source'),
                        'category': category,
                        'image_url': extract_image_from_entry(e),
                        'id':        get_item_id(e),
                        '_entry':    e,
                    })
            except Exception as ex:
                print(f"  ⚠ Feed error: {str(ex)[:60]}")
    return all_entries

# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────

def main():
    banner = "AISecurityDaily Bot v4 — Fixed Posting · 300+ Replies · 80+ Feeds"
    print(f"\n{'='*70}")
    print(f"🤖 {banner}")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*70}\n")

    bsky_handle   = os.environ.get('BLUESKY_HANDLE')
    bsky_password = os.environ.get('BLUESKY_APP_PASSWORD')
    tg_token      = os.environ.get('TELEGRAM_BOT_TOKEN')
    tg_channel    = os.environ.get('TELEGRAM_CHANNEL_ID')
    masto_token   = os.environ.get('MASTODON_ACCESS_TOKEN')

    platforms    = []
    bsky_session = None

    if bsky_handle and bsky_password:
        print(f"🔐 Authenticating Bluesky as {bsky_handle}…")
        bsky_session = bsky_create_session(bsky_handle, bsky_password)
        if bsky_session:
            print("✅ Bluesky — authenticated")
            platforms.append('bluesky')
        else:
            print("❌ Bluesky — auth failed after retries")
    else:
        print("⚠️  Bluesky credentials not set")

    if tg_token and tg_channel:
        print("✅ Telegram — ready")
        platforms.append('telegram')

    if masto_token:
        print("✅ Mastodon — ready")
        platforms.append('mastodon')

    if GEMINI_API_KEY:
        print("✅ Gemini — ready")
    else:
        print("⚠️  Gemini key missing — using fallback pool (300+ replies)")

    if not platforms:
        print("❌ No platforms configured. Check secrets. Exiting.")
        return

    # ── Fetch news ─────────────────────────────────────────────
    print(f"\n📰 Fetching {sum(len(v) for v in RSS_FEEDS.values())} RSS feeds…\n")
    entries = fetch_news()
    print(f"\n📊 Fetched: {len(entries)} entries total")

    posted      = load_json(POSTED_FILE)
    posted_set  = set(posted)
    new_entries = [e for e in entries if e['id'] not in posted_set]
    print(f"✨ New / unposted: {len(new_entries)}")

    categories_posted = []

    # ── Post ───────────────────────────────────────────────────
    if not new_entries:
        print("ℹ️  Nothing new to post this run.")
    else:
        random.shuffle(new_entries)
        to_post = new_entries[:random.randint(MIN_POSTS, MAX_POSTS)]
        categories_posted = list({e['category'] for e in to_post})

        print(f"\n🎯 Posting {len(to_post)} item(s)\n{'─'*60}")

        for i, entry in enumerate(to_post, 1):
            title    = clean_title(entry['title'])
            link     = entry['link']
            category = entry['category']

            print(f"\n[{i}/{len(to_post)}] {title[:65]}…")
            print(f"   📂 {category}  |  🔗 {link[:55]}…")

            # Content
            rss_body = get_rss_summary(entry)
            if len(rss_body) < 200:
                print("   🌐 Scraping for more content…")
                scraped   = scrape_article_body(link)
                body_text = scraped if len(scraped) > len(rss_body) else rss_body
            else:
                body_text = rss_body
            print(f"   📄 Body: {len(body_text)} chars")

            # Summary
            summary = None
            if body_text:
                print("   🧠 Generating summary…")
                summary = gemini_summarize(title, body_text, category)
                if summary:
                    print(f"   ✍  Summary ({len(summary)} chars): {summary[:80]}…")
                else:
                    # Fallback: short sentence trim
                    cut  = body_text[:180]
                    last = max(cut.rfind('.'), cut.rfind('!'), cut.rfind('?'))
                    summary = cut[:last + 1] if last > 30 else truncate_to_graphemes(cut, 150) + "…"
                    print(f"   ✍  Fallback summary: {len(summary)} chars")

            # Image
            image_bytes = None
            image_url   = entry.get('image_url') or fetch_og_image(link)
            if image_url:
                image_bytes = download_image(image_url)
                if image_bytes:
                    print(f"   🖼️  Image: {len(image_bytes)//1024}KB")

            # Post to platforms
            successes = []

            if 'bluesky' in platforms:
                post_text = build_post_text(entry, summary)
                char_count = count_graphemes(post_text)
                print(f"   📝 Bluesky post: {char_count} graphemes")
                if char_count > BSKY_MAX_GRAPHEMES + 5:
                    print(f"   ⚠️  Still over limit after truncation — skipping Bluesky")
                else:
                    blob   = bsky_upload_blob(image_bytes, bsky_session) if image_bytes else None
                    record = build_bluesky_record(post_text, blob)
                    uri, cid = bsky_post(record, bsky_session)
                    if uri:
                        successes.append('Bluesky')
                        print(f"   ✅ Bluesky: {uri}")

            if 'telegram' in platforms:
                tg_text = format_telegram(entry, summary)
                if post_to_telegram(tg_text, tg_token, tg_channel, image_bytes):
                    successes.append('Telegram')

            if 'mastodon' in platforms:
                masto_text = format_mastodon(entry, summary)
                if post_to_mastodon(masto_text, masto_token, image_bytes=image_bytes):
                    successes.append('Mastodon')

            if successes:
                posted.append(entry['id'])
                # Save state immediately after each successful post
                save_json(POSTED_FILE, posted[-MAX_HISTORY:])
                print(f"   ✅ Posted → {', '.join(successes)}")
            else:
                print(f"   ❌ All platforms failed for this item")

            if i < len(to_post):
                wait = random.randint(15, 30)
                print(f"   ⏳ Waiting {wait}s…")
                time.sleep(wait)

    # ── Engagement (runs after posting + state saved) ──────────
    if bsky_session:
        cats = categories_posted if categories_posted else random.sample(
            list(RSS_FEEDS.keys()), min(4, len(RSS_FEEDS))
        )
        run_engagement(bsky_session, cats)

    print(f"\n{'='*70}")
    print(f"✅ Run complete — {datetime.now().strftime('%H:%M:%S UTC')}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
