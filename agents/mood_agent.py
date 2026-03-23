# Agent: Mood | Role: Intent detection only — response generation moved to pipeline

"""Mood agent — intent detection only. All response generation is in pipeline.py."""

import logging
import os

from config import GROQ_MODEL, INTENT_PATTERNS

logger = logging.getLogger(__name__)


def detect_intent(message: str) -> str:
    """Lightweight intent classifier for special command routing.

    Returns: UPDATE_DOC, PLAN_SUBMISSION, COMPLETION_REPORT, or CASUAL.
    The pipeline handles all nuanced response logic — this is only for
    routing commands that need pre-processing (parse tasks, mark complete).
    """
    msg_lower = message.lower().strip()

    if msg_lower.startswith("/update"):
        return "UPDATE_DOC"

    for intent in ["PLAN_SUBMISSION", "COMPLETION_REPORT"]:
        for pattern in INTENT_PATTERNS.get(intent, []):
            if pattern in msg_lower:
                return intent

    return "CASUAL"
