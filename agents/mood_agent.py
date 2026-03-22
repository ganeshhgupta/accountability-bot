# Agent: Mood | Role: Intent detection + two-pass response for all emotional states

"""Mood agent — detects intent; all responses go through the two-pass system."""

import logging
import os

import gdocs
import llm
import memory
from config import GROQ_MODEL, INTENT_PATTERNS

logger = logging.getLogger(__name__)


def detect_intent(message: str) -> str:
    """Classify message intent using pattern matching + LLM fallback.

    Returns one of: UPDATE_DOC, STUCK, LOW_MOOD, NEGATIVE_PUSH,
    COMPLETION_REPORT, PLAN_SUBMISSION, CASUAL
    """
    msg_lower = message.lower().strip()

    if msg_lower.startswith("/update"):
        return "UPDATE_DOC"

    matched = []
    for intent, patterns in INTENT_PATTERNS.items():
        if intent == "UPDATE_DOC":
            continue
        for pattern in patterns:
            if pattern in msg_lower:
                matched.append(intent)
                break

    if len(matched) == 1:
        return matched[0]

    if len(matched) > 1:
        # Explicit priority when multiple patterns fire
        for p in ["NEGATIVE_PUSH", "LOW_MOOD", "STUCK", "COMPLETION_REPORT", "PLAN_SUBMISSION"]:
            if p in matched:
                return p

    # LLM classification for short/ambiguous messages that pattern-match nothing
    if not matched:
        try:
            return _llm_classify(message)
        except Exception as e:
            logger.warning("LLM intent classification failed: %s", e)

    return "CASUAL"


def _llm_classify(message: str) -> str:
    """LLM fallback intent classifier."""
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    prompt = (
        f"Classify this WhatsApp message into ONE label.\n"
        f"Labels: STUCK, LOW_MOOD, NEGATIVE_PUSH, COMPLETION_REPORT, PLAN_SUBMISSION, CASUAL\n"
        f'Message: "{message}"\n'
        f"Reply with ONLY the label."
    )
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
        temperature=0.0,
    )
    result = resp.choices[0].message.content.strip().upper()
    valid = {"STUCK", "LOW_MOOD", "NEGATIVE_PUSH", "COMPLETION_REPORT", "PLAN_SUBMISSION", "CASUAL"}
    return result if result in valid else "CASUAL"


# ---------------------------------------------------------------------------
# All handlers use the two-pass system
# ---------------------------------------------------------------------------

def handle_stuck(message: str) -> str:
    """User is stuck — two-pass with context hint."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    tasks = _get_tasks()
    return llm.generate_two_pass(
        user_message=message,
        history=history,
        motivation_doc=doc,
        tasks=tasks,
        trigger_type="stuck",
        context_hint="user says they're stuck on something",
    )


def handle_low_mood(message: str) -> str:
    """User doesn't feel like working — two-pass."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    tasks = _get_tasks()
    return llm.generate_two_pass(
        user_message=message,
        history=history,
        motivation_doc=doc,
        tasks=tasks,
        trigger_type="low_mood",
        context_hint="user doesn't feel like working — ask why before pushing",
    )


def handle_negative_push(message: str) -> str:
    """User pushing back or asking to stop — two-pass, never comply."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    tasks = _get_tasks()
    return llm.generate_two_pass(
        user_message=message,
        history=history,
        motivation_doc=doc,
        tasks=tasks,
        trigger_type="negative_push",
        context_hint=(
            "user is pushing back or asking to stop. "
            "Do NOT comply or apologize. "
            "Acknowledge briefly then redirect — like a friend who isn't playing along."
        ),
    )


def handle_completion(message: str) -> str:
    """User completed a task — mark it, then respond + next task."""
    from agents import task_agent
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()

    completed = task_agent.mark_most_recent_task_complete()
    task_name = completed["task"] if completed else "that"

    tasks_remaining = task_agent.get_pending_tasks()
    context = f"user just finished: '{task_name}'."
    if tasks_remaining:
        next_task = tasks_remaining[0]["task"]
        context += f" Next pending task is: '{next_task}'."
    else:
        context += " All tasks are done for today."

    response = llm.generate_two_pass(
        user_message=message,
        history=history,
        motivation_doc=doc,
        tasks=tasks_remaining,
        trigger_type="completion",
        context_hint=context,
    )
    return response


def _get_tasks() -> list:
    try:
        from agents import task_agent
        return task_agent.get_pending_tasks()
    except Exception:
        return []
