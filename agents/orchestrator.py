# Agent: Orchestrator | Role: Master router — classifies intent and delegates to sub-agents

"""Orchestrator — entry point for every incoming WhatsApp message."""

import logging
import os

import gdocs
import llm
import memory
from agents import ghost_agent, mood_agent, task_agent

logger = logging.getLogger(__name__)


def _handle_update_command(message: str) -> str:
    payload = message[len("/update"):].strip()
    if payload.lower() == "clear":
        memory.clear_motivation_override()
        return "done, back to the original doc"
    if payload:
        memory.set_motivation_override(payload)
        return "got it, updated"
    return "usage: /update [new content] or /update clear"


def handle_incoming(message: str, from_number: str) -> str:
    """Master router. Called by Flask webhook for every incoming message."""
    my_number = os.getenv("MY_WHATSAPP_NUMBER", "")
    if from_number != my_number:
        logger.warning("Ignored message from unknown number: %s", from_number)
        return ""

    logger.info("Incoming | msg=%s", message[:80])

    memory.save_message("user", message)
    ghost_agent.reset_ghost_level()

    intent = mood_agent.detect_intent(message)
    logger.info("Intent: %s", intent)

    try:
        response = _route(intent, message)
    except Exception as e:
        logger.error("Routing error | intent=%s | %s", intent, e)
        response = "something broke on my end, give me a sec"

    if response:
        memory.save_message("assistant", response)
        logger.info("Outbound | intent=%s | chars=%d", intent, len(response))

    return response


def _route(intent: str, message: str) -> str:
    if intent == "UPDATE_DOC":
        return _handle_update_command(message)

    if intent == "STUCK":
        return mood_agent.handle_stuck(message)

    if intent == "LOW_MOOD":
        return mood_agent.handle_low_mood(message)

    if intent == "NEGATIVE_PUSH":
        return mood_agent.handle_negative_push(message)

    if intent == "PLAN_SUBMISSION":
        tasks = task_agent.parse_plan_from_message(message)
        if tasks:
            task_agent.save_daily_plan(tasks)
            doc = gdocs.load_motivation_doc()
            history = memory.get_chat_history()
            tasks_pending = task_agent.get_pending_tasks()
            return llm.generate_two_pass(
                user_message=message,
                history=history,
                motivation_doc=doc,
                tasks=tasks_pending,
                trigger_type="plan_received",
                context_hint=f"user just submitted their plan: {', '.join(tasks)}. Confirm briefly and push to start the first task.",
            )
        return "couldn't parse the tasks — can you list them one per line?"

    if intent == "COMPLETION_REPORT":
        return mood_agent.handle_completion(message)

    # CASUAL / default — two-pass with no special context
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()
    tasks_today = task_agent.get_pending_tasks()
    return llm.generate_two_pass(
        user_message=message,
        history=history,
        motivation_doc=doc,
        tasks=tasks_today,
        trigger_type="casual",
    )
