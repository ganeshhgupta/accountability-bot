"""Society of Mind pipeline — 5 specialist agents argue before any message is sent.

Architecture based on:
- Minsky's Society of Mind: intelligence from specialist agents
- MultiAgentESC (EMNLP 2025): dialogue analysis → strategy → generation
- Emotional CoT: observe before responding
- MAD (Multi-Agent Debate): angel/devil stance before committing
- Implicature-aware prompting: what was MEANT not what was SAID

REFERENCE — what the pipeline should have produced for the real conversation:

"Hi"
  Agent1 → register: phatic, implied: "checking if this feels real"
  Agent3 → technique: phatic_mirror
  SENT: "hey"

"Tumko Hi mein frustration kahan se dikh gaya"
  Agent1 → register: pushing_back, maxim_violated: quality
  Agent2 → pattern: testing_the_bot
  Agent3 → technique: acknowledgment (own the mistake)
  SENT: "fair, I read too much into it"

"It's not like that"
  Agent1 → register: deflecting
  Agent3 → technique: phatic_mirror
  SENT: "okay"

"Bruh" (after two questions)
  Agent1 → one_word_dismissal: true, register: exasperation
  Agent3 → technique: strategic_silence (constraint: question_streak >= 1)
  SENT: [nothing]

"I can't focus" (after 28 min gap)
  Agent1 → silence_signal: reset, register: confessing
  Agent2 → pattern: genuine_work_block or room_spiral
  Agent3 → technique: micro_step
  SENT: "room mein hai? bahar jao pehle"

"You already know"
  Agent1 → implied: "name it so I don't have to", register: deflecting
  Agent2 → wants_to_be_named: true
  Agent3 → technique: name_pattern
  SENT: "andar kuch gooey ho gaya hai"
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from groq import Groq

from agents.banned_phrases import BANNED_PHRASES, contains_banned
from agents.prompts import (
    critic_prompt, debate_prompt, linguist_prompt,
    pattern_reader_prompt, reflector_prompt, writer_prompt,
)
from agents.voice_rules import VOICE_RULES
from config import GROQ_MODEL

logger = logging.getLogger(__name__)

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _client


# ---------------------------------------------------------------------------
# Base Groq caller
# ---------------------------------------------------------------------------

def _call(
    prompt: str,
    max_tokens: int = 250,
    temperature: float = 0.3,
    json_mode: bool = True,
    trigger: str = "unknown",
) -> dict | str:
    """Single Groq call with 3-attempt retry + backoff."""
    for attempt in range(3):
        try:
            time.sleep(0.4)  # Rate limit buffer between pipeline calls
            kwargs: dict = dict(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = _get_client().chat.completions.create(**kwargs)
            raw = resp.choices[0].message.content.strip()
            logger.debug("Agent[%s] raw: %s", trigger, raw[:120])
            if json_mode:
                # Strip any accidental markdown fences
                clean = re.sub(r"```(?:json)?", "", raw).strip()
                return json.loads(clean)
            return raw
        except Exception as e:
            logger.warning("Groq[%s] attempt %d failed: %s", trigger, attempt + 1, e)
            if attempt < 2:
                time.sleep(2 ** attempt * 2)
    # Fallback
    return {} if json_mode else ""


# ---------------------------------------------------------------------------
# Coaching doc section extractor for Agent 4
# ---------------------------------------------------------------------------

_SECTION_MAP = {
    "room_spiral":             "What Breaks Him",
    "question_loop":           "How To Push Him",
    "small_contact_destabilized": "The Girl",
    "pre_emptive_grief":       "What Breaks Him",
    "rationalization_chain":   "What Breaks Him",
    "achievement_hollow":      "What Breaks Him",
    "phatic_check":            "Who He's Becoming",
    "genuine_work_block":      "What Rebuilds Him",
    "testing_the_bot":         "How To Push Him",
    "none":                    "What Rebuilds Him",
}


def _get_doc_excerpt(pattern: dict, coaching_doc: str) -> str:
    section = _SECTION_MAP.get(pattern.get("pattern", "none"), "How To Push Him")
    lines = coaching_doc.split("\n")
    in_section, excerpt = False, []
    for line in lines:
        if line.startswith("##") and section in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("##") and section not in line:
                break
            excerpt.append(line)
    return "\n".join(excerpt[:25]).strip() or coaching_doc[:600]


# ---------------------------------------------------------------------------
# Silence duration
# ---------------------------------------------------------------------------

def _silence_minutes() -> int:
    try:
        import memory
        last = memory.get_last_response_time()
        if last is None:
            return 0
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - last).total_seconds() / 60)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Main 5-agent pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    user_message: str,
    history: list,
    coaching_doc: str,
    context_hint: str = "",
) -> str:
    """
    Run the full Society of Mind pipeline.

    Returns: message string to send, or "SILENCE" to send nothing.
    Total: 5 Groq calls, ~2-4 seconds.
    """
    import memory

    silence_mins = _silence_minutes()
    question_streak = memory.get_question_streak()
    ghost_level = memory.get_ghost_level()
    psych_model = memory.get_psych_model()
    last_two = memory.get_last_two_techniques()

    # Last bot message for linguist context
    last_bot_msg = next(
        (m["content"] for m in reversed(history[-10:]) if m.get("role") == "assistant"),
        "",
    )

    # Recent history for pattern reader
    recent_history = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[-20:]
    )

    logger.info(
        "[PIPELINE] msg=%r | silence=%dm | q_streak=%d | ghost=%d",
        user_message[:50], silence_mins, question_streak, ghost_level,
    )

    # ─── AGENT 1: LINGUIST ───────────────────────────────────────────────
    logger.info("[A1] Linguist...")
    linguist: dict = _call(
        linguist_prompt(user_message, silence_mins, last_bot_msg),
        max_tokens=220, temperature=0.15, trigger="linguist"
    )  # type: ignore
    if not linguist:
        linguist = {"register": "casual", "implied": user_message,
                    "silence_signal": "normal", "one_word_dismissal": False,
                    "call_for_action": True, "maxim_violated": "none",
                    "linguist_note": ""}
    logger.info("[A1] register=%s | implied=%s", linguist.get("register"), linguist.get("implied", "")[:60])

    # ─── AGENT 2: PATTERN READER ─────────────────────────────────────────
    logger.info("[A2] Pattern reader...")
    pattern: dict = _call(
        pattern_reader_prompt(user_message, linguist, coaching_doc, psych_model, recent_history),
        max_tokens=250, temperature=0.2, trigger="pattern"
    )  # type: ignore
    if not pattern:
        pattern = {"pattern": "none", "confidence": 0.5,
                   "current_emotional_state": "unclear",
                   "is_testing_the_bot": False, "wants_to_be_named": False,
                   "what_worked_before": "", "what_failed_before": ""}
    logger.info("[A2] pattern=%s | conf=%.1f", pattern.get("pattern"), pattern.get("confidence", 0))

    # ─── AGENT 3: DEBATE ─────────────────────────────────────────────────
    logger.info("[A3] Angel/Devil debate...")
    debate: dict = _call(
        debate_prompt(user_message, linguist, pattern, question_streak, ghost_level, last_two),
        max_tokens=220, temperature=0.4, trigger="debate"
    )  # type: ignore
    if not debate:
        debate = {"technique": "question", "winning_stance": "warmth",
                  "reasoning": "fallback", "what_NOT_to_do": "over-explain"}
    logger.info("[A3] technique=%s | stance=%s", debate.get("technique"), debate.get("winning_stance"))

    # Early exit for strategic silence
    if debate.get("technique") == "strategic_silence":
        logger.info("[PIPELINE] Strategic silence — sending nothing")
        memory.reset_question_streak()
        return "SILENCE"

    # ─── AGENT 4: WRITER ─────────────────────────────────────────────────
    logger.info("[A4] Writer composing...")
    doc_excerpt = _get_doc_excerpt(pattern, coaching_doc)
    draft: str = _call(  # type: ignore
        writer_prompt(
            user_message, linguist, pattern, debate,
            doc_excerpt, VOICE_RULES, BANNED_PHRASES, psych_model,
        ),
        max_tokens=130, temperature=0.92, json_mode=False, trigger="writer"
    )
    draft = draft.strip().strip('"').strip("'")
    logger.info("[A4] draft=%r", draft[:80])

    # Early exit for silence from writer
    if draft.upper() == "SILENCE":
        memory.reset_question_streak()
        return "SILENCE"

    # ─── AGENT 5: CRITIC ─────────────────────────────────────────────────
    logger.info("[A5] Critic reviewing...")
    critique: dict = _call(
        critic_prompt(draft, user_message, linguist, question_streak, BANNED_PHRASES),
        max_tokens=200, temperature=0.1, trigger="critic"
    )  # type: ignore
    if not critique:
        critique = {"approved": True, "final_message": draft}

    final = critique.get("final_message", draft) or draft
    approved = critique.get("approved", True)
    logger.info("[A5] approved=%s | reason=%s", approved, critique.get("rejection_reason"))

    # Final banned-phrase safety net
    banned, phrase = contains_banned(final)
    if banned:
        logger.warning("[A5] Banned phrase '%s' survived critic — stripping", phrase)
        # Compress to something safe
        final = _emergency_compress(user_message, linguist)

    # ─── TRACKING ────────────────────────────────────────────────────────
    has_question = "?" in final
    if has_question:
        memory.increment_question_streak()
    else:
        memory.reset_question_streak()

    memory.save_last_technique(debate.get("technique", "unknown"))

    logger.info("[PIPELINE] final=%r", final[:80])
    return final


def _emergency_compress(user_message: str, linguist: dict) -> str:
    """Last-resort fallback when critic still returns a banned phrase."""
    register = linguist.get("register", "casual")
    if register == "phatic":
        return "hey"
    if register == "pushing_back":
        return "fair enough"
    if register == "genuine_distress":
        return "what happened"
    if "bruh" in user_message.lower():
        return "okay"
    return "what's going on"


# ---------------------------------------------------------------------------
# Async reflector — runs every 10 user turns
# ---------------------------------------------------------------------------

def run_reflector(history: list, coaching_doc: str) -> None:
    """Update the living psychological model. Runs in a background thread."""
    import memory

    last_20 = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[-20:]
    )
    current_model = memory.get_psych_model()

    updated = _call(
        reflector_prompt(last_20, current_model, coaching_doc),
        max_tokens=400, temperature=0.2, trigger="reflector"
    )
    if updated and isinstance(updated, dict):
        memory.save_psych_model(updated)
        logger.info("[REFLECTOR] Model updated | stability=%s | momentum=%s",
                    updated.get("current_stability"), updated.get("work_momentum"))
