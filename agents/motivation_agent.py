# Agent: Motivation | Role: Fetch and expose motivation doc content

"""Motivation agent — thin wrapper around gdocs.load_motivation_doc().

Provides a single surface for all agents to request motivation context.
"""

import gdocs


def get_motivation_context() -> str:
    """Return current motivation doc text (override > fresh fetch > cache > fallback)."""
    return gdocs.load_motivation_doc()
