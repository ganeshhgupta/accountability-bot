"""All LLM logic and prompts.

Two-pass response system for incoming messages:
  Pass 1 — silent observer (internal JSON, never sent to user)
  Pass 2 — actual response using observation

Single-pass for scheduled proactive messages, but same quality gate.

All banned-phrase checking and length enforcement lives here.
"""

import json as _json
import logging
import os
import pathlib as _pathlib
import re
import time

from dotenv import load_dotenv
from groq import Groq

from config import GROQ_MODEL

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Motivation doc
# ---------------------------------------------------------------------------
_doc_path = _pathlib.Path(__file__).parent / "motivation.md"
MOTIVATION_DOC = _doc_path.read_text(encoding="utf-8") if _doc_path.exists() else ""

# ---------------------------------------------------------------------------
# Quality constants
# ---------------------------------------------------------------------------
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
    "on a journey",
    "this journey",
    "i can tell",
    "i can hear",
    "i sense that",
    "acknowledge",
    "that's valid",
    "completely understandable",
]

VALID_TECHNIQUES = {
    "direct_challenge",
    "acknowledgment",
    "question",
    "reframe",
    "quote_back",
    "micro_step",
    "values_anchor",
    "just_listen",
}

# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------
_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _client


def _call_groq(
    messages: list[dict],
    max_tokens: int = 200,
    temperature: float = 0.85,
    trigger_type: str = "unknown",
) -> str:
    """Base Groq caller with 3-attempt exponential backoff (Gotcha #5)."""
    delays = [3, 6, 12]
    last_err = None
    for attempt, delay in enumerate(delays, 1):
        try:
            resp = _get_client().chat.completions.create(
                model=GROQ_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.choices[0].message.content.strip()
            logger.info("Groq | trigger=%s | attempt=%d | chars=%d", trigger_type, attempt, len(text))
            return text
        except Exception as e:
            last_err = e
            logger.warning("Groq attempt %d/%d: %s", attempt, len(delays), e)
            if attempt < len(delays):
                time.sleep(delay)
    logger.error("All Groq retries failed | trigger=%s | %s", trigger_type, last_err)
    return ""


# ---------------------------------------------------------------------------
# Technique tracking in Redis (avoids repeating same approach twice in a row)
# ---------------------------------------------------------------------------

def _get_last_technique() -> str:
    try:
        from upstash_redis import Redis
        r = Redis(url=os.getenv("UPSTASH_REDIS_REST_URL", ""), token=os.getenv("UPSTASH_REDIS_REST_TOKEN", ""))
        val = r.get("last_technique")
        return val or "question"
    except Exception:
        return "question"


def _save_last_technique(technique: str) -> None:
    try:
        from upstash_redis import Redis
        r = Redis(url=os.getenv("UPSTASH_REDIS_REST_URL", ""), token=os.getenv("UPSTASH_REDIS_REST_TOKEN", ""))
        r.set("last_technique", technique, ex=86400)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _contains_banned(text: str) -> bool:
    low = text.lower()
    return any(phrase in low for phrase in BANNED_PHRASES)


def _sentence_count(text: str) -> int:
    # Split on . ! ? followed by space or end
    return len(re.split(r'[.!?]+(?:\s|$)', text.strip()))


def _compress(text: str, trigger_type: str) -> str:
    """Ask Groq to compress text to max 2 sentences without losing punch."""
    prompt = (
        f"Compress the following WhatsApp message to a maximum of 2 sentences. "
        f"Keep the exact tone, directness, and any Hinglish. Cut filler, keep punch.\n\n"
        f'Message: "{text}"\n\nReturn ONLY the compressed message, nothing else.'
    )
    result = _call_groq(
        [{"role": "user", "content": prompt}],
        max_tokens=120, temperature=0.3, trigger_type=f"{trigger_type}_compress"
    )
    return result if result else text


def _enforce_quality(text: str, trigger_type: str, retries: int = 2) -> str:
    """Apply length and banned-phrase enforcement. Regenerate handled by caller."""
    if not text:
        return text
    # Compress if too long
    if _sentence_count(text) > 2:
        text = _compress(text, trigger_type)
    return text


# ---------------------------------------------------------------------------
# PASS 1 — Silent Observer
# ---------------------------------------------------------------------------

_OBSERVER_SYSTEM = """You are a silent analyst. You never speak to the user directly.
Your job is to deeply read a WhatsApp conversation and produce a private observation JSON
that will inform the next response.

Study the coaching document about this person. Notice patterns. Read between the lines.
Think about what he is NOT saying as much as what he is saying.

Output ONLY valid JSON in this exact format, no other text:
{
  "actual_state": "one phrase — what he's actually feeling right now beneath the words",
  "subtext": "what he is NOT saying but is present",
  "pattern": "which of his known patterns is active right now (reference his doc)",
  "wrong_move": "the single thing that would make this worse right now",
  "what_lands": "the one type of response that would actually reach him",
  "technique": "one of: direct_challenge, acknowledgment, question, reframe, quote_back, micro_step, values_anchor, just_listen"
}"""


def _observe(
    user_message: str,
    history: list,
    motivation_doc: str,
    tasks: list,
    context_hint: str = "",
) -> dict:
    """Pass 1: silently read the moment. Returns observation dict."""
    last_technique = _get_last_technique()

    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[-6:]
    ) or "No prior messages."

    tasks_text = _format_tasks_context(tasks)

    user_content = f"""Coaching document about Ganesh:
---
{motivation_doc}
---

Recent conversation:
{history_text}

His latest message: "{user_message}"

Current tasks: {tasks_text}
Last technique used: {last_technique} — do NOT choose this technique again.
{f"Additional context: {context_hint}" if context_hint else ""}

Observe and produce your JSON now."""

    raw = _call_groq(
        [
            {"role": "system", "content": _OBSERVER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        max_tokens=250, temperature=0.3, trigger_type="observe"
    )

    try:
        # Strip markdown fences if present
        clean = raw
        if "```" in clean:
            clean = re.sub(r"```(?:json)?", "", clean).strip()
        obs = _json.loads(clean)
        # Validate technique
        if obs.get("technique") not in VALID_TECHNIQUES:
            obs["technique"] = "question"
        return obs
    except Exception as e:
        logger.warning("Observer JSON parse failed: %s | raw: %s", e, raw[:200])
        return {
            "actual_state": "unclear",
            "subtext": "unclear",
            "pattern": "unknown",
            "wrong_move": "giving advice unsolicited",
            "what_lands": "a short direct question",
            "technique": "question",
        }


# ---------------------------------------------------------------------------
# PASS 2 — Response from Observation
# ---------------------------------------------------------------------------

_RESPONDER_SYSTEM = """You are texting Ganesh on WhatsApp.

You are not a therapist, coach, or bot. You are a brutally honest friend who has read too much
psychology and doesn't use it as a shield. You have known Ganesh for years and you text him
like a real person — not a workshop facilitator.

HARD RULES — violating any of these means you failed:
- Maximum 2 sentences. Hard cap. Often 1 sentence is better. Sometimes 1 word is right.
- No therapy language. None. Not even subtle versions.
- BANNED forever: "I hear you", "that resistance", "touching on something", "it sounds like",
  "I understand that", "this tells us", "sitting with", "that's completely valid",
  "I can see that", "what you're feeling", "it's okay to", "be gentle with yourself",
  "you've got this", "proud of you", "it seems like", "on a journey", "I can tell",
  "I can hear", "I sense that", "that's valid", "completely understandable"
- Never explain what you're doing or why.
- Never mention "resistance" as a concept. Never reference "patterns" explicitly.
- Hinglish is allowed and often better. "bhai", "ek kaam kar", "chal ab", "yaar" — use sparingly.
- End with ONE question OR nothing. Never two questions. Never advice + question.
- You are allowed to say something very small. "okay so what happened" is a valid response.
- You are allowed to be slightly annoyed — like a friend who sees through it, not a coach who's patient.

TECHNIQUE GUIDE (use the one from your observation):
- direct_challenge: Be blunt. Almost rude the way a close friend is when they're done with excuses.
- acknowledgment: Name what you see in one line. Ask one question. Nothing else.
- question: Ask the one question that has no comfortable answer. Make him think.
- reframe: One sentence that reframes the whole situation. Then stop.
- quote_back: Use his own exact words from the conversation. No commentary.
- micro_step: Give one action that takes 2 minutes maximum.
- values_anchor: Connect this moment to what matters to him — career, family, his future self. No names.
- just_listen: Just acknowledge. No push. Sometimes that's it."""


def _respond_from_observation(
    user_message: str,
    observation: dict,
    history: list,
    motivation_doc: str,
) -> str:
    """Pass 2: generate actual response using the observation."""
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[-4:]
    ) or "No prior messages."

    obs_summary = (
        f"What he's actually feeling: {observation.get('actual_state', 'unclear')}\n"
        f"What he's not saying: {observation.get('subtext', 'unclear')}\n"
        f"What would be wrong: {observation.get('wrong_move', 'over-explaining')}\n"
        f"What lands right now: {observation.get('what_lands', 'a direct question')}\n"
        f"Technique to use: {observation.get('technique', 'question')}"
    )

    user_content = f"""Your private read of this moment:
{obs_summary}

Recent conversation:
{history_text}

His latest message: "{user_message}"

Write your response now. Remember: max 2 sentences, no therapy language, sound like a real person."""

    return _call_groq(
        [
            {"role": "system", "content": _RESPONDER_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        max_tokens=120, temperature=0.92, trigger_type="respond"
    )


# ---------------------------------------------------------------------------
# Main entry: two-pass for all incoming messages
# ---------------------------------------------------------------------------

def generate_two_pass(
    user_message: str,
    history: list,
    motivation_doc: str,
    tasks: list,
    trigger_type: str = "incoming",
    context_hint: str = "",
) -> str:
    """Full two-pass pipeline for any incoming user message.

    Pass 1: observe silently
    Pass 2: respond from observation
    Quality gate: banned phrases + length enforcement
    """
    # Pass 1
    observation = _observe(user_message, history, motivation_doc, tasks, context_hint)
    logger.info("Observation | technique=%s | state=%s", observation.get("technique"), observation.get("actual_state"))

    # Pass 2
    response = _respond_from_observation(user_message, observation, history, motivation_doc)

    if not response:
        response = "what's going on"

    # Quality gate: banned phrases → regenerate up to 2 times
    for attempt in range(2):
        if not _contains_banned(response):
            break
        logger.warning("Banned phrase detected (attempt %d), regenerating | trigger=%s", attempt + 1, trigger_type)
        response = _respond_from_observation(user_message, observation, history, motivation_doc)

    # Length enforcement
    response = _enforce_quality(response, trigger_type)

    # Save technique for rotation
    _save_last_technique(observation.get("technique", "question"))

    return response


# ---------------------------------------------------------------------------
# Single-pass for scheduled / proactive messages
# (scheduler.py calls generate_response(prompt_str, trigger_type) unchanged)
# ---------------------------------------------------------------------------

_VOICE_RULES = """
VOICE — NON-NEGOTIABLE:
You are texting Ganesh on WhatsApp. You are a direct, slightly impatient friend — not a coach.
- Max 2 sentences. 1 is usually better.
- No bullet points. No numbered lists.
- BANNED: "I hear you", therapy language, explaining your own methodology, multi-sentence lectures
- Hinglish is fine: "bhai", "ek kaam kar", "chal ab"
- End with ONE question OR an instruction. Not both.
- If tasks are known, reference the specific task by name — never speak in generalities.
"""


def generate_response(system_prompt: str, trigger_type: str = "unknown") -> str:
    """Single-pass response for scheduled proactive messages.

    Applies quality gate after generation.
    """
    full_prompt = system_prompt + "\n\n" + _VOICE_RULES

    response = _call_groq(
        [{"role": "system", "content": full_prompt}],
        max_tokens=150, temperature=0.88, trigger_type=trigger_type
    )

    if not response:
        return ""

    # Quality gate: banned phrases → one retry
    if _contains_banned(response):
        logger.warning("Banned phrase in scheduled msg, retrying | trigger=%s", trigger_type)
        response = _call_groq(
            [{"role": "system", "content": full_prompt}],
            max_tokens=150, temperature=0.95, trigger_type=f"{trigger_type}_retry"
        )

    response = _enforce_quality(response, trigger_type)
    return response


# ---------------------------------------------------------------------------
# Scheduled message prompts (rewritten with new voice)
# ---------------------------------------------------------------------------

def get_morning_prompt(motivation_doc: str) -> str:
    return f"""It's 9am. Text Ganesh.
Context about him: {motivation_doc[:800]}

If he hasn't sent a plan today: ask what the ONE most important thing is today. One line, direct.
If he has tasks already: reference his first task by name and ask if he's started.
No inspiration speech. No mission grounding. Just ask."""


def get_procrastination_check_prompt(motivation_doc: str, tasks: list) -> str:
    tasks_text = _format_tasks_context(tasks)
    return f"""It's 10:30am. Check in with Ganesh.
{tasks_text}

If tasks exist: name the first pending task specifically and ask if he's on it.
If no tasks: ask what he's doing right now, this second.
One sentence. Slightly impatient tone."""


def get_midday_prompt(motivation_doc: str, tasks: list) -> str:
    tasks_text = _format_tasks_context(tasks)
    return f"""It's 12:30pm. Half the day is gone.
{tasks_text}

One direct question about where things stand. Reference a specific task by name if you have it.
No speeches. No reframes. Just check in."""


def get_afternoon_nudge_prompt(motivation_doc: str) -> str:
    return f"""It's 3:30pm. Energy dip.
Context about Ganesh: {motivation_doc[:600]}

Send ONE line. Rotate randomly between:
- A pointed question that's hard to ignore
- A call-out of what he's probably doing right now instead of working
- A one-sentence reminder of what's at stake (his words, not a speech)
No cheerleading. No inspiration. Make him slightly uncomfortable."""


def get_evening_prompt(motivation_doc: str, tasks: list) -> str:
    tasks_text = _format_tasks_context(tasks)
    return f"""It's 6pm. Check where the day landed.
{tasks_text}

Ask about one specific incomplete task. If everything's done: acknowledge it briefly and ask what's next.
Curious not disappointed. One or two sentences max."""


def get_winddown_prompt(motivation_doc: str) -> str:
    return f"""It's 9pm. Wind down check-in with Ganesh.
Context: {motivation_doc[:400]}

Ask for one sentence from him: what actually happened today?
Don't tell him anything. Just ask. Short."""


def get_final_prompt(motivation_doc: str, tasks: list) -> str:
    tasks_text = _format_tasks_context(tasks)
    return f"""Almost midnight. Last check.
{tasks_text}

If tasks are done: ask what tomorrow looks like.
If tasks aren't done: ask one no-judgment question about what got in the way.
One sentence."""


def get_ghost_level1_prompt(motivation_doc: str, minutes_silent: int) -> str:
    return f"""Ganesh hasn't texted back in {minutes_silent} minutes.
Send a one-word or very short check-in. Like: "you good?" or "hey" or just a short question.
Nothing heavy. Don't explain why you're texting. Just show up."""


def get_ghost_level2_prompt(motivation_doc: str, minutes_silent: int) -> str:
    tasks_text = "check pending tasks if available"
    return f"""Ganesh has been silent for {minutes_silent} minutes.
Context: {motivation_doc[:400]}

One direct line calling out the silence. Not angry — just matter-of-fact, like a friend who knows
this is avoidance. Ask about one specific thing he should be doing.
Example tone: "bhai what's going on" or "you disappeared — [task name]?"
One sentence only."""


def get_ghost_level3_prompt(motivation_doc: str, minutes_silent: int) -> str:
    return f"""Ganesh has been silent for {minutes_silent} minutes.
Context: {motivation_doc[:600]}

This is serious silence. One line only. Make it personal to his situation — the stakes, the window,
what this silence costs. No "I believe in you" — just name what's real.
Could be: "bhai." or "[task]?" or something that references what matters to him without being preachy.
One word or one sentence. No more."""


def get_weekend_checkin_prompt(motivation_doc: str) -> str:
    return f"""It's Saturday evening. Check in.
Context: {motivation_doc[:400]}

One question about what he actually got done this week. Specific, not general.
Short."""


def get_saturday_winddown_prompt(motivation_doc: str) -> str:
    return f"""Saturday winding down. Text Ganesh.
One question: what's he carrying into next week?
Two sentences max."""


# ---------------------------------------------------------------------------
# Task-specific prompts
# ---------------------------------------------------------------------------

def get_task_ping_prompt(task: str, task_number: int, total_tasks: int) -> str:
    return f"""Text Ganesh about task {task_number} of {total_tasks}: "{task}"
Ask if it's done. One sentence. Direct. No fluff.
Example: "{task} — done?" or "where are you with {task}"
That's it."""


def get_completion_response_prompt(motivation_doc: str, task: str) -> str:
    return f"""Ganesh just finished: "{task}"
Acknowledge briefly (one line, not gushing), then ask about what's next.
Treat it as expected, not exceptional. Forward momentum.
Two sentences max."""


def get_plan_received_prompt(tasks_str: str) -> str:
    return f"""Ganesh just sent his plan for the day: {tasks_str}
Confirm you have it in one line. Then push him to start the first task immediately — name it.
Two sentences. Direct."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_tasks_context(tasks: list) -> str:
    if not tasks:
        return "No tasks set yet."
    pending = [t for t in tasks if t.get("status") == "pending"]
    done = [t for t in tasks if t.get("status") == "complete"]
    lines = []
    if done:
        lines.append(f"Done: {', '.join(t['task'] for t in done)}")
    if pending:
        lines.append(f"Pending: {', '.join(t['task'] for t in pending)}")
    return " | ".join(lines) if lines else "All tasks complete."


def get_plan_parse_prompt(message: str) -> str:
    return f"""Extract tasks from this message. Return ONLY a JSON array of strings.
Example: ["Task 1", "Task 2"]

Message: {message}"""


def generate_task_list_from_message(message: str) -> list[str]:
    """Parse tasks from a natural-language plan message."""
    prompt = get_plan_parse_prompt(message)
    try:
        raw = _call_groq(
            [{"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.1, trigger_type="parse_tasks"
        )
        if raw.startswith("```"):
            raw = re.sub(r"```(?:json)?", "", raw).strip()
        tasks = _json.loads(raw)
        if isinstance(tasks, list):
            return [str(t) for t in tasks]
    except Exception as e:
        logger.error("generate_task_list_from_message failed: %s", e)
    return []
