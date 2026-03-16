# 🍽️ Discord Food Tracker Bot

A Discord bot that reminds you to log meals and analyzes food photos for macros & calories using Claude Vision.

## Features

- **Scheduled reminders** at 8am, 11am, 2pm, 5pm, 8pm, 11pm (configurable timezone)
- **Auto-analysis** — drop a food photo in the channel and get an instant macro/kcal breakdown
- **`!analyze`** — reply to any message with a food photo to (re-)analyze it
- **`!schedule`** — view the current reminder schedule
- **`!ping`** — health check

## Setup

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** → name it → **Bot** tab → **Add Bot**
3. Enable these **Privileged Gateway Intents**:
   - Message Content Intent
4. Copy the **Bot Token**
5. Invite the bot to your server using OAuth2 URL Generator:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `Embed Links`

### 2. Get your Channel ID

1. Enable Developer Mode in Discord (Settings → Advanced → Developer Mode)
2. Right-click the channel you want to use → **Copy Channel ID**

### 3. Get an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key

### 4. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```
DISCORD_BOT_TOKEN=your_token
DISCORD_CHANNEL_ID=your_channel_id
ANTHROPIC_API_KEY=sk-ant-...
TIMEZONE=America/Chicago
```

### 5. Run Locally

```bash
pip install -r requirements.txt
python bot.py
```

### 6. Deploy to Railway

1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub**
3. Select your repo
4. Add environment variables in the Railway dashboard (same as `.env`)
5. Railway will auto-detect the `Dockerfile` and deploy

**Important:** In Railway, set the service type to **Worker** (not Web), since this bot doesn't serve HTTP.

## How It Works

1. At each scheduled time, the bot posts a reminder embed in your channel
2. When you reply with a food photo, the bot downloads it and sends it to Claude Vision
3. Claude identifies the foods, estimates portion sizes, and returns a macro breakdown
4. The bot posts the analysis as a clean embed reply

## Customization

Edit `MEAL_SCHEDULE` in `bot.py` to change reminder times or labels:

```python
MEAL_SCHEDULE = [
    (8,  "Breakfast",       "🌅"),
    (11, "Morning Snack",   "🍎"),
    (14, "Lunch",           "🥗"),
    (17, "Afternoon Snack", "🍌"),
    (20, "Dinner",          "🍽️"),
    (23, "Evening Snack",   "🌙"),
]
```
