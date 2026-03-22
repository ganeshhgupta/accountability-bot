"""APScheduler setup — all scheduled jobs with Redis lock + schedule window guards.

Implements FIXES.md Gotcha #7 (Redis lock per job) and Gotcha #8 (timezone-aware).
"""

import logging
import os

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

import gdocs
import llm
import memory
from agents.schedule_agent import is_active_now
from agents import ghost_agent, task_agent
from config import TIMEZONE, WEEKDAY_JOBS, SATURDAY_JOBS

logger = logging.getLogger(__name__)

_tz = pytz.timezone(TIMEZONE)


def _send_whatsapp(message: str, trigger_type: str) -> None:
    """Send a WhatsApp message via Twilio and persist to history."""
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM", "")
    to_number = os.getenv("MY_WHATSAPP_NUMBER", "")

    try:
        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_number, to=to_number)
        memory.save_message("assistant", message)
        logger.info("Sent | trigger=%s | chars=%d", trigger_type, len(message))
    except TwilioRestException as e:
        # Error 63016 = 24hr sandbox window expired — log and skip, don't retry
        logger.error("Twilio send failed | trigger=%s | code=%s | %s",
                     trigger_type, getattr(e, "code", "?"), e)
    except Exception as e:
        logger.error("Unexpected send error | trigger=%s | %s", trigger_type, e)


def _job(trigger_type: str) -> None:
    """Generic job wrapper: acquire lock -> check window -> generate -> send."""
    if not memory.acquire_scheduler_lock(trigger_type, ttl_seconds=55):
        logger.info("Lock held by another instance — skipping %s", trigger_type)
        return
    if not is_active_now():
        logger.info("Outside window — skipping %s", trigger_type)
        return

    doc = gdocs.load_motivation_doc()
    tasks = task_agent.get_pending_tasks()

    prompt_map = {
        "morning":              lambda: llm.get_morning_prompt(doc),
        "procrastination_check": lambda: llm.get_procrastination_check_prompt(doc, tasks),
        "midday":               lambda: llm.get_midday_prompt(doc, tasks),
        "afternoon_nudge":      lambda: llm.get_afternoon_nudge_prompt(doc),
        "evening":              lambda: llm.get_evening_prompt(doc, tasks),
        "winddown":             lambda: llm.get_winddown_prompt(doc),
        "final":                lambda: llm.get_final_prompt(doc, tasks),
        "weekend_checkin":      lambda: llm.get_weekend_checkin_prompt(doc),
        "saturday_winddown":    lambda: llm.get_saturday_winddown_prompt(doc),
    }

    prompt_fn = prompt_map.get(trigger_type)
    if prompt_fn is None:
        logger.warning("Unknown trigger_type: %s", trigger_type)
        return

    message = llm.generate_response(prompt_fn(), trigger_type=trigger_type)
    _send_whatsapp(message, trigger_type)


def _ghost_check_job() -> None:
    """Ghost escalation — runs every 15 min during active hours."""
    if not memory.acquire_scheduler_lock("ghost_check", ttl_seconds=55):
        return
    message = ghost_agent.escalate_if_needed()
    if message:
        _send_whatsapp(message, trigger_type="ghost_escalation")


def create_scheduler() -> BackgroundScheduler:
    """Build and return a configured BackgroundScheduler (not yet started)."""
    scheduler = BackgroundScheduler(timezone=_tz)

    # Mon-Fri jobs (days_of_week='0-4' = Mon-Fri in APScheduler)
    for hour, minute, trigger_type in WEEKDAY_JOBS:
        scheduler.add_job(
            _job,
            trigger="cron",
            day_of_week="0-4",
            hour=hour,
            minute=minute,
            timezone=_tz,
            args=[trigger_type],
            id=f"weekday_{trigger_type}",
            replace_existing=True,
        )

    # Saturday jobs
    for hour, minute, trigger_type in SATURDAY_JOBS:
        scheduler.add_job(
            _job,
            trigger="cron",
            day_of_week="5",
            hour=hour,
            minute=minute,
            timezone=_tz,
            args=[trigger_type],
            id=f"saturday_{trigger_type}",
            replace_existing=True,
        )

    # Ghost check every 15 minutes
    scheduler.add_job(
        _ghost_check_job,
        trigger="interval",
        minutes=15,
        id="ghost_check",
        replace_existing=True,
    )

    return scheduler
