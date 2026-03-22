# Agent: Orchestrator | Role: Master router — classifies intent and delegates to sub-agents

"""Orchestrator — entry point for every incoming WhatsApp message."""

import logging
import os

import gdocs
import llm
import memory
from agents import ghost_agent, mood_agent, task_agent
from config import INTENT_PATTERNS

logger = logging.getLogger(__name__)


def _handle_update_command(message: str) -> str:
    """Process /update command — override or clear motivation doc."""
    payload = message[len("/update"):].strip()
    if payload.lower() == "clear":
        memory.clear_motivation_override()
        return "Got it. Cleared the override. I'll pull from your Google Doc going forward."
    if payload:
        memory.set_motivation_override(payload)
        return "Got it. I've updated your context. I'll use this going forward."
    return "Usage: /update [new content] or /update clear"


def handle_incoming(message: str, from_number: str) -> str:
    """Master router called by the Flask webhook.

    1. Validates from_number == MY_WHATSAPP_NUMBER
    2. Saves message to history
    3. Updates last_response_time, resets ghost level
    4. Detects intent
    5. Routes to correct handler
    6. Saves response to history
    7. Returns response string
    """
    my_number = os.getenv("MY_WHATSAPP_NUMBER", "")
    if from_number != my_number:
        logger.warning("Ignored message from unknown number: %s", from_number)
        return ""

    logger.info("Incoming | from=%s | intent_pending | msg=%s", from_number, message[:80])

    # Persist incoming message and reset ghost tracking
    memory.save_message("user", message)
    ghost_agent.reset_ghost_level()

    # Detect intent
    intent = mood_agent.detect_intent(message)
    logger.info("Intent detected: %s", intent)

    # Route
    try:
        response = _route(intent, message)
    except Exception as e:
        logger.error("Routing error for intent=%s: %s", intent, e)
        response = "Something went wrong on my end. Keep going — I'll be back."

    if response:
        memory.save_message("assistant", response)
        logger.info("Outbound | trigger=incoming_response | intent=%s | chars=%d",
                    intent, len(response))

    return response


def _route(intent: str, message: str) -> str:
    """Dispatch to the correct handler based on intent."""
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
            task_list_str = ", ".join(tasks)
            doc = gdocs.load_motivation_doc()
            prompt = (
                f"{llm.get_base_system_prompt(doc, memory.get_chat_history())}\n\n"
                f"Albert just submitted his plan for the day: {task_list_str}\n"
                "Acknowledge it briefly (1 sentence), confirm you have it, "
                "then push him to start immediately. Reference his first task."
            )
            return llm.generate_response(prompt, trigger_type="plan_received")
        return "Got it — but I couldn't parse any tasks. Can you list them one per line?"

    if intent == "COMPLETION_REPORT":
        return mood_agent.handle_completion(message)

    # CASUAL / TASK_REPORT / GHOST_BREAK / default
    doc = gdocs.load_motivation_doc()
    tasks_today = task_agent.get_pending_tasks()
    prompt = llm.get_casual_response_prompt(doc, tasks_today)
    return llm.generate_response(prompt, trigger_type="casual")
