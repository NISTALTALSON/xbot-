# X News Bot - Automated AI & Cybersecurity Updates

Automatically posts AI and cybersecurity news to your X (Twitter) account every 6 hours.

## Features

- 🤖 Fully automated - runs on GitHub Actions (100% free)
- 📰 Pulls from 9+ top RSS feeds (AI, cybersecurity, ethical hacking)
- 🔄 Posts 2-3 random updates every 6 hours
- 🚫 Avoids duplicates - tracks what's already posted
- #️⃣ Automatically adds relevant hashtags
- ⚡ Rate limiting to avoid API issues

## News Sources

**AI:**
- ArXiv AI Research
- Google AI Blog
- OpenAI Blog

**Cybersecurity & Ethical Hacking:**
- BleepingComputer
- The Hacker News
- Dark Reading
- Krebs on Security
- Schneier on Security
- Threatpost

## Setup Instructions

### 1. Fork/Create GitHub Repository

1. Create a new repository on GitHub (can be private)
2. Upload these files:
   - `bot.py`
   - `requirements.txt`
   - `.github/workflows/bot.yml`

### 2. Add X API Secrets to GitHub

1. Go to your repo → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add these 4 secrets:

   | Secret Name | Value |
   |-------------|-------|
   | `X_CONSUMER_KEY` | Your consumer key |
   | `X_CONSUMER_SECRET` | Your consumer secret |
   | `X_ACCESS_TOKEN` | Your access token |
   | `X_ACCESS_TOKEN_SECRET` | Your access token secret |

### 3. Enable GitHub Actions

1. Go to **Actions** tab in your repo
2. Click **"I understand my workflows, go ahead and enable them"**
3. The bot will now run automatically every 6 hours!

### 4. Test It Manually (Optional)

1. Go to **Actions** → **X News Bot**
2. Click **Run workflow** → **Run workflow**
3. Watch it run in real-time
4. Check your X account for new posts!

## Schedule

The bot runs at:
- 12:00 AM UTC (6:00 PM EST)
- 6:00 AM UTC (12:00 AM EST)
- 12:00 PM UTC (6:00 AM EST)
- 6:00 PM UTC (12:00 PM EST)

**Total:** 8-12 posts per day

## Customization

### Change Posting Frequency

Edit `.github/workflows/bot.yml`:

```yaml
# Every 3 hours
- cron: '0 */3 * * *'

# Every 12 hours
- cron: '0 */12 * * *'

# Daily at 9 AM UTC
- cron: '0 9 * * *'
```

### Add More RSS Feeds

Edit `bot.py` and add to `RSS_FEEDS` list:

```python
RSS_FEEDS = [
    # Your existing feeds...
    "https://your-favorite-blog.com/feed/",
]
```

### Change Hashtags

Edit the `format_tweet()` function in `bot.py`:

```python
hashtags = "\n\n#AI #MachineLearning #Security"
```

### Change Posts Per Run

Edit this line in `bot.py`:

```python
# Posts 2-3 tweets per run (change the numbers)
to_post = new_entries[:random.randint(2, 3)]
```

## Monitoring

- Check **Actions** tab to see bot runs
- Green checkmark = success
- Red X = error (check logs)
- Your X account for posted tweets

## Troubleshooting

### Bot Not Posting?

1. Check Actions tab for errors
2. Verify all 4 API secrets are correct
3. Make sure X API keys are valid
4. Check if you hit X's rate limits

### Posting Duplicates?

The `posted_items.json` file tracks posted items. If it's not working:
1. Check if the file is being committed
2. Ensure workflow has write permissions

### Want to Stop the Bot?

1. Go to **Actions** tab
2. Click **X News Bot**
3. Click **•••** menu → **Disable workflow**

## Cost

**$0.00** - Completely free!
- GitHub Actions: 2,000 minutes/month (free tier)
- X API: Free tier (with limits)
- RSS feeds: Free

## Privacy & Security

- Never commit API keys to the repo
- Use GitHub Secrets only
- Bot only posts, doesn't read DMs or user data

## License

MIT License - Do whatever you want with it!

## Support

Having issues? Check:
1. GitHub Actions logs
2. X API status
3. RSS feed availability

---

**Made with 🤖 by an automated bot**
