# Accountability Bot - Claude Code Instructions

## Project Overview
A WhatsApp accountability bot that proactively texts the user throughout the day,
tracks their daily tasks, uses psychological/CBT techniques to push them through
resistance, and behaves like a relentless manager who never backs down.

## Stack
- Python 3.11
- Flask (webhook server)
- APScheduler (persistent scheduler)
- Groq API (LLM, free tier, llama-3.3-70b-versatile)
- Twilio WhatsApp API
- Google Docs API (motivation context doc)
- Upstash Redis (chat history + state persistence)
- Railway (deployment)

## Project Structure
```
accountability-bot/
├── CLAUDE.md               # This file
├── FIXES.md                # Error log - Claude populates this after every fix
├── bot.py                  # Flask app, webhook handler, /update command
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py     # Master agent - routes to sub-agents
│   ├── task_agent.py       # Manages daily task list, pings for completion
│   ├── mood_agent.py       # Handles emotional states, CBT reframes
│   ├── ghost_agent.py      # Escalates frequency when user ghosts
│   ├── schedule_agent.py   # Determines if bot should be active right now
│   └── motivation_agent.py # Fetches + rephrases motivation doc content
├── memory.py               # Upstash Redis wrapper
├── llm.py                  # Groq API wrapper with all system prompts
├── gdocs.py                # Google Docs API fetcher
├── scheduler.py            # APScheduler setup with time window enforcement
├── config.py               # All constants, schedule windows, intent patterns
├── requirements.txt
├── Procfile
├── railway.toml
├── nixpacks.toml
└── .env.example
```

## FIXES.md Protocol
CRITICAL: Every time you fix a bug, add an entry to FIXES.md in this format:
```
## Fix #N - [date]
**Error**: exact error message or description
**Root Cause**: why it happened
**Fix Applied**: what you changed
**Files Modified**: list of files
**Prevention**: how to avoid this class of error in future
```
Read FIXES.md at the start of every session to avoid repeating past mistakes.

## Environment Variables Required
```
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
MY_WHATSAPP_NUMBER=whatsapp:+1XXXXXXXXXX
GROQ_API_KEY=
GOOGLE_SERVICE_ACCOUNT_JSON=  # full JSON string, not file path
GDOC_MOTIVATION_ID=           # Google Doc ID from URL
UPSTASH_REDIS_REST_URL=
UPSTASH_REDIS_REST_TOKEN=
EDIT_SECRET=                  # secret token for /update whatsapp command
```

## Agent Architecture (5 agents)

### 1. Orchestrator Agent (orchestrator.py)
- Entry point for every incoming message
- Classifies user intent using pattern matching + LLM
- Routes to appropriate sub-agent
- Intents: TASK_UPDATE, STUCK, LOW_MOOD, TASK_REPORT, GHOST_BREAK, NEGATIVE_PUSH,
           PLAN_SUBMISSION, PLAN_REQUEST, UPDATE_DOC, CASUAL, COMPLETION_REPORT

### 2. Task Agent (task_agent.py)
- Stores daily task list in Redis (key: tasks:YYYY-MM-DD)
- When plan submitted: parses tasks, stores them, sets up ping schedule
- Tracks completion status per task
- Sends ordered pings: "Did you finish X? What's next?"
- Escalates if task not confirmed after 90 minutes

### 3. Mood Agent (mood_agent.py)
- Handles: "I'm stuck", "I don't feel like it", "I'm tired", "I can't"
- "stuck" -> asks exactly where stuck, gives concrete micro-step
- "don't feel like" -> asks exactly why, then uses motivation doc to counter
- "negative/stop texting" -> acknowledges but DOES NOT stop, reframes and pushes harder
- Uses CBT techniques: thought challenging, behavioral activation, values clarification

### 4. Ghost Agent (ghost_agent.py)
- Tracks last_response_time in Redis
- If no response for 45min during active hours: send nudge
- If no response for 90min: escalate tone
- If no response for 2hrs: send annoying rapid-fire messages (every 15 min)
- If user says "stop" or "leave me alone": log it but KEEP GOING with reframe
- Backs off only when task completion confirmed or day ends

### 5. Schedule Agent (schedule_agent.py)
- Enforces time windows:
  - Mon-Fri: 9:00 AM - 12:00 AM (midnight) CT
  - Saturday: 6:00 PM - 11:00 PM CT
  - Sunday: OFF
- ALL outbound messages (scheduled + ghost) must pass through this agent first
- Returns True/False for whether bot should be active right now

## Schedule Windows (Central Time, Arlington TX)
```python
SCHEDULE_WINDOWS = {
    0: {"active": True,  "start": "09:00", "end": "23:59"},  # Monday
    1: {"active": True,  "start": "09:00", "end": "23:59"},  # Tuesday
    2: {"active": True,  "start": "09:00", "end": "23:59"},  # Wednesday
    3: {"active": True,  "start": "09:00", "end": "23:59"},  # Thursday
    4: {"active": True,  "start": "09:00", "end": "23:59"},  # Friday
    5: {"active": True,  "start": "18:00", "end": "23:00"},  # Saturday
    6: {"active": False, "start": None,    "end": None},     # Sunday OFF
}
```

## Scheduled Message Times (only fires if within window)
- 9:00 AM Mon-Fri: Morning kickoff - ask for today's plan
- 10:30 AM Mon-Fri: Procrastination check
- 12:30 PM Mon-Fri: Midday accountability
- 3:30 PM Mon-Fri: Afternoon push
- 6:00 PM Mon-Fri: Evening check + task review
- 9:00 PM Mon-Fri: Wind down, reflection
- 11:30 PM Mon-Fri: Final accountability before midnight
- 6:30 PM Sat: Weekend check-in
- 9:00 PM Sat: Saturday wind-down

## /update WhatsApp Command
User texts: `/update [new motivation content]`
- Bot verifies it came from MY_WHATSAPP_NUMBER
- Updates the motivation doc cache in Redis (key: motivation:override)
- If override exists, use it instead of fetching Google Docs
- Reply: "Got it. I've updated your context. I'll use this going forward."
- User can also text: `/update clear` to go back to Google Docs version

## Redis Key Schema
```
chat_history          -> list of last 50 {role, content, timestamp} messages
tasks:YYYY-MM-DD      -> JSON list of {task, status, order, pinged_at}
last_response_time    -> ISO timestamp of user's last reply
ghost_level           -> int 0-3 (escalation level)
motivation:override   -> string (user's /update content, overrides gdoc)
motivation:cache      -> string (cached gdoc content, refreshed every 6hrs)
motivation:cache_time -> ISO timestamp of last gdoc fetch
day_state             -> JSON {plan_received: bool, morning_done: bool, date: str}
```

## LLM Prompt Philosophy
Every prompt must:
1. Reference the motivation doc content inline
2. Be WhatsApp-native: short, punchy, conversational
3. Never use bullet points or numbered lists in the message text
4. Vary technique per message (don't repeat same approach twice in a row)
5. For negative responses ("stop", "leave me alone"): acknowledge the feeling,
   then immediately reframe and push. NEVER comply with stopping.
6. Always end proactive messages with either a direct question or a direct instruction

## Intent Detection Patterns (config.py)
```python
INTENT_PATTERNS = {
    "STUCK": ["stuck", "can't figure", "don't know how", "blocked", "confused", "lost"],
    "LOW_MOOD": ["don't feel like", "not feeling it", "tired", "exhausted", "lazy",
                 "unmotivated", "what's the point", "pointless", "why bother"],
    "NEGATIVE_PUSH": ["stop texting", "leave me alone", "stop it", "shut up",
                      "go away", "i don't care", "whatever", "not now"],
    "COMPLETION_REPORT": ["done", "finished", "completed", "did it", "wrapped up", "checked off"],
    "PLAN_SUBMISSION": ["my plan", "today i will", "planning to", "tasks for today",
                        "going to", "will do", "my tasks"],
    "UPDATE_DOC": ["/update"],
}
```

## Error Handling Rules
- All Groq API calls: retry up to 3 times with exponential backoff
- All Twilio sends: catch TwilioRestException, log to FIXES.md format, don't crash
- All Redis ops: wrap in try/except, fall back to in-memory dict if Redis fails
- All Google Docs fetches: cache aggressively (6hr TTL), fall back to cached version
- Flask: never return 500 to Twilio (Twilio retries on 5xx, causing duplicate messages)
  Always return 200 with empty TwiML if there's an internal error

## Testing
- Add a /test endpoint (GET, requires EDIT_SECRET header) that sends a test message
- Add a /status endpoint that returns current Redis state as JSON
- Add a /trigger/<type> endpoint to manually fire any scheduled message type

## Code Style
- Type hints on all functions
- Docstrings on all agent methods
- Log every outbound message with timestamp and trigger type
- Log every inbound message with detected intent
- Keep each agent file under 200 lines
- No hardcoded strings in agent files - all prompts in llm.py
