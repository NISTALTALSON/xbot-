# Creator Growth Research Bot

An automated Bluesky bot that researches creator economy, social media, content marketing, SEO, and audience-growth sources, then turns the best items into readable mini-threads.

The goal is not to spam links. The bot posts useful research briefs that help followers learn how to become better content creators, grow an audience, and build repeatable content systems.

## What It Does

- Fetches creator-growth research from RSS feeds.
- Scores each item for practical creator value.
- Pulls readable context from RSS summaries and article pages.
- Formats each source as a 4-post Bluesky thread:
  - Creator growth research hook
  - Useful signal from the article
  - Concrete creator move
  - Source link and hashtags
- Avoids duplicate posts with `posted_items.json`.
- Saves posted history back to GitHub when it runs in Actions.
- Supports dry runs so you can preview posts before publishing.

## Sources

Current feeds in `bot.py`:

- Buffer
- Creator Science
- Social Media Examiner
- Hootsuite Blog
- Social Media Today
- Sprout Social
- HubSpot Marketing
- Search Engine Journal
- Neal Schaffer

These are chosen because they regularly cover audience growth, creator strategy, platform changes, content marketing, SEO, and monetization.

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Add Bluesky Secrets

In your GitHub repository, go to:

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Add:

| Secret Name | Value |
| --- | --- |
| `BLUESKY_HANDLE` | Your Bluesky handle |
| `BLUESKY_APP_PASSWORD` | A Bluesky app password |

### 3. Run Locally Without Posting

```bash
python bot.py --dry-run --limit 1
```

This fetches sources and prints the thread without posting.

### 4. Run Locally and Post

```bash
set BLUESKY_HANDLE=your-handle.bsky.social
set BLUESKY_APP_PASSWORD=your-app-password
python bot.py --limit 1
```

PowerShell:

```powershell
$env:BLUESKY_HANDLE="your-handle.bsky.social"
$env:BLUESKY_APP_PASSWORD="your-app-password"
python bot.py --limit 1
```

## GitHub Actions

The workflow in `.github/workflows/bot.yml` runs every 6 hours and posts 2 research threads per run.

You can change the amount with:

```yaml
THREADS_PER_RUN: 1
```

Use fewer threads if you want a calmer account. Quality and consistency are better for follower growth than high-volume posting.

## Customization

### Change The Niche

Edit `RSS_FEEDS` in `bot.py`. Add sources that match the audience you want to attract.

### Tune What Gets Picked

Edit these dictionaries in `bot.py`:

- `POSITIVE_KEYWORDS`
- `ACTION_KEYWORDS`
- `NEGATIVE_KEYWORDS`

Higher scores make the bot prioritize those topics.

### Change The Thread Style

Edit `build_thread()` and `make_creator_action()` in `bot.py`.

## Growth Notes

This bot can help by posting useful, consistent research. It cannot guarantee thousands of followers by itself. Real growth usually comes from a clear niche, useful posts, replies, collaborations, profile positioning, and repeated testing of what the audience saves and shares.

Use the bot as the research engine. Pair it with human replies and original opinions for best results.
