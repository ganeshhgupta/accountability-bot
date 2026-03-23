"""Upstash Redis wrapper for all bot state.

Uses upstash-redis REST client (NOT redis-py) per FIXES.md Gotcha #3.
All ops wrapped in try/except with in-memory fallback.
Chat history stored as single JSON string per FIXES.md Gotcha #9.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from upstash_redis import Redis

from config import MAX_HISTORY, REDIS_KEYS

load_dotenv()
logger = logging.getLogger(__name__)

# In-memory fallback store used when Redis is unavailable
_fallback: dict = {}


def _get_redis() -> Redis:
    return Redis(
        url=os.getenv("UPSTASH_REDIS_REST_URL", ""),
        token=os.getenv("UPSTASH_REDIS_REST_TOKEN", ""),
    )


# ---------------------------------------------------------------------------
# Chat history
# ---------------------------------------------------------------------------

def get_chat_history() -> list[dict]:
    """Return the last MAX_HISTORY messages as a list of dicts."""
    try:
        r = _get_redis()
        raw = r.get(REDIS_KEYS["chat_history"])
        if raw is None:
            return []
        return json.loads(raw)
    except Exception as e:
        logger.warning("Redis get_chat_history failed: %s", e)
        return json.loads(_fallback.get(REDIS_KEYS["chat_history"], "[]"))


def save_message(role: str, content: str) -> None:
    """Append a message to history, trimming to MAX_HISTORY."""
    try:
        history = get_chat_history()
        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        history = history[-MAX_HISTORY:]
        serialised = json.dumps(history)
        r = _get_redis()
        r.set(REDIS_KEYS["chat_history"], serialised)
        _fallback[REDIS_KEYS["chat_history"]] = serialised
    except Exception as e:
        logger.warning("Redis save_message failed: %s", e)
        history = json.loads(_fallback.get(REDIS_KEYS["chat_history"], "[]"))
        history.append({"role": role, "content": content,
                         "timestamp": datetime.now(timezone.utc).isoformat()})
        history = history[-MAX_HISTORY:]
        _fallback[REDIS_KEYS["chat_history"]] = json.dumps(history)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def get_tasks(date: str) -> list[dict]:
    """Return task list for a given date string (YYYY-MM-DD)."""
    key = REDIS_KEYS["tasks"].format(date=date)
    try:
        r = _get_redis()
        raw = r.get(key)
        if raw is None:
            return []
        return json.loads(raw)
    except Exception as e:
        logger.warning("Redis get_tasks failed: %s", e)
        return json.loads(_fallback.get(key, "[]"))


def save_tasks(date: str, tasks: list[dict]) -> None:
    """Persist task list for a given date."""
    key = REDIS_KEYS["tasks"].format(date=date)
    try:
        serialised = json.dumps(tasks)
        r = _get_redis()
        r.set(key, serialised)
        _fallback[key] = serialised
    except Exception as e:
        logger.warning("Redis save_tasks failed: %s", e)
        _fallback[key] = json.dumps(tasks)


# ---------------------------------------------------------------------------
# Ghost / response tracking
# ---------------------------------------------------------------------------

def get_last_response_time() -> Optional[datetime]:
    """Return the last time the user responded, or None."""
    try:
        r = _get_redis()
        raw = r.get(REDIS_KEYS["last_response_time"])
        if raw is None:
            return None
        return datetime.fromisoformat(raw)
    except Exception as e:
        logger.warning("Redis get_last_response_time failed: %s", e)
        raw = _fallback.get(REDIS_KEYS["last_response_time"])
        return datetime.fromisoformat(raw) if raw else None


def set_last_response_time() -> None:
    """Record current UTC time as the user's last response."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        r = _get_redis()
        r.set(REDIS_KEYS["last_response_time"], now_str)
        _fallback[REDIS_KEYS["last_response_time"]] = now_str
    except Exception as e:
        logger.warning("Redis set_last_response_time failed: %s", e)
        _fallback[REDIS_KEYS["last_response_time"]] = now_str


def get_ghost_level() -> int:
    """Return current ghost escalation level (0-3)."""
    try:
        r = _get_redis()
        val = r.get(REDIS_KEYS["ghost_level"])
        return int(val) if val is not None else 0
    except Exception as e:
        logger.warning("Redis get_ghost_level failed: %s", e)
        return int(_fallback.get(REDIS_KEYS["ghost_level"], 0))


def set_ghost_level(level: int) -> None:
    """Set ghost escalation level."""
    try:
        r = _get_redis()
        r.set(REDIS_KEYS["ghost_level"], str(level))
        _fallback[REDIS_KEYS["ghost_level"]] = level
    except Exception as e:
        logger.warning("Redis set_ghost_level failed: %s", e)
        _fallback[REDIS_KEYS["ghost_level"]] = level


# ---------------------------------------------------------------------------
# Motivation override
# ---------------------------------------------------------------------------

def get_motivation_override() -> Optional[str]:
    """Return user's /update override text, or None."""
    try:
        r = _get_redis()
        return r.get(REDIS_KEYS["motivation_override"])
    except Exception as e:
        logger.warning("Redis get_motivation_override failed: %s", e)
        return _fallback.get(REDIS_KEYS["motivation_override"])


def set_motivation_override(content: str) -> None:
    """Persist /update override content."""
    try:
        r = _get_redis()
        r.set(REDIS_KEYS["motivation_override"], content)
        _fallback[REDIS_KEYS["motivation_override"]] = content
    except Exception as e:
        logger.warning("Redis set_motivation_override failed: %s", e)
        _fallback[REDIS_KEYS["motivation_override"]] = content


def clear_motivation_override() -> None:
    """Remove /update override so Google Docs version is used."""
    try:
        r = _get_redis()
        r.delete(REDIS_KEYS["motivation_override"])
        _fallback.pop(REDIS_KEYS["motivation_override"], None)
    except Exception as e:
        logger.warning("Redis clear_motivation_override failed: %s", e)
        _fallback.pop(REDIS_KEYS["motivation_override"], None)


# ---------------------------------------------------------------------------
# Day state
# ---------------------------------------------------------------------------

def get_day_state() -> dict:
    """Return current day state dict."""
    try:
        r = _get_redis()
        raw = r.get(REDIS_KEYS["day_state"])
        if raw is None:
            return {"plan_received": False, "morning_done": False, "date": ""}
        return json.loads(raw)
    except Exception as e:
        logger.warning("Redis get_day_state failed: %s", e)
        raw = _fallback.get(REDIS_KEYS["day_state"])
        if raw:
            return json.loads(raw)
        return {"plan_received": False, "morning_done": False, "date": ""}


def set_day_state(state: dict) -> None:
    """Persist day state."""
    try:
        serialised = json.dumps(state)
        r = _get_redis()
        r.set(REDIS_KEYS["day_state"], serialised)
        _fallback[REDIS_KEYS["day_state"]] = serialised
    except Exception as e:
        logger.warning("Redis set_day_state failed: %s", e)
        _fallback[REDIS_KEYS["day_state"]] = json.dumps(state)


# ---------------------------------------------------------------------------
# Scheduler lock (FIXES.md Gotcha #7 — prevents duplicate sends on multi-dyno)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Question streak tracking
# ---------------------------------------------------------------------------

def get_question_streak() -> int:
    """How many consecutive bot questions have gone unanswered / bounced."""
    try:
        r = _get_redis()
        val = r.get("question_streak")
        return int(val) if val is not None else 0
    except Exception as e:
        logger.warning("Redis get_question_streak failed: %s", e)
        return int(_fallback.get("question_streak", 0))


def increment_question_streak() -> None:
    try:
        current = get_question_streak()
        r = _get_redis()
        r.set("question_streak", current + 1)
        _fallback["question_streak"] = current + 1
    except Exception as e:
        logger.warning("Redis increment_question_streak failed: %s", e)


def reset_question_streak() -> None:
    try:
        r = _get_redis()
        r.set("question_streak", 0)
        _fallback["question_streak"] = 0
    except Exception as e:
        logger.warning("Redis reset_question_streak failed: %s", e)


# ---------------------------------------------------------------------------
# Technique rotation tracking
# ---------------------------------------------------------------------------

def get_last_two_techniques() -> list:
    try:
        r = _get_redis()
        raw = r.get("last_techniques")
        return json.loads(raw) if raw else []
    except Exception as e:
        logger.warning("Redis get_last_two_techniques failed: %s", e)
        raw = _fallback.get("last_techniques")
        return json.loads(raw) if raw else []


def save_last_technique(technique: str) -> None:
    try:
        techniques = get_last_two_techniques()
        techniques.append(technique)
        techniques = techniques[-2:]
        serialised = json.dumps(techniques)
        r = _get_redis()
        r.set("last_techniques", serialised)
        _fallback["last_techniques"] = serialised
    except Exception as e:
        logger.warning("Redis save_last_technique failed: %s", e)


# ---------------------------------------------------------------------------
# Living psychological model
# ---------------------------------------------------------------------------

_DEFAULT_PSYCH_MODEL = {
    "current_stability": 5,
    "dominant_pattern_this_week": "none",
    "what_is_landing": [],
    "what_is_bouncing": [],
    "recent_wins_to_reference": [],
    "current_avoidance_target": "job applications",
    "anusha_mention_frequency": "stable",
    "work_momentum": "flat",
    "best_time_to_push": "morning",
    "current_register_preference": "mixed",
    "last_updated": None,
}


def get_psych_model() -> dict:
    try:
        r = _get_redis()
        raw = r.get("psych_model")
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning("Redis get_psych_model failed: %s", e)
        raw = _fallback.get("psych_model")
        if raw:
            return json.loads(raw)
    return dict(_DEFAULT_PSYCH_MODEL)


def save_psych_model(model: dict) -> None:
    try:
        serialised = json.dumps(model)
        r = _get_redis()
        r.set("psych_model", serialised)
        _fallback["psych_model"] = serialised
    except Exception as e:
        logger.warning("Redis save_psych_model failed: %s", e)
        _fallback["psych_model"] = json.dumps(model)


# ---------------------------------------------------------------------------
# User message time (for silence calculation in pipeline)
# ---------------------------------------------------------------------------

def save_last_user_message_time() -> None:
    """Record when the user last sent a message (separate from bot response time)."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        r = _get_redis()
        r.set("last_user_message_time", now_str)
        _fallback["last_user_message_time"] = now_str
    except Exception as e:
        logger.warning("Redis save_last_user_message_time failed: %s", e)
        _fallback["last_user_message_time"] = now_str


# ---------------------------------------------------------------------------
# Scheduler lock
# ---------------------------------------------------------------------------

def acquire_scheduler_lock(job_name: str, ttl_seconds: int = 60) -> bool:
    """Attempt to acquire a Redis lock for a scheduler job.

    Returns True if lock acquired (this instance should proceed),
    False if another instance already holds it.
    """
    key = f"scheduler_lock:{job_name}"
    try:
        r = _get_redis()
        # SET ... NX EX — atomic set-if-not-exists
        result = r.set(key, "1", nx=True, ex=ttl_seconds)
        return result is not None and result is not False
    except Exception as e:
        logger.warning("Redis acquire_scheduler_lock failed: %s", e)
        # Fallback: allow execution (single-process environments)
        return True
