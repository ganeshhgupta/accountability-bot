# Agent: Mood | Role: Intent detection, emotional handling, CBT responses

"""Mood agent — detects intent and handles emotional/behavioral states."""

import logging

import llm
import memory
import gdocs
from config import INTENT_PATTERNS

logger = logging.getLogger(__name__)


def detect_intent(message: str) -> str:
    """Classify message intent.

    First tries pattern matching; falls back to LLM classification if ambiguous.
    Returns one of the INTENT_PATTERNS keys or 'CASUAL'.
    """
    msg_lower = message.lower()

    # Check UPDATE_DOC first (exact prefix)
    if msg_lower.startswith("/update"):
        return "UPDATE_DOC"

    # Pattern matching
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
        # Priority order for ambiguous matches
        priority = [
            "NEGATIVE_PUSH", "LOW_MOOD", "STUCK",
            "COMPLETION_REPORT", "PLAN_SUBMISSION",
        ]
        for p in priority:
            if p in matched:
                return p

    # LLM fallback for ambiguous or no match
    if not matched:
        try:
            intent = _llm_classify_intent(message)
            if intent:
                return intent
        except Exception as e:
            logger.warning("LLM intent classification failed: %s", e)

    return "CASUAL"


def _llm_classify_intent(message: str) -> str:
    """Use Groq to classify intent for ambiguous messages."""
    import groq as groq_lib
    import os
    from config import GROQ_MODEL

    client_obj = groq_lib.Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    prompt = f"""Classify the following WhatsApp message into ONE of these intents:
STUCK, LOW_MOOD, NEGATIVE_PUSH, COMPLETION_REPORT, PLAN_SUBMISSION, CASUAL

Message: "{message}"

Respond with ONLY the intent label, nothing else."""

    response = client_obj.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
        temperature=0.0,
    )
    result = response.choices[0].message.content.strip().upper()
    valid = {"STUCK", "LOW_MOOD", "NEGATIVE_PUSH", "COMPLETION_REPORT", "PLAN_SUBMISSION", "CASUAL"}
    return result if result in valid else "CASUAL"


def handle_stuck(message: str) -> str:
    """Handle 'I'm stuck' messages with CBT micro-step approach."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    prompt = llm.get_stuck_response_prompt(doc, message)
    # Inject history context into base prompt
    prompt = _inject_history(prompt, history)
    return llm.generate_response(prompt, trigger_type="stuck")


def handle_low_mood(message: str) -> str:
    """Handle low motivation messages with empathy-first + behavioral activation."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    prompt = llm.get_low_mood_response_prompt(doc, message)
    prompt = _inject_history(prompt, history)
    return llm.generate_response(prompt, trigger_type="low_mood")


def handle_negative_push(message: str) -> str:
    """Handle 'stop' / negative messages — acknowledge but NEVER comply."""
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    prompt = llm.get_negative_push_response_prompt(doc, message)
    prompt = _inject_history(prompt, history)
    return llm.generate_response(prompt, trigger_type="negative_push")


def handle_completion(message: str) -> str:
    """Mark the current task complete and return acknowledgment + next step."""
    from agents import task_agent
    doc = gdocs.load_motivation_doc()
    completed_task = task_agent.mark_most_recent_task_complete()
    task_name = completed_task["task"] if completed_task else "that task"
    prompt = llm.get_completion_response_prompt(doc, task_name)
    response = llm.generate_response(prompt, trigger_type="completion")

    # Append next task ping if available
    next_ping = task_agent.ping_next_task()
    if next_ping:
        response = f"{response}\n\n{next_ping}"

    return response


def _inject_history(prompt: str, history: list) -> str:
    """Replace history placeholder in prompt with actual recent messages."""
    last_msgs = history[-3:] if history else []
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in last_msgs
    ) or "No prior messages."
    return prompt.replace("No prior messages.", history_text)
