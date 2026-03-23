# Agent: Orchestrator | Role: Entry point — routes special commands, runs pipeline for everything else

"""Orchestrator — called by Flask webhook for every incoming message."""

import logging
import os
import threading

import gdocs
import memory
from agents import ghost_agent, task_agent
from agents.pipeline import run_pipeline, run_reflector

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
    """Master entry point. Called by Flask webhook."""
    my_number = os.getenv("MY_WHATSAPP_NUMBER", "")
    if from_number != my_number:
        logger.warning("Ignored message from unknown number: %s", from_number)
        return ""

    logger.info("Incoming | msg=%s", message[:80])

    # Save message + reset ghost tracking
    memory.save_message("user", message)
    memory.save_last_user_message_time()
    ghost_agent.reset_ghost_level()

    # /update command — bypass pipeline
    if message.lower().strip().startswith("/update"):
        response = _handle_update_command(message)
        memory.save_message("assistant", response)
        return response

    # Load shared context
    doc = gdocs.load_motivation_doc()
    history = memory.get_chat_history()

    # Special routing: plan submission — parse tasks first, then pipeline
    context_hint = ""
    msg_lower = message.lower()
    if any(p in msg_lower for p in ["my plan", "today i will", "planning to",
                                     "tasks for today", "going to", "will do", "my tasks"]):
        from llm import generate_task_list_from_message
        tasks = generate_task_list_from_message(message)
        if tasks:
            task_agent.save_daily_plan(tasks)
            context_hint = (
                f"user just submitted their plan: {', '.join(tasks)}. "
                f"Confirm you have it briefly, then push to start the first task by name."
            )

    # Special routing: completion — mark task first, then pipeline
    elif any(p in msg_lower for p in ["done", "finished", "completed", "did it",
                                       "wrapped up", "checked off"]):
        completed = task_agent.mark_most_recent_task_complete()
        if completed:
            remaining = task_agent.get_pending_tasks()
            context_hint = f"user just finished: '{completed['task']}'."
            if remaining:
                context_hint += f" Next task is: '{remaining[0]['task']}'."
            else:
                context_hint += " All tasks done for today."

    # Run the 5-agent pipeline
    try:
        response = run_pipeline(
            user_message=message,
            history=history,
            coaching_doc=doc,
            context_hint=context_hint,
        )
    except Exception as e:
        logger.error("Pipeline error: %s", e, exc_info=True)
        response = "something broke on my end"

    # Strategic silence — don't send anything, ghost agent handles re-approach
    if response == "SILENCE":
        logger.info("Strategic silence chosen — not replying")
        return ""

    if response:
        memory.save_message("assistant", response)
        logger.info("Outbound | chars=%d | response=%r", len(response), response[:60])

    # Run reflector every 10 user turns (background, non-blocking)
    user_turns = sum(1 for m in memory.get_chat_history() if m.get("role") == "user")
    if user_turns > 0 and user_turns % 10 == 0:
        threading.Thread(
            target=run_reflector,
            args=(memory.get_chat_history(), doc),
            daemon=True,
        ).start()
        logger.info("Reflector triggered (turn %d)", user_turns)

    return response
