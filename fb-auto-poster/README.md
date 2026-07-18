# FB Auto Poster

A simplified Facebook auto-posting tool that listens for Telegram messages and posts them to Facebook groups with AI rewriting. Built as a single Flask app with a web dashboard — no Docker, no n8n, no external orchestration needed.

## Architecture

```
Browser Dashboard ←→ Flask API (app.py) ←→ JSON files (data/)
                         ↓
                   Playwright (Chromium)
                         ↓
                    Facebook Groups
```

**Tech Stack:**
- Python + Flask (web server & API)
- Playwright (Facebook browser automation)
- OpenAI API (post rewriting)
- Telegram Bot API (message listening & notifications)
- JSON files (data persistence)
- Single HTML dashboard (no build tools)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Log into Facebook

```bash
python login.py
```

A Chrome window will open — log into Facebook, wait for your feed to load, then press Enter in the terminal. Your session cookies will be saved to `data/fb_session.json`.

### 3. Configure

Edit `config.env` with your credentials:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_chat_id
OPENAI_API_KEY=your_openai_api_key
```

Or configure everything from the dashboard Settings tab.

### 4. Run

```bash
python app.py
```

The dashboard opens at **http://localhost:5000**. From there you can:

- **Start the Telegram Listener** — captures messages you send to your bot
- **Manage Groups** — add the Facebook groups you want to post to
- **Run the Pipeline** — rewrites and posts captured messages to all groups
- **Enable Auto-Pilot** — schedule automatic pipeline runs every N hours

## How It Works

1. **Send a message** (text or photo+caption) to your Telegram bot
2. The **Telegram Listener** captures it and saves to `data/posts.json`
3. When you **Run the Pipeline** (or it runs on schedule):
   - Each post is **rewritten** by OpenAI for each target group (unique versions)
   - Each rewritten post is **posted to Facebook** via Playwright automation
   - A **Telegram notification** is sent with the results summary
4. The **Session Keeper** automatically refreshes your Facebook session to prevent expiry

## Project Structure

```
fb-auto-poster/
├── app.py                  # Main Flask application (all logic)
├── login.py                # Facebook login helper
├── config.env              # Environment variables template
├── requirements.txt        # Python dependencies
├── templates/
│   └── dashboard.html      # Web dashboard (single-page app)
└── data/
    ├── posts.json           # Captured posts
    ├── groups.json          # Target Facebook groups
    ├── channels.json        # Telegram channels config
    ├── settings.json        # App settings
    ├── run_history.json     # Pipeline run history
    ├── fb_session.json      # Facebook session cookies (auto-created)
    └── uploads/             # Downloaded Telegram images (auto-created)
```

## Dashboard Features

- **Dark theme** with modern glassmorphism UI
- **Real-time pipeline logs** via Server-Sent Events
- **Post management** — view, filter, and delete captured posts
- **Group management** — add, edit, toggle, and delete target groups
- **Settings panel** — configure everything from the browser
- **Run history** — view past pipeline executions with details
- **Auto-pilot scheduler** — set-and-forget automation

## Compared to the Old Version

| Feature | Old (Docker + n8n) | New (this) |
|---------|-------------------|------------|
| Setup | Docker, n8n, supervisord | `pip install` + `python app.py` |
| UI | None | Web dashboard |
| Orchestration | n8n workflows | Python threads + scheduler |
| Data storage | Google Sheets | Local JSON files |
| Processes | 7+ managed by supervisord | Single Python process |
| Config | config.env + n8n UI | Dashboard settings panel |

## Tips

- **Session expired?** Run `python login.py` again or click "Refresh Session" in the dashboard
- **Rate limited?** Increase the delay settings in the Settings tab
- **Test posting:** Add a single test group and send a short message to your bot first
- **Headless mode:** Enabled by default. Disable in Settings to see the browser during automation (useful for debugging)
