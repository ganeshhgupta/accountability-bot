# Agent: Task | Role: Manage daily task list, track completion, send ordered pings

"""Task agent — parses plans, tracks tasks, pings for completion."""

import logging
from datetime import datetime, timezone, timedelta

import pytz

from config import TIMEZONE
import memory
import llm

logger = logging.getLogger(__name__)

_tz = pytz.timezone(TIMEZONE)


def _today() -> str:
    """Return today's date string in YYYY-MM-DD (Central Time)."""
    return datetime.now(_tz).strftime("%Y-%m-%d")


def parse_plan_from_message(message: str) -> list[str]:
    """Use Groq to extract an ordered list of tasks from a natural-language message.

    Returns a list of task strings.
    """
    tasks = llm.generate_task_list_from_message(message)
    if not tasks:
        # Fallback: treat each sentence-like segment as a task
        import re
        parts = re.split(r"[,\n;]+", message)
        tasks = [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]
    return tasks


def save_daily_plan(tasks: list[str]) -> None:
    """Persist today's task list to Redis.

    Stored as list of {task, status, order, pinged_at}.
    """
    date = _today()
    task_dicts = [
        {"task": t, "status": "pending", "order": i, "pinged_at": None}
        for i, t in enumerate(tasks)
    ]
    memory.save_tasks(date, task_dicts)
    # Update day state
    state = memory.get_day_state()
    state["plan_received"] = True
    state["date"] = date
    memory.set_day_state(state)
    logger.info("Saved %d tasks for %s", len(tasks), date)


def get_pending_tasks() -> list[dict]:
    """Return all tasks with status 'pending' for today."""
    tasks = memory.get_tasks(_today())
    return [t for t in tasks if t.get("status") == "pending"]


def mark_task_complete(task_index: int) -> None:
    """Mark a task complete by its order index."""
    date = _today()
    tasks = memory.get_tasks(date)
    for t in tasks:
        if t.get("order") == task_index:
            t["status"] = "complete"
            break
    memory.save_tasks(date, tasks)


def get_next_pending_task() -> dict | None:
    """Return the first pending task (lowest order), or None."""
    pending = get_pending_tasks()
    if not pending:
        return None
    return min(pending, key=lambda t: t.get("order", 0))


def ping_next_task() -> str | None:
    """Generate a ping message for the next pending task.

    Returns the message string, or None if all tasks done or no plan set.
    """
    next_task = get_next_pending_task()
    if next_task is None:
        return None

    date = _today()
    all_tasks = memory.get_tasks(date)
    total = len(all_tasks)
    task_num = next_task.get("order", 0) + 1

    # Record ping time
    for t in all_tasks:
        if t.get("order") == next_task.get("order"):
            t["pinged_at"] = datetime.now(timezone.utc).isoformat()
            break
    memory.save_tasks(date, all_tasks)

    prompt = llm.get_task_ping_prompt(next_task["task"], task_num, total)
    return llm.generate_response(prompt, trigger_type="task_ping")


def check_overdue_tasks() -> list[dict]:
    """Return tasks that were pinged more than 90 minutes ago with no completion."""
    tasks = memory.get_tasks(_today())
    overdue = []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=90)
    for t in tasks:
        if t.get("status") != "pending":
            continue
        pinged_at = t.get("pinged_at")
        if pinged_at is None:
            continue
        ping_time = datetime.fromisoformat(pinged_at)
        if ping_time.tzinfo is None:
            ping_time = ping_time.replace(tzinfo=timezone.utc)
        if ping_time < cutoff:
            overdue.append(t)
    return overdue


def mark_most_recent_task_complete() -> dict | None:
    """Mark the last pinged/pending task as complete. Returns the task or None."""
    next_task = get_next_pending_task()
    if next_task is None:
        return None
    mark_task_complete(next_task.get("order", 0))
    return next_task
