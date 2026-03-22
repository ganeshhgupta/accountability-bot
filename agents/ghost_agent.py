# Agent: Ghost | Role: Escalate when user goes silent — short, direct, human

"""Ghost agent — tracks silence and escalates. Keeps messages terse."""

import logging
from datetime import datetime, timezone

import gdocs
import llm
import memory
from agents.schedule_agent import is_active_now
from config import GHOST_THRESHOLDS

logger = logging.getLogger(__name__)


def _minutes_silent() -> int | None:
    last = memory.get_last_response_time()
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - last).total_seconds() // 60)


def check_ghost_status() -> int:
    minutes = _minutes_silent()
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
    """Called every 15 min by scheduler. Returns message to send or None."""
    if not is_active_now():
        return None

    minutes = _minutes_silent()
    if minutes is None:
        return None

    current = check_ghost_status()
    stored = memory.get_ghost_level()
    doc = gdocs.load_motivation_doc()

    if current == 0:
        if stored != 0:
            memory.set_ghost_level(0)
        return None

    if current == 1 and stored < 1:
        memory.set_ghost_level(1)
        prompt = llm.get_ghost_level1_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_1")
        logger.info("Ghost L1 | %d min silent", minutes)
        return msg

    if current == 2 and stored < 2:
        memory.set_ghost_level(2)
        prompt = llm.get_ghost_level2_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_2")
        logger.info("Ghost L2 | %d min silent", minutes)
        return msg

    if current == 3:
        memory.set_ghost_level(3)
        prompt = llm.get_ghost_level3_prompt(doc, minutes)
        msg = llm.generate_response(prompt, trigger_type="ghost_3")
        logger.info("Ghost L3 | %d min silent", minutes)
        return msg

    return None


def reset_ghost_level() -> None:
    memory.set_ghost_level(0)
    memory.set_last_response_time()
