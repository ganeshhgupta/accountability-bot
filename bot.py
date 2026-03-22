"""Flask app — webhook handler, health/status/trigger endpoints, startup checks.

FIXES.md Gotcha #1: Always return HTTP 200 from webhook.
FIXES.md Gotcha #2: Never use debug=True.
"""

import json
import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive incoming WhatsApp messages from Twilio.

    Always returns 200 with TwiML to avoid Twilio retry loops (Gotcha #1).
    """
    twiml = MessagingResponse()
    try:
        body = request.form.get("Body", "").strip()
        from_number = request.form.get("From", "").strip()

        logger.info("Webhook | from=%s | body=%s", from_number, body[:80])

        from agents.orchestrator import handle_incoming
        response_text = handle_incoming(body, from_number)

        if response_text:
            twiml.message(response_text)
    except Exception as e:
        logger.error("Webhook error: %s", e, exc_info=True)
        # Return empty TwiML — never 500

    return str(twiml), 200, {"Content-Type": "text/xml"}


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    from agents.schedule_agent import is_active_now
    from datetime import datetime, timezone
    return jsonify({
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "active": is_active_now(),
    })


# ---------------------------------------------------------------------------
# Status (requires X-Token header)
# ---------------------------------------------------------------------------

@app.route("/status", methods=["GET"])
def status():
    token = request.headers.get("X-Token", "")
    if token != os.getenv("EDIT_SECRET", ""):
        return jsonify({"error": "unauthorized"}), 401

    import memory
    from datetime import datetime
    import pytz
    today = datetime.now(pytz.timezone("America/Chicago")).strftime("%Y-%m-%d")
    return jsonify({
        "chat_history_count": len(memory.get_chat_history()),
        "tasks_today": memory.get_tasks(today),
        "last_response_time": str(memory.get_last_response_time()),
        "ghost_level": memory.get_ghost_level(),
        "motivation_override": memory.get_motivation_override(),
        "day_state": memory.get_day_state(),
    })


# ---------------------------------------------------------------------------
# Manual trigger (requires X-Token header)
# ---------------------------------------------------------------------------

TRIGGER_MAP = {
    "morning":               "morning",
    "procrastination_check": "procrastination_check",
    "midday":                "midday",
    "afternoon_nudge":       "afternoon_nudge",
    "evening":               "evening",
    "winddown":              "winddown",
    "final":                 "final",
    "weekend_checkin":       "weekend_checkin",
    "saturday_winddown":     "saturday_winddown",
    "ghost":                 "_ghost",
}


@app.route("/trigger/<trigger_type>", methods=["GET"])
def trigger(trigger_type: str):
    """Manually fire any scheduled message type for testing."""
    token = request.headers.get("X-Token", "")
    if token != os.getenv("EDIT_SECRET", ""):
        return jsonify({"error": "unauthorized"}), 401

    if trigger_type not in TRIGGER_MAP:
        return jsonify({
            "error": "unknown trigger",
            "valid": list(TRIGGER_MAP.keys()),
        }), 400

    try:
        if trigger_type == "ghost":
            from agents.ghost_agent import escalate_if_needed
            from scheduler import _send_whatsapp
            msg = escalate_if_needed()
            if msg:
                _send_whatsapp(msg, "ghost_escalation")
                return jsonify({"sent": True, "message": msg})
            return jsonify({"sent": False, "reason": "no escalation needed"})

        from scheduler import _job
        _job(TRIGGER_MAP[trigger_type])
        return jsonify({"sent": True, "trigger": trigger_type})
    except Exception as e:
        logger.error("Trigger error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Startup health checks
# ---------------------------------------------------------------------------

def run_startup_checks() -> None:
    """Validate external service connections before accepting traffic."""
    logger.info("=== Startup Health Checks ===")

    # 1. Groq
    try:
        from groq import Groq
        from config import GROQ_MODEL
        client = Groq(api_key=os.getenv("GROQ_API_KEY", ""))
        client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
        )
        logger.info("[OK]  Groq connection verified")
    except Exception as e:
        logger.error("[FAIL] Groq connection failed: %s", e)

    # 2. Redis
    try:
        from upstash_redis import Redis
        r = Redis(
            url=os.getenv("UPSTASH_REDIS_REST_URL", ""),
            token=os.getenv("UPSTASH_REDIS_REST_TOKEN", ""),
        )
        r.set("startup_check", "ok", ex=10)
        val = r.get("startup_check")
        assert val == "ok"
        logger.info("[OK]  Redis connection verified")
    except Exception as e:
        logger.error("[FAIL] Redis connection failed: %s", e)

    # 3. Twilio
    try:
        from twilio.rest import Client
        client = Client(os.getenv("TWILIO_ACCOUNT_SID", ""), os.getenv("TWILIO_AUTH_TOKEN", ""))
        account = client.api.accounts(os.getenv("TWILIO_ACCOUNT_SID", "")).fetch()
        logger.info("[OK]  Twilio verified (account: %s)", account.friendly_name)
    except Exception as e:
        logger.error("[FAIL] Twilio connection failed: %s", e)

    logger.info("=== Startup Checks Complete ===")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_startup_checks()

    from scheduler import create_scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started")

    # Send startup notification
    try:
        from twilio.rest import Client
        _c = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
        _c.messages.create(
            body="Bot is live. Kar le bhai.",
            from_=os.getenv("TWILIO_WHATSAPP_FROM"),
            to=os.getenv("MY_WHATSAPP_NUMBER"),
        )
        logger.info("Startup message sent")
    except Exception as _e:
        logger.warning("Startup message failed: %s", _e)

    port = int(os.getenv("PORT", 5000))
    # FIXES.md Gotcha #2: Never use debug=True
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
