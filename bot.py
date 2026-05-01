#!/usr/bin/env python3
"""
Creator Growth Research Bot.

Fetches creator economy, social media, and content marketing research, turns the
best source into a readable Bluesky thread, and avoids reposting the same item.
"""

import argparse
import hashlib
import html
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Iterable

import feedparser
import requests


MAX_POST_LENGTH = 300
POSTED_FILE = "posted_items.json"
DEFAULT_THREADS_PER_RUN = 2
REQUEST_TIMEOUT = 18
USER_AGENT = (
    "CreatorGrowthResearchBot/2.0 "
    "(RSS research digest; contact owner via Bluesky profile)"
)


RSS_FEEDS = [
    {
        "name": "Buffer",
        "url": "https://buffer.com/resources/rss/",
        "focus": "social media strategy and creator growth",
        "weight": 3,
    },
    {
        "name": "Creator Science",
        "url": "https://creatorscience.com/feed/",
        "focus": "creator businesses, audience trust, and monetization",
        "weight": 4,
    },
    {
        "name": "Social Media Examiner",
        "url": "https://www.socialmediaexaminer.com/feed/",
        "focus": "platform tactics and social media marketing",
        "weight": 3,
    },
    {
        "name": "Hootsuite Blog",
        "url": "https://blog.hootsuite.com/feed/",
        "focus": "social platform trends and workflows",
        "weight": 2,
    },
    {
        "name": "Social Media Today",
        "url": "https://www.socialmediatoday.com/feeds/news/",
        "focus": "social platform changes and creator discovery",
        "weight": 2,
    },
    {
        "name": "Sprout Social",
        "url": "https://sproutsocial.com/insights/feed/",
        "focus": "social media strategy, analytics, and audience engagement",
        "weight": 2,
    },
    {
        "name": "HubSpot Marketing",
        "url": "https://blog.hubspot.com/marketing/rss.xml",
        "focus": "content marketing, SEO, and audience acquisition",
        "weight": 2,
    },
    {
        "name": "Search Engine Journal",
        "url": "https://www.searchenginejournal.com/feed/",
        "focus": "SEO, discovery, and search behavior",
        "weight": 2,
    },
    {
        "name": "Neal Schaffer",
        "url": "https://nealschaffer.com/feed/",
        "focus": "influencer marketing and social media systems",
        "weight": 2,
    },
]


POSITIVE_KEYWORDS = {
    "audience": 7,
    "creator": 7,
    "followers": 7,
    "growth": 7,
    "content creator": 7,
    "personal brand": 7,
    "content strategy": 6,
    "creator economy": 6,
    "engagement": 6,
    "organic reach": 6,
    "retention": 6,
    "social media": 6,
    "youtube": 6,
    "instagram": 5,
    "tiktok": 5,
    "shorts": 5,
    "reels": 5,
    "algorithm": 5,
    "community": 5,
    "newsletter": 5,
    "monetization": 5,
    "storytelling": 5,
    "hooks": 4,
    "analytics": 4,
    "distribution": 4,
    "seo": 4,
    "search": 4,
    "posting": 4,
    "video": 4,
    "brand": 4,
    "conversion": 3,
    "email": 3,
    "case study": 3,
    "framework": 3,
    "guide": 3,
}

ACTION_KEYWORDS = {
    "how to": 5,
    "guide": 4,
    "tips": 4,
    "strategy": 4,
    "playbook": 4,
    "framework": 4,
    "case study": 3,
    "examples": 3,
    "template": 3,
    "checklist": 3,
    "mistakes": 2,
}

NEGATIVE_KEYWORDS = {
    "press release": -6,
    "product update": -5,
    "funding": -4,
    "acquisition": -4,
    "earnings": -4,
    "webinar": -3,
    "podcast": -2,
    "event recap": -2,
}

NOISE_PHRASES = (
    "cookie",
    "privacy policy",
    "terms of service",
    "subscribe",
    "sign up",
    "advertisement",
    "sponsored",
    "all rights reserved",
    "she specializes",
    "he specializes",
    "they specialize",
    "based in",
    "when she's not",
    "when he's not",
    "when they are not",
    "connect with",
    "follow her",
    "follow him",
    "follow them",
    "about the author",
    "check out this guide",
    "in this guide",
    "keep reading",
    "read on",
    "learn more",
    "we'll cover",
    "we will cover",
)


@dataclass
class ResearchEntry:
    title: str
    link: str
    source: str
    focus: str
    published: str
    summary: str
    content: str
    item_id: str
    score: int


class ArticleTextExtractor(HTMLParser):
    """Small HTML-to-text extractor tuned for article paragraphs."""

    CAPTURE_TAGS = {"p", "li", "h1", "h2", "h3", "blockquote"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "nav"}

    def __init__(self):
        super().__init__()
        self._capture_depth = 0
        self._skip_depth = 0
        self._chunks = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.CAPTURE_TAGS and self._skip_depth == 0:
            self._capture_depth += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.CAPTURE_TAGS and self._capture_depth > 0:
            self._capture_depth -= 1
            self._chunks.append("\n")
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._capture_depth > 0 and self._skip_depth == 0:
            cleaned = normalize_text(data)
            if cleaned:
                self._chunks.append(cleaned)

    def text(self):
        return normalize_text(" ".join(self._chunks))


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("\u2019", "'").replace("\u2018", "'")
    value = value.replace("\u201c", '"').replace("\u201d", '"')
    value = value.replace("\u2013", " - ").replace("\u2014", " - ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_post_text(value: str) -> str:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [normalize_text(line) for line in value.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_posted_items() -> list[str]:
    if not os.path.exists(POSTED_FILE):
        return []

    try:
        with open(POSTED_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return [str(item) for item in data]


def save_posted_item(item_id: str) -> None:
    posted = load_posted_items()
    if item_id not in posted:
        posted.append(item_id)

    posted = posted[-1000:]
    with open(POSTED_FILE, "w", encoding="utf-8") as file:
        json.dump(posted, file, indent=2)
        file.write("\n")


def get_item_id(title: str, link: str) -> str:
    unique_string = f"{link}|{title}".strip()
    return hashlib.sha256(unique_string.encode("utf-8")).hexdigest()


def clean_feed_content(entry) -> tuple[str, str]:
    summary = normalize_text(entry.get("summary", ""))
    content_parts = []

    for content_item in entry.get("content", []) or []:
        content_parts.append(normalize_text(content_item.get("value", "")))

    return summary, normalize_text(" ".join(content_parts))


def score_text(text: str, source_weight: int = 0) -> int:
    lowered = text.lower()
    score = source_weight

    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword in lowered:
            score += weight

    for keyword, weight in ACTION_KEYWORDS.items():
        if keyword in lowered:
            score += weight

    for keyword, weight in NEGATIVE_KEYWORDS.items():
        if keyword in lowered:
            score += weight

    return score


def fetch_feed_entries(feed_config: dict) -> list[ResearchEntry]:
    print(f"Fetching feed: {feed_config['name']}")
    try:
        response = requests.get(
            feed_config["url"],
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"  skipped: {exc}")
        return []

    feed = feedparser.parse(response.content)
    if not feed.entries:
        print("  skipped: no entries found")
        return []

    entries = []
    for raw_entry in feed.entries[:8]:
        title = normalize_text(raw_entry.get("title", ""))
        link = raw_entry.get("link", "").strip()
        if not title or not link:
            continue

        summary, content = clean_feed_content(raw_entry)
        combined = " ".join([title, summary, content, feed_config["focus"]])
        score = score_text(combined, feed_config.get("weight", 0))

        entries.append(
            ResearchEntry(
                title=title,
                link=link,
                source=feed_config["name"],
                focus=feed_config["focus"],
                published=raw_entry.get("published", ""),
                summary=summary,
                content=content,
                item_id=get_item_id(title, link),
                score=score,
            )
        )

    print(f"  found {len(entries)} usable entries")
    return entries


def fetch_research_entries() -> list[ResearchEntry]:
    all_entries = []
    for feed_config in RSS_FEEDS:
        all_entries.extend(fetch_feed_entries(feed_config))

    all_entries.sort(key=lambda entry: entry.score, reverse=True)
    return all_entries


def fetch_article_text(url: str) -> str:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        return ""

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return ""

    parser = ArticleTextExtractor()
    try:
        parser.feed(response.text)
    except Exception:
        return ""

    return parser.text()


def split_sentences(text: str) -> list[str]:
    cleaned = normalize_text(text)
    if not cleaned:
        return []

    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    return [piece.strip() for piece in pieces if piece.strip()]


def is_noise_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if len(sentence) < 45 or len(sentence) > 260:
        return True
    return any(phrase in lowered for phrase in NOISE_PHRASES)


def choose_best_sentences(text: str, limit: int = 2) -> list[str]:
    candidates = []
    for sentence in split_sentences(text):
        if is_noise_sentence(sentence):
            continue
        candidates.append((score_text(sentence), sentence))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = []
    seen_stems = set()

    for _, sentence in candidates:
        stem = " ".join(sentence.lower().split()[:8])
        if stem in seen_stems:
            continue
        selected.append(sentence)
        seen_stems.add(stem)
        if len(selected) == limit:
            break

    return selected


def make_creator_action(title: str, text: str) -> str:
    title_lower = title.lower()
    lowered = f"{title} {text}".lower()

    if any(word in title_lower for word in ("community", "comments", "conversation")):
        return (
            "Build a reply loop. End the post with a sharp question, then turn the "
            "best replies into tomorrow's content ideas."
        )
    video_words = ("youtube", "shorts", "video", "reels", "tiktok")
    if any(word in title_lower for word in video_words):
        return (
            "Open with the result, not the intro. In the first 2 seconds, show "
            "the problem, the payoff, or the surprising proof."
        )
    if any(word in title_lower for word in ("seo", "search", "google", "discovery")):
        return (
            "Make one searchable asset from the idea: a clear title, a direct "
            "answer, examples, and internal links to your strongest related posts."
        )
    if any(word in title_lower for word in ("monetization", "business", "sponsor", "revenue")):
        return (
            "Tie content to one audience pain. Teach the pain publicly, then offer "
            "a deeper solution through a product, service, sponsor, or newsletter."
        )
    if any(word in lowered for word in ("community", "comments", "conversation")):
        return (
            "Build a reply loop. End the post with a sharp question, then turn the "
            "best replies into tomorrow's content ideas."
        )
    if any(word in lowered for word in ("newsletter", "email", "owned audience")):
        return (
            "Move attention into an owned channel. Give followers a simple reason "
            "to join: a checklist, template, weekly breakdown, or private note."
        )
    if any(word in lowered for word in ("analytics", "metrics", "data", "benchmark")):
        return (
            "Track saves, shares, replies, profile clicks, and follows per post. "
            "Those signals tell you what to repeat better than likes alone."
        )
    if sum(word in lowered for word in video_words) >= 2:
        return (
            "Open with the result, not the intro. In the first 2 seconds, show "
            "the problem, the payoff, or the surprising proof."
        )
    if any(word in lowered for word in ("algorithm", "reach", "discover", "discovery")):
        return (
            "Turn the idea into one repeatable format. Post 5 versions with a "
            "different hook, then keep the one that earns saves and replies."
        )
    if any(word in lowered for word in ("seo", "search", "google", "discovery")):
        return (
            "Make one searchable asset from the idea: a clear title, a direct "
            "answer, examples, and internal links to your strongest related posts."
        )
    if any(word in lowered for word in ("monetization", "business", "sponsor", "revenue")):
        return (
            "Tie content to one audience pain. Teach the pain publicly, then offer "
            "a deeper solution through a product, service, sponsor, or newsletter."
        )

    return (
        "Before posting, write the audience problem, promised outcome, and one "
        "proof point. That makes the idea useful instead of generic."
    )


def trim_to_limit(text: str, limit: int = MAX_POST_LENGTH) -> str:
    text = normalize_post_text(text)
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 3)].rstrip()
    last_space = cut.rfind(" ")
    if last_space > limit * 0.6:
        cut = cut[:last_space].rstrip()
    return cut.rstrip(" ,;:-") + "..."


def fit_template(prefix: str, body: str, suffix: str = "", limit: int = MAX_POST_LENGTH) -> str:
    fixed_length = len(prefix) + len(suffix)
    budget = max(0, limit - fixed_length)
    return f"{prefix}{trim_to_limit(body, budget)}{suffix}"


def pack_insights(insights: list[str], prefix: str) -> str:
    body = ""
    for insight in insights[:2]:
        candidate = insight if not body else f"{body}\n\n{insight}"
        if len(prefix) + len(normalize_post_text(candidate)) <= MAX_POST_LENGTH:
            body = candidate

    if body:
        return body

    budget = MAX_POST_LENGTH - len(prefix)
    return trim_to_limit(insights[0], budget)


def build_thread(entry: ResearchEntry) -> list[str]:
    article_text = fetch_article_text(entry.link)
    research_text = normalize_text(" ".join([entry.content, entry.summary, article_text]))
    insights = choose_best_sentences(research_text, limit=2)

    if not insights:
        fallback = entry.summary or entry.content or entry.focus
        insights = [trim_to_limit(fallback, 220)]

    action = make_creator_action(entry.title, research_text)
    title = trim_to_limit(entry.title, 190)

    post_1 = fit_template(
        "Creator growth research:\n\n",
        f"{title}\n\nWhy it matters: {entry.focus}.",
    )

    post_2_prefix = "Useful signal:\n\n"
    post_2 = fit_template(post_2_prefix, pack_insights(insights, post_2_prefix))

    post_3 = fit_template("Creator move:\n\n", action)

    source_prefix = f"Source: {entry.source}\n"
    hashtags = "\n\n#ContentCreator #CreatorEconomy #AudienceGrowth"
    post_4 = fit_template(source_prefix, entry.link, hashtags)

    return [post_1, post_2, post_3, post_4]


def create_bluesky_session(handle: str, app_password: str) -> dict | None:
    try:
        response = requests.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": app_password},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Error creating session: {exc}")
        return None


def post_to_bluesky(post_text: str, session: dict, reply: dict | None = None) -> dict | None:
    record = {
        "$type": "app.bsky.feed.post",
        "text": trim_to_limit(post_text),
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "langs": ["en"],
    }
    if reply:
        record["reply"] = reply

    try:
        response = requests.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {session['accessJwt']}"},
            json={
                "repo": session["did"],
                "collection": "app.bsky.feed.post",
                "record": record,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        print(f"Error posting to Bluesky: {exc}")
        return None


def post_thread_to_bluesky(thread: list[str], session: dict, dry_run: bool = False) -> int:
    root_ref = None
    parent_ref = None
    published = 0

    for index, post_text in enumerate(thread, 1):
        print(f"\nThread post {index}/{len(thread)} ({len(post_text)} chars)")
        print(post_text)

        if dry_run:
            published += 1
            continue

        reply_ref = None
        if root_ref and parent_ref:
            reply_ref = {"root": root_ref, "parent": parent_ref}

        result = post_to_bluesky(post_text, session, reply_ref)
        if not result:
            break

        current_ref = {"uri": result["uri"], "cid": result["cid"]}
        if root_ref is None:
            root_ref = current_ref
        parent_ref = current_ref
        published += 1

        if index < len(thread):
            time.sleep(random.randint(6, 10))

    return published


def select_entries(entries: Iterable[ResearchEntry], posted_items: set[str], limit: int) -> list[ResearchEntry]:
    new_entries = [entry for entry in entries if entry.item_id not in posted_items]
    strong_entries = [entry for entry in new_entries if entry.score >= 10]
    pool = strong_entries or new_entries
    return list(pool[:limit])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post creator growth research threads to Bluesky.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and format threads without posting to Bluesky.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("THREADS_PER_RUN", DEFAULT_THREADS_PER_RUN)),
        help="Number of research threads to publish.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    limit = max(1, min(args.limit, 5))
    dry_run = args.dry_run or os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"}

    print("\n" + "=" * 60)
    print(f"Creator Growth Research Bot - {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60 + "\n")

    session = None
    if not dry_run:
        handle = os.environ.get("BLUESKY_HANDLE")
        app_password = os.environ.get("BLUESKY_APP_PASSWORD")

        if not handle or not app_password:
            print("ERROR: Missing BLUESKY_HANDLE or BLUESKY_APP_PASSWORD.")
            return

        print("Authenticating with Bluesky...")
        session = create_bluesky_session(handle, app_password)
        if not session:
            print("Failed to authenticate. Exiting.")
            return
        print("[ok] Authentication successful")
    else:
        print("[dry-run] Fetching and formatting only. Nothing will be posted.")

    entries = fetch_research_entries()
    print(f"\nFound {len(entries)} total research entries")

    if not entries:
        print("No entries found. Exiting.")
        return

    posted_items = set(load_posted_items())
    to_post = select_entries(entries, posted_items, limit)
    print(f"Selected {len(to_post)} new high-signal entries\n")

    if not to_post:
        print("No new entries to post. Exiting.")
        return

    for index, entry in enumerate(to_post, 1):
        print("-" * 60)
        print(f"Research brief {index}/{len(to_post)}")
        print(f"Title : {entry.title}")
        print(f"Source: {entry.source}")
        print(f"Score : {entry.score}")

        thread = build_thread(entry)
        published_count = post_thread_to_bluesky(thread, session, dry_run=dry_run)

        if published_count:
            print(f"[ok] Published/formatted {published_count}/{len(thread)} posts")
            if not dry_run:
                save_posted_item(entry.item_id)
        else:
            print("[warn] No posts were published for this entry")

        if not dry_run and index < len(to_post):
            wait_time = random.randint(25, 45)
            print(f"Waiting {wait_time}s before next research brief...")
            time.sleep(wait_time)

    print("\n" + "=" * 60)
    print(f"Bot finished at {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
