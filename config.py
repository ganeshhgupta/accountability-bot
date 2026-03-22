"""All constants, schedule windows, intent patterns, and configuration."""

GROQ_MODEL = "llama-3.3-70b-versatile"

TIMEZONE = "America/Chicago"

MAX_HISTORY = 50

# Ghost escalation thresholds in minutes
GHOST_THRESHOLDS = {1: 45, 2: 90, 3: 120}

# Schedule windows per weekday (0=Monday ... 6=Sunday), Central Time
SCHEDULE_WINDOWS = {
    0: {"active": True,  "start": "09:00", "end": "23:59"},  # Monday
    1: {"active": True,  "start": "09:00", "end": "23:59"},  # Tuesday
    2: {"active": True,  "start": "09:00", "end": "23:59"},  # Wednesday
    3: {"active": True,  "start": "09:00", "end": "23:59"},  # Thursday
    4: {"active": True,  "start": "09:00", "end": "23:59"},  # Friday
    5: {"active": True,  "start": "18:00", "end": "23:00"},  # Saturday
    6: {"active": False, "start": None,    "end": None},     # Sunday OFF
}

# Scheduled message times as (hour, minute) tuples — Mon-Fri
WEEKDAY_JOBS = [
    (9,  0,  "morning"),
    (10, 30, "procrastination_check"),
    (12, 30, "midday"),
    (15, 30, "afternoon_nudge"),
    (18, 0,  "evening"),
    (21, 0,  "winddown"),
    (23, 30, "final"),
]

# Scheduled message times — Saturday only
SATURDAY_JOBS = [
    (18, 30, "weekend_checkin"),
    (21, 0,  "saturday_winddown"),
]

# Redis key names
REDIS_KEYS = {
    "chat_history":        "chat_history",
    "tasks":               "tasks:{date}",
    "last_response_time":  "last_response_time",
    "ghost_level":         "ghost_level",
    "motivation_override": "motivation:override",
    "day_state":           "day_state",
}

INTENT_PATTERNS = {
    "STUCK": [
        "stuck", "can't figure", "dont know how", "don't know how",
        "blocked", "confused", "lost",
    ],
    "LOW_MOOD": [
        "don't feel like", "dont feel like", "not feeling it", "tired",
        "exhausted", "lazy", "unmotivated", "what's the point",
        "whats the point", "pointless", "why bother",
    ],
    "NEGATIVE_PUSH": [
        "stop texting", "leave me alone", "stop it", "shut up",
        "go away", "i don't care", "i dont care", "whatever", "not now",
    ],
    "COMPLETION_REPORT": [
        "done", "finished", "completed", "did it", "wrapped up", "checked off",
    ],
    "PLAN_SUBMISSION": [
        "my plan", "today i will", "planning to", "tasks for today",
        "going to", "will do", "my tasks",
    ],
    "UPDATE_DOC": ["/update"],
}
