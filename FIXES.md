# FIXES.md - Error Log & Prevention Guide

> Claude: Read this file at the start of every session.
> After every bug fix, add an entry below using the format shown.
> This file is the project's institutional memory for errors.

---

## How to Add an Entry
```
## Fix #N - YYYY-MM-DD
**Error**: exact error message or description of the bug
**Root Cause**: why it happened (be specific)
**Fix Applied**: what code change resolved it
**Files Modified**: list every file touched
**Prevention**: rule to follow to never hit this class of error again
```

---

## Known Gotchas (Pre-populated)

### Gotcha #1 - Twilio Duplicate Messages
**Problem**: If your Flask webhook returns a 500, Twilio retries the request,
causing the bot to send duplicate messages.
**Rule**: ALWAYS return HTTP 200 from the webhook, even on internal errors.
Catch all exceptions inside the handler and return empty TwiML on failure.

### Gotcha #2 - APScheduler + Flask in same process
**Problem**: APScheduler's BackgroundScheduler conflicts with Flask's reloader in debug mode.
**Rule**: NEVER run Flask with debug=True in production. Set debug=False.
In development, set use_reloader=False if you need debug mode.

### Gotcha #3 - Upstash Redis REST client vs redis-py
**Problem**: Upstash free tier uses a REST API, not a raw TCP Redis connection.
Standard redis-py will fail to connect.
**Rule**: Use the `upstash-redis` Python package, NOT `redis-py`.
Install: `pip install upstash-redis`
Import: `from upstash_redis import Redis`
Init: `Redis(url=os.getenv("UPSTASH_REDIS_REST_URL"), token=os.getenv("UPSTASH_REDIS_REST_TOKEN"))`

### Gotcha #4 - Google Service Account JSON in env var
**Problem**: Storing the full service account JSON as an env var causes issues
with newlines in the private key when Railway injects it.
**Rule**: Base64-encode the JSON before storing, decode at runtime:
```python
import base64, json, os
sa_json = json.loads(base64.b64decode(os.getenv("GOOGLE_SERVICE_ACCOUNT_B64")))
```
Store it as: `base64 -w 0 service_account.json` output.

### Gotcha #5 - Groq rate limits on free tier
**Problem**: Groq free tier has per-minute token limits. Rapid-fire ghost messages
can hit rate limits.
**Rule**: Add a minimum 3-second sleep between consecutive Groq calls.
Implement exponential backoff: 3s, 6s, 12s on retries.

### Gotcha #6 - Twilio WhatsApp sandbox 24hr window
**Problem**: Twilio sandbox requires the user to have messaged the bot within
the last 24 hours before the bot can send outbound messages.
**Rule**: This is a sandbox-only limitation. For production, apply for a
WhatsApp Business API number. For testing, text the bot daily to reset the window.
If a scheduled message fails with error 63016, log it and skip (don't retry loop).

### Gotcha #7 - APScheduler jobs firing on every dyno
**Problem**: If Railway scales to multiple instances, APScheduler fires on every
instance, sending duplicate messages.
**Rule**: Add a Redis lock before every scheduled send:
```python
lock = redis.set("scheduler_lock:morning", "1", ex=60, nx=True)
if not lock:
    return  # another instance already fired this
```

### Gotcha #8 - Timezone naive vs aware datetimes
**Problem**: Mixing naive and aware datetimes in schedule comparisons causes
TypeError or wrong time window checks.
**Rule**: ALWAYS use timezone-aware datetimes throughout the codebase.
Use `from datetime import datetime` + `pytz.timezone("America/Chicago")`.
Never use `datetime.now()` - always use `datetime.now(tz)`.

### Gotcha #9 - Redis list vs string for chat history
**Problem**: Using Redis LPUSH/LRANGE for chat history causes ordering issues
and makes trimming complex.
**Rule**: Store chat history as a single JSON string (GET/SET), not a Redis list.
Load, append, trim to last 50, save back. Simpler and avoids list direction confusion.

### Gotcha #10 - Groq model name changes
**Problem**: Groq deprecates and renames models. Hardcoded model names break silently
(API returns 404, bot stops responding).
**Rule**: Store model name in config.py as GROQ_MODEL constant.
Add a startup health check that pings Groq with a 1-token request and logs the result.

---

## Fix Log (Claude populates below this line)

<!-- Claude: add your fixes here as you work -->

## Fix #2 - 2026-03-22
**Error**: Bot responses were mechanical, scripted, and shallow — sounding like a therapy chatbot ("This resistance is telling us that we're touching on something real")
**Root Cause**: Single-pass prompts described CBT techniques to the LLM instead of giving it a character and voice. No observation step before responding. No quality gate. LLM pattern-matched "pushback = resistance script" without reading the actual moment.
**Fix Applied**: Full refactor of llm.py + all agent prompts:
  1. Two-pass system: Pass 1 (silent observer JSON) → Pass 2 (response from observation)
  2. 23 banned therapy phrases with auto-regenerate on detection
  3. Technique rotation tracking in Redis — never repeats same approach twice in a row
  4. Length enforcement: max 2 sentences, compress via separate Groq call if exceeded
  5. All scheduled prompts rewritten with human voice (short, direct, Hinglish allowed)
  6. Ghost messages: single impactful line, "bhai" style
**Files Modified**: llm.py, agents/mood_agent.py, agents/orchestrator.py, agents/ghost_agent.py
**Prevention**: Never tell the LLM to "use CBT techniques" — give it a character and let it respond naturally from that character. Always have an observation step before generating. Always enforce a quality gate for banned patterns and length.

## Fix #1 - 2026-03-22
**Error**: Google Docs integration removed from spec before first deploy
**Root Cause**: User does not need Google Docs; adds unnecessary complexity and credentials
**Fix Applied**: Replaced gdocs.py with a thin shim that reads Redis override or falls back to hardcoded MOTIVATION_DOC constant in llm.py. Removed google-api-python-client, google-auth from requirements.txt. Removed GOOGLE_SERVICE_ACCOUNT_B64 and GDOC_MOTIVATION_ID from .env and .env.example. Removed motivation:cache and motivation:cache_time from config.py REDIS_KEYS.
**Files Modified**: gdocs.py, llm.py, requirements.txt, .env, .env.example, config.py
**Prevention**: If Google Docs is not needed, don't add the dependency. The /update WhatsApp command + hardcoded MOTIVATION_DOC is a simpler, more reliable pattern.
