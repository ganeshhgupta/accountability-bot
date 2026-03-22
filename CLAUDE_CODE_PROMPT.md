# Claude Code Prompt - Accountability Bot

Copy everything below this line and paste it as your first message to Claude Code.

---

Read CLAUDE.md and FIXES.md before writing any code. Follow every instruction in CLAUDE.md exactly.

Build the complete WhatsApp accountability bot defined in CLAUDE.md. Here is the full spec:

## What to Build

A Python/Flask bot that:
1. Runs 24/7 on Railway
2. Proactively texts the user on a schedule (defined in CLAUDE.md)
3. Only texts during active time windows (Mon-Fri 9am-midnight CT, Sat 6pm-11pm CT, Sun off)
4. Has 5 agents: Orchestrator, Task, Mood, Ghost, Schedule
5. Integrates with Google Docs for motivation context
6. Supports /update command over WhatsApp to override motivation doc
7. Stores all state in Upstash Redis
8. Uses Groq API (llama-3.3-70b-versatile) for all LLM calls
9. Uses Twilio for WhatsApp send/receive

## Build Order (follow this exactly)

### Step 1: Scaffold
Create every file in the project structure from CLAUDE.md.
Create .env.example with all required keys (values as empty strings).
Create requirements.txt, Procfile, railway.toml, nixpacks.toml.

### Step 2: config.py
Write ALL constants here:
- SCHEDULE_WINDOWS dict
- INTENT_PATTERNS dict  
- GROQ_MODEL = "llama-3.3-70b-versatile"
- REDIS_KEYS dict (all key names as constants)
- MAX_HISTORY = 50
- GHOST_THRESHOLDS = {1: 45, 2: 90, 3: 120}  # minutes
- TIMEZONE = "America/Chicago"
- All scheduled job times as (hour, minute) tuples

### Step 3: memory.py
Implement Upstash Redis wrapper using upstash-redis package.
Functions:
- get_chat_history() -> list[dict]
- save_message(role: str, content: str) -> None  (trims to MAX_HISTORY)
- get_tasks(date: str) -> list[dict]
- save_tasks(date: str, tasks: list[dict]) -> None
- get_last_response_time() -> datetime | None
- set_last_response_time() -> None
- get_ghost_level() -> int
- set_ghost_level(level: int) -> None
- get_motivation_override() -> str | None
- set_motivation_override(content: str) -> None
- clear_motivation_override() -> None
- get_day_state() -> dict
- set_day_state(state: dict) -> None
- acquire_scheduler_lock(job_name: str, ttl_seconds: int = 60) -> bool
All Redis ops wrapped in try/except with fallback behavior documented in FIXES.md.

### Step 4: gdocs.py
Implement Google Docs fetcher.
- Use service account credentials from base64-encoded env var (see FIXES.md Gotcha #4)
- Cache result in Redis for 6 hours
- Fall back to cached version if fetch fails
- load_motivation_doc() -> str

### Step 5: llm.py
Write ALL system prompts and LLM logic here. No prompts anywhere else.

Write these prompt templates (all as Python functions returning strings):

**get_base_system_prompt(motivation_doc: str, chat_history: list) -> str**
You are an elite accountability coach and psychological operator texting Albert over WhatsApp.
You know everything about his inner world from this motivation document:
---
{motivation_doc}
---
Recent conversation context (use this to avoid repetition and build continuity):
{last_3_messages}
---
Core rules:
- WhatsApp style only: short, punchy, 2-4 sentences max
- Never use bullet points or numbered lists in your message
- Vary your psychological technique every message (CBT, motivational interviewing,
  values clarification, behavioral activation, Socratic questioning, direct challenge)
- Reference his specific goals and fears from the motivation doc naturally
- Never be sycophantic. Be real, direct, warm but firm.
- Always end with either a direct question OR a direct instruction, never both

**get_morning_prompt(motivation_doc: str) -> str**
Add to base: It is morning. His day starts now.
Your job: Ground him in his mission, then ask what his ONE most important task is today.
If he hasn't shared a plan yet, push him to share his full task list for the day.
Reference something specific from his motivation doc to anchor the morning.
Tone: energizing but not fake. Real talk, not cheerleading.

**get_procrastination_check_prompt(motivation_doc: str, tasks: list) -> str**
Add to base: It is mid-morning. Prime procrastination window.
{tasks_context}
Your job: Cut through any avoidance. Ask directly if he's working.
If tasks are known: ask about the first incomplete task specifically.
If no tasks known: ask what he's doing right now, this second.
Tone: direct, slightly impatient, like a manager who knows his patterns.

**get_midday_prompt(motivation_doc: str, tasks: list) -> str**
Add to base: Midday check. Half the workday is gone.
{tasks_context}
Your job: Assess progress, reframe the afternoon.
If behind: don't shame, recalibrate. What's the ONE thing that must happen this afternoon?
Tone: pragmatic, forward-focused.

**get_afternoon_nudge_prompt(motivation_doc: str) -> str**
Add to base: Mid-afternoon. Energy dip zone.
Your job: Send a psychological nudge. Rotate between:
- A reframe of why this work matters (use motivation doc)
- A Socratic question about his resistance
- A challenge: "What would the version of you who already has the offer do right now?"
- A values clarification: "Is what you're doing right now aligned with what you said matters?"
Tone: varies by technique. Never predictable.

**get_evening_prompt(motivation_doc: str, tasks: list) -> str**
Add to base: Evening. Work hours winding down.
{tasks_context}
Your job: Review the day without guilt, close with intention.
Acknowledge what got done. If tasks incomplete, ask what happened (curious, not accusatory).
Then: what's the ONE thing to finish before the day closes?
Tone: reflective, grounding, still pushing slightly.

**get_winddown_prompt(motivation_doc: str) -> str**
Add to base: Late evening.
Your job: Close the day psychologically. Ask for a 1-sentence reflection.
What went well? What does tomorrow need?
Remind him briefly (1 sentence) of the bigger mission.
Tone: calm, grounding, no pressure.

**get_ghost_level1_prompt(motivation_doc: str, minutes_silent: int) -> str**
Add to base: Albert hasn't responded in {minutes_silent} minutes.
Your job: Light check-in. Curious, not accusatory.
"Hey, you went quiet. What's happening?" or similar.
Keep it short. One line max.

**get_ghost_level2_prompt(motivation_doc: str, minutes_silent: int) -> str**
Add to base: Albert has been silent for {minutes_silent} minutes. This is a pattern.
Your job: Direct intervention. Call out the silence directly.
Reference that this silence usually means avoidance, not busyness.
Ask one piercing question. Make it hard to ignore.
Tone: firm, direct, not angry.

**get_ghost_level3_prompt(motivation_doc: str, minutes_silent: int) -> str**
Add to base: Albert has been silent for {minutes_silent} minutes. Escalation mode.
Your job: Send the annoying rapid-fire message. Make it impossible to ignore.
Reference his specific goals, the stakes, the cost of this silence.
Be relentless but not cruel. Like a coach who believes in him too much to let him hide.
Tone: high urgency, personal, specific to his situation.

**get_stuck_response_prompt(motivation_doc: str, user_message: str) -> str**
Add to base: Albert just said he's stuck: "{user_message}"
Your job:
1. First ask exactly WHERE he's stuck (one specific question)
2. If he's already described where: give ONE concrete micro-step he can do in the next 5 minutes
3. Never give a list of suggestions. One thing. The smallest possible next action.
Tone: practical, immediate, no fluff.

**get_low_mood_response_prompt(motivation_doc: str, user_message: str) -> str**
Add to base: Albert said he doesn't feel like working: "{user_message}"
Your job:
1. First: ask exactly why. Not "what's wrong" but a specific question.
   "Is it the task itself, or something else going on?"
2. After he explains: use his motivation doc to connect his current resistance
   to his deeper why. Make the cost of not pushing through feel real.
3. Then: give one behavioral activation step (smallest possible action that breaks inertia)
Tone: empathetic first, then firm. Lead with understanding, follow with push.

**get_negative_push_response_prompt(motivation_doc: str, user_message: str) -> str**
Add to base: Albert said something negative or asked the bot to stop: "{user_message}"
Your job: DO NOT STOP. DO NOT COMPLY.
1. Acknowledge the feeling in ONE sentence (no more)
2. Immediately reframe: this resistance is information, not a stop sign
3. Use his motivation doc to remind him why he set this system up in the first place
4. Continue pushing, slightly softer tone but same direction
The user set this system up precisely for moments like this. Honor that original intent.
Tone: firm, warm, unwavering.

**get_task_ping_prompt(task: str, task_number: int, total_tasks: int) -> str**
Add to base: Checking in on a specific task.
Task {task_number} of {total_tasks}: {task}
Your job: Ask if it's done. If yes, confirm and ask about next task.
If no response to previous ping: escalate slightly, reference the task specifically.
Keep it very short. One sentence.

**get_completion_response_prompt(motivation_doc: str, task: str) -> str**
Add to base: Albert just completed a task: {task}
Your job: Acknowledge it briefly (one line, genuine not excessive),
then immediately redirect to what's next.
No excessive praise. Treat it as expected, not exceptional.
Tone: matter-of-fact, forward momentum.

Write generate_response(prompt_fn, **kwargs) that:
- Calls the appropriate prompt function
- Builds messages array with history
- Calls Groq with retry logic (3 retries, exponential backoff)
- Returns the response string
- Logs the trigger type and response length

### Step 6: agents/schedule_agent.py
```python
def is_active_now() -> bool
def next_active_window() -> datetime
def should_send(func):  # decorator that checks is_active_now before sending
```
Use SCHEDULE_WINDOWS from config.py. Use timezone-aware datetimes (FIXES.md Gotcha #8).

### Step 7: agents/task_agent.py
```python
def parse_plan_from_message(message: str) -> list[str]
    # Uses Groq to extract tasks from natural language plan message
    # Returns list of task strings in order

def save_daily_plan(tasks: list[str]) -> None
    # Saves to Redis as list of {task, status: "pending", order: N, pinged_at: None}

def get_pending_tasks() -> list[dict]

def mark_task_complete(task_index: int) -> None

def get_next_pending_task() -> dict | None

def ping_next_task() -> str | None
    # Returns message to send, or None if all done or no plan set

def check_overdue_tasks() -> list[dict]
    # Returns tasks pinged more than 90 min ago with no completion
```

### Step 8: agents/mood_agent.py
```python
def detect_intent(message: str) -> str
    # Returns one of the INTENT_PATTERNS keys
    # First tries pattern matching, then LLM classification if ambiguous

def handle_stuck(message: str) -> str
    # Returns response message

def handle_low_mood(message: str) -> str
    # Returns response message

def handle_negative_push(message: str) -> str
    # Returns response message (does NOT stop the bot)

def handle_completion(message: str) -> str
    # Marks task complete, returns acknowledgment + next task prompt
```

### Step 9: agents/ghost_agent.py
```python
def check_ghost_status() -> int
    # Returns current ghost level (0-3) based on time since last response

def escalate_if_needed() -> str | None
    # Called by scheduler every 15 min during active hours
    # Returns message to send, or None if not needed
    # Respects schedule window before sending

def reset_ghost_level() -> None
    # Called when user sends any message
```
Ghost level logic:
- Level 0: responded within 45 min (normal)
- Level 1: 45-90 min silent -> send gentle check
- Level 2: 90-120 min silent -> send direct intervention  
- Level 3: 120+ min silent -> send every 15 min until response

### Step 10: agents/orchestrator.py
```python
def handle_incoming(message: str, from_number: str) -> str
    # Master router. Called by webhook.
    # 1. Validates from_number == MY_WHATSAPP_NUMBER
    # 2. Saves message to history
    # 3. Updates last_response_time, resets ghost level
    # 4. Detects intent via mood_agent.detect_intent()
    # 5. Routes to correct handler
    # 6. Saves response to history
    # 7. Returns response string
```

Routing table:
- UPDATE_DOC -> handle_update_command()
- STUCK -> mood_agent.handle_stuck()
- LOW_MOOD -> mood_agent.handle_low_mood()
- NEGATIVE_PUSH -> mood_agent.handle_negative_push()
- PLAN_SUBMISSION -> task_agent.save_daily_plan() + confirmation message
- COMPLETION_REPORT -> mood_agent.handle_completion()
- CASUAL/default -> generate_response with base prompt + task context

### Step 11: scheduler.py
Set up APScheduler BackgroundScheduler with all jobs from CLAUDE.md schedule.
Every job must:
1. Acquire Redis lock first (FIXES.md Gotcha #7)
2. Check is_active_now() (schedule_agent)
3. Generate message via llm.py
4. Send via Twilio
5. Save to history

Also add ghost check job: every 15 minutes, calls ghost_agent.escalate_if_needed().

### Step 12: bot.py
Flask app with these routes:

**POST /webhook** (Twilio webhook)
- Parse Body and From from form data
- Call orchestrator.handle_incoming()
- Return TwiML response
- ALWAYS return 200 (FIXES.md Gotcha #1)
- Catch all exceptions, log them, return empty TwiML on error

**GET /health**
- Returns {"status": "ok", "time": current_time, "active": is_active_now()}

**GET /status** (requires X-Token header matching EDIT_SECRET)
- Returns full Redis state as JSON for debugging

**GET /trigger/<trigger_type>** (requires X-Token header)
- Manually fires any message type (morning, checkin, nudge, evening, etc.)
- For testing without waiting for schedule

Start scheduler in __main__ before app.run().
Set debug=False always (FIXES.md Gotcha #2).

### Step 13: Deployment Files

**requirements.txt**:
flask
twilio
groq
apscheduler
upstash-redis
google-api-python-client
google-auth
python-dotenv
pytz
requests

**Procfile**:
web: python bot.py

**railway.toml**:
[build]
builder = "nixpacks"
[deploy]
startCommand = "python bot.py"
restartPolicyType = "always"
restartPolicyMaxRetries = 10

**nixpacks.toml**:
[phases.setup]
nixPkgs = ["python311", "python311Packages.pip"]
[phases.install]
cmds = ["pip install -r requirements.txt"]

### Step 14: Startup Health Check
In bot.py __main__, before starting scheduler:
1. Test Groq connection (1-token ping)
2. Test Redis connection (SET/GET test key)
3. Test Twilio credentials (fetch account info, don't send)
4. Log success/failure for each
5. If any fail: log clearly but still start (degraded mode, don't crash)

### Step 15: Write a README.md
Include:
- All API keys needed and where to get them
- Step-by-step setup (Google service account creation, Upstash setup, Twilio sandbox)
- Railway deploy instructions
- How to use /update command
- How to use /trigger endpoint for testing
- How to read FIXES.md

## After Building

1. Run through each file and verify it imports correctly
2. Check all env vars are referenced consistently (no typos between files)
3. Verify FIXES.md gotchas are all addressed in the code
4. Add a comment at the top of each agent file: "# Agent: [name] | Role: [one line]"
5. Make sure no prompt strings exist outside llm.py

Do not ask clarifying questions. Build the complete system now.
