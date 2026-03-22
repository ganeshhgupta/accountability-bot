# Accountability Bot

A WhatsApp accountability bot that proactively texts you throughout the day, tracks your daily tasks, uses CBT techniques to push you through resistance, and behaves like a relentless manager who never backs down.

## Stack

- Python 3.11 / Flask
- APScheduler (persistent background scheduler)
- Groq API (llama-3.3-70b-versatile — free tier)
- Twilio WhatsApp API
- Google Docs API (motivation context)
- Upstash Redis (state persistence)
- Railway (deployment)

---

## API Keys — Where to Get Them

| Variable | Where to get it |
|---|---|
| `TWILIO_ACCOUNT_SID` | Twilio Console → Account Info |
| `TWILIO_AUTH_TOKEN` | Twilio Console → Account Info |
| `TWILIO_WHATSAPP_FROM` | Twilio sandbox number (default `whatsapp:+14155238886`) |
| `MY_WHATSAPP_NUMBER` | Your own number in `whatsapp:+1XXXXXXXXXX` format |
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `GOOGLE_SERVICE_ACCOUNT_B64` | See Google setup below |
| `GDOC_MOTIVATION_ID` | The ID from your Google Doc URL |
| `UPSTASH_REDIS_REST_URL` | console.upstash.com → Your database → REST API |
| `UPSTASH_REDIS_REST_TOKEN` | console.upstash.com → Your database → REST API |
| `EDIT_SECRET` | Any secret string you choose |

---

## Step-by-Step Setup

### 1. Google Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable the **Google Docs API**
4. Go to **IAM & Admin → Service Accounts** → Create Service Account
5. Download the JSON key file
6. Base64-encode it (no line wraps):
   ```bash
   base64 -w 0 service_account.json
   ```
7. Paste the output as `GOOGLE_SERVICE_ACCOUNT_B64`
8. Share your motivation Google Doc with the service account email (Viewer access)
9. Copy the Doc ID from the URL: `docs.google.com/document/d/YOUR_DOC_ID/edit`

### 2. Upstash Redis

1. Go to [console.upstash.com](https://console.upstash.com)
2. Create a new Redis database (free tier is fine)
3. Copy the **REST URL** and **REST Token** from the database page

### 3. Twilio WhatsApp Sandbox

1. Go to [Twilio Console](https://console.twilio.com) → Messaging → Try it out → Send a WhatsApp message
2. Follow the sandbox join instructions (text the join keyword)
3. Set the webhook URL to `https://your-railway-app.railway.app/webhook`
4. Set **Method** to `POST`

> **Note**: The sandbox requires you to have messaged the bot within the last 24 hours for outbound messages to work. This is a sandbox limitation. For production, apply for a WhatsApp Business API number.

### 4. Local Development

```bash
cp .env.example .env
# Fill in all values in .env

pip install -r requirements.txt
python bot.py
```

Use [ngrok](https://ngrok.com) to expose your local server to Twilio:
```bash
ngrok http 5000
# Set Twilio webhook to your ngrok URL + /webhook
```

---

## Railway Deployment

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Select your repo
4. Go to **Variables** and add all env vars from `.env.example`
5. Railway will auto-detect `railway.toml` and deploy

The app starts automatically with `python bot.py`, which runs startup health checks, then starts the scheduler and Flask server.

---

## Schedule (Central Time)

| Time | Day | Message |
|---|---|---|
| 9:00 AM | Mon-Fri | Morning kickoff — ask for today's plan |
| 10:30 AM | Mon-Fri | Procrastination check |
| 12:30 PM | Mon-Fri | Midday accountability |
| 3:30 PM | Mon-Fri | Afternoon push |
| 6:00 PM | Mon-Fri | Evening check + task review |
| 9:00 PM | Mon-Fri | Wind down, reflection |
| 11:30 PM | Mon-Fri | Final accountability |
| 6:30 PM | Saturday | Weekend check-in |
| 9:00 PM | Saturday | Saturday wind-down |
| Sunday | — | OFF |

---

## How to Use /update

From WhatsApp, text the bot:

```
/update I'm interviewing at Google next Friday. My main anxiety is system design rounds.
```

The bot will use this context instead of the Google Doc for all future messages.

To revert to the Google Doc:
```
/update clear
```

---

## Testing with /trigger

Manually fire any scheduled message without waiting for the clock:

```bash
# Requires X-Token header matching EDIT_SECRET
curl -H "X-Token: your_secret" https://your-app.railway.app/trigger/morning
curl -H "X-Token: your_secret" https://your-app.railway.app/trigger/evening
curl -H "X-Token: your_secret" https://your-app.railway.app/trigger/ghost
```

Valid trigger types: `morning`, `procrastination_check`, `midday`, `afternoon_nudge`, `evening`, `winddown`, `final`, `weekend_checkin`, `saturday_winddown`, `ghost`

Check current bot state:
```bash
curl -H "X-Token: your_secret" https://your-app.railway.app/status
```

---

## How to Read FIXES.md

`FIXES.md` is the project's institutional memory for bugs and gotchas. It has two sections:

1. **Known Gotchas** (pre-populated) — common failure modes and the rules to avoid them
2. **Fix Log** — entries added after each bug fix, with error message, root cause, fix applied, and prevention rule

Read it before making changes. Add an entry after every fix.

---

## Agent Architecture

| Agent | File | Role |
|---|---|---|
| Orchestrator | `agents/orchestrator.py` | Routes every incoming message to the right handler |
| Task | `agents/task_agent.py` | Manages daily task list and completion pings |
| Mood | `agents/mood_agent.py` | Handles emotional states with CBT techniques |
| Ghost | `agents/ghost_agent.py` | Escalates when user goes silent |
| Schedule | `agents/schedule_agent.py` | Enforces active time windows |
| Motivation | `agents/motivation_agent.py` | Provides motivation doc context |
