"""Banned phrases — any response containing these gets rejected and regenerated."""

BANNED_PHRASES = [
    "i hear you",
    "that resistance",
    "touching on something",
    "it sounds like",
    "i understand that",
    "this tells us",
    "sitting with",
    "that's completely valid",
    "i can see that",
    "what you're feeling",
    "it's okay to",
    "be gentle with yourself",
    "you've got this",
    "proud of you",
    "it seems like",
    "i know you're",
    "what's really going on",
    "what's actually going on",
    "don't give me that",
    "indeed",
    "journey",
    "safe space",
    "processing",
    "that's not an answer",
    "i can tell",
    "i can hear",
    "i sense that",
    "that's valid",
    "completely understandable",
    "acknowledge",
    "resistance is",
    "something real",
    "you're not telling me",
]


def contains_banned(text: str) -> tuple[bool, str]:
    """Return (True, phrase) if banned phrase found, else (False, '')."""
    low = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in low:
            return True, phrase
    return False, ""
