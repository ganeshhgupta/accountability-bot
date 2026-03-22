"""Motivation doc loader — no Google Docs integration.

Priority: Redis motivation:override (set via /update command) > hardcoded MOTIVATION_DOC in llm.py.
gdocs.py is kept as a thin shim so import paths across agents don't change.
"""

import logging

logger = logging.getLogger(__name__)


def load_motivation_doc() -> str:
    """Return motivation context string.

    Checks Redis for a /update override first; falls back to the hardcoded
    MOTIVATION_DOC constant in llm.py.
    """
    try:
        import memory
        override = memory.get_motivation_override()
        if override:
            return override
    except Exception as e:
        logger.warning("Could not check motivation override: %s", e)

    from llm import MOTIVATION_DOC
    return MOTIVATION_DOC
