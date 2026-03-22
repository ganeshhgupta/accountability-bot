# Agent: Ghost | Role: Escalate messaging frequency when user goes silent

"""Ghost agent — tracks silence and escalates outbound messaging frequency."""

import logging
from datetime import datetime, timezone

import gdocs
import llm
import memory
from agents.schedule_agent import is_active_now
from config import GHOST_THRESHOLDS

logger = logging.getLogger(__name__)


def _minutes_since_last_response() -> int | None:
    """Return minutes since user last responded, or None if no record."""
    last = memory.get_last_response_time()
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last
    return int(delta.total_seconds() // 60)


def check_ghost_status() -> int:
    """Return current ghost level (0-3) based on silence duration.

    Level 0: responded within 45 min (normal)
    Level 1: 45-90 min silent
    Level 2: 90-120 min silent
    Level 3: 120+ min silent
    """
    minutes = _minutes_since_last_response()
    if minutes is None:
        return 0

    if minutes >= GHOST_THRESHOLDS[3]:
        return 3
    if minutes >= GHOST_THRESHOLDS[2]:
        return 2
    if minutes >= GHOST_THRESHOLDS[1]:
        return 1
    return 0


def escalate_if_needed() -> str | None:
    """Determine whether to send a ghost escalation message.

    Called by the scheduler every 15 minutes during active hours.
    Returns the message string to send, or None if escalation is not needed.
    Respects schedule window via is_active_now().
    """
    if not is_active_now():
        return None

    minutes = _minutes_since_last_response()
    if minutes is None:
        return None

    current_level = check_ghost_status()
    stored_level = memory.get_ghost_level()

    doc = gdocs.load_motivation_doc()

    if current_level == 0:
        # User responded recently — reset
        if stored_level != 0:
            memory.set_ghost_level(0)
        return None

    if current_level == 1 and stored_level < 1:
        memory.set_ghost_level(1)
        prompt = llm.get_ghost_level1_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_level1")
        logger.info("Ghost level 1 triggered (%d min silent)", minutes)
        return msg

    if current_level == 2 and stored_level < 2:
        memory.set_ghost_level(2)
        prompt = llm.get_ghost_level2_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_level2")
        logger.info("Ghost level 2 triggered (%d min silent)", minutes)
        return msg

    if current_level == 3:
        # Level 3: fire every 15-min scheduler tick, don't gate on stored_level
        memory.set_ghost_level(3)
        prompt = llm.get_ghost_level3_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_level3")
        logger.info("Ghost level 3 triggered (%d min silent)", minutes)
        return msg

    return None


def reset_ghost_level() -> None:
    """Reset ghost level when user sends any message."""
    memory.set_ghost_level(0)
    memory.set_last_response_time()
    logger.info("Ghost level reset — user responded")
