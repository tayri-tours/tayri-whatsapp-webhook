import os
import json
import re
import time
from datetime import datetime
from typing import Dict, Any, Optional

import requests
from flask import Flask, request, jsonify

# ==========================
# Environment configuration
# ==========================
# Required (360dialog)
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")               # D360-API-KEY
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "tayribot")           # webhook verify token
D360_BASE_URL = os.getenv("D360_BASE_URL", "https://waba.360dialog.io")

# Optional: Meta Cloud API (if you switch providers)
USE_META_CLOUD = os.getenv("USE_META_CLOUD", "false").lower() == "true"
META_TOKEN = os.getenv("META_TOKEN", "")                       # Bearer token for Meta Cloud API
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")             # Meta phone number id

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# App behavior flags
LOG_PATH = os.getenv("LOG_PATH", "orders_log.jsonl")
STATE_PATH = os.getenv("STATE_PATH", "sessions_state.json")
OWNER_PHONE = os.getenv("OWNER_PHONE", "972549039596")  # E.164 without leading + (e.g. 9725...)
APPROVAL_MODE = os.getenv("APPROVAL_MODE", "false").lower() == "true"

# ==========================
# Globals
# ==========================
app = Flask(__name__)
sessions: Dict[str, Dict[str, Any]] = {}

# ==========================
# Utilities
# ==========================

def load_state() -> None:
    global sessions
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                sessions = json.load(f)
        else:
            sessions = {}
    except Exception:
        sessions = {}


def save_state() -> None:
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(sessions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log_event(data: Dict[str, Any]) -> None:
    record = {"ts": datetime.utcnow().isoformat() + "Z", **data}
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def is_hebrew(text: str) -> bool:
    return bool(re.search(r"[\u0590-\u05FF]", text))


def detect_language(text: str) -> str:
    return "he" if is_hebrew(text) else "en"


def get_session(user_id: str) -> Dict[str, Any]:
    sess = sessions.get(user_id)
    if not sess:
        sess = {
            "first_greeting_sent": False,
            "collected": {
                "date": None,
                "time": None,
                "pickup_address": None,
                "dropoff_address": None,
                "passengers": None,
                "bags_large": None,
                "bags_small": None,
            },
            "pending_offer": None,   # where we store a prepared offer awaiting owner approval
        }
        sessions[user_id] = sess
        save_state()
    return sess


# ==========================
# Messaging senders (360dialog / Meta Cloud)
# ==========================

def _normalize_to_number(raw: str, cloud: bool = False) -> str:
    n = raw.replace("+", "").strip()
    return n if cloud else ("+" + n)


def send_whatsapp_text(to: str, body: str) -> requests.Response:
    """Send a plain text message using one of the configured providers.
    Supports:
    - 360dialog On-Prem style (v1/messages)
    - 360dialog Cloud style (waba-v2.360dialog.io/messages)
    - Meta Cloud (Graph API /{PHONE_NUMBER_ID}/messages)
    """
    # Meta Cloud explicit flag wins
    if USE_META_CLOUD:
        url = f"https://graph.facebook.com/v20.0/{PHONE_NUMBER_ID}/messages"
        headers = {"Authorization": f"Bearer {META_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _normalize_to_number(to, cloud=True),
            "type": "text",
            "text": {"body": body},
        }
        log_event({"direction": "out", "provider": "meta", "to": to, "payload": payload})
        return requests.post(url, headers=headers, json=payload, timeout=20)

    # Decide between 360dialog Cloud vs On-Prem by base URL
    base = (D360_BASE_URL or "").lower()
    is_d360_cloud = "waba-v2.360dialog.io" in base

    if is_d360_cloud:
        # Cloud API mirrors Meta Cloud schema
        url = f"{D360_BASE_URL.rstrip('/')}/messages"
        headers = {"D360-API-KEY": WHATSAPP_TOKEN, "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": _normalize_to_number(to, cloud=True),
            "type": "text",
            "text": {"body": body},
        }
        log_event({"direction": "out", "provider": "360dialog-cloud", "to": to, "payload": payload})
        return requests.post(url, headers=headers, json=payload, timeout=20)

    # Fallback: 360dialog On-Prem (legacy v1)
    url = f"{D360_BASE_URL.rstrip('/')}/v1/messages"
    headers = {"D360-API-KEY": WHATSAPP_TOKEN, "Content-Type": "application/json"}
    payload = {
        "to": _normalize_to_number(to, cloud=False),
        "type": "text",
        "text": {"body": body},
    }
    log_event({"direction": "out", "provider": "360dialog-onprem", "to": to, "payload": payload})
    return requests.post(url, headers=headers, json=payload, timeout=20)


# ==========================
# OpenAI – Structured Extraction + Dialogue Guidance
# ==========================

# We use the Responses API with a JSON Schema to parse booking info.
# SDK: openai>=1.0.0
try:
    from openai import OpenAI
    _openai_client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:  # keep server alive even if SDK missing in build step
    _openai_client = None


BOOKING_SCHEMA: Dict[str, Any] = {
    "name": "booking_schema",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "greeting",           # user says hi / opening
                    "ask_missing",        # ask targeted question to fill missing field
                    "summarize_booking",  # all fields present → summarize
                    "other"
                ]
            },
            "language": {"type": "string", "enum": ["he", "en"]},
            "missing_field": {
                "type": ["string", "null"],
                "enum": [
                    "date", "time", "pickup_address", "dropoff_address",
                    "passengers", "bags_large", "bags_small", None
                ]
            },
            "ask_message": {"type": ["string", "null"]},
            "summary_message": {"type": ["string", "null"]},
            "parsed": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "date": {"type": ["string", "null"]},
                    "time": {"type": ["string", "null"]},
                    "pickup_address": {"type": ["string", "null"]},
                    "dropoff_address": {"type": ["string", "null"]},
                    "passengers": {"type": ["integer", "null"]},
                    "bags_large": {"type": ["integer", "null"]},
                    "bags_small": {"type": ["integer", "null"]}
                },
                "required": ["date", "time", "pickup_address", "dropoff_address", "passengers", "bags_large", "bags_small"]
            }
        },
        "required": ["intent", "language", "parsed"]
    }
}


SYSTEM_GUIDE = (
    "You are Tayri Bot, a polite, concise, bi-lingual assistant for Tayri Tours taxi & shuttles. "
    "Detect the user's language (Hebrew or English) and ALWAYS answer in the same language. "
    "Follow these business rules: first message should append '(תשובה חכמה מ\"סוכן וירטואלי\" – פיילוט בבדיקה)' for Hebrew or ' (Smart reply from \"Virtual Agent\" – pilot)' for English. "
    "Collect: date, time, pickup address, dropoff address, number of passengers, number of large bags, number of small bags. "
    "If any field is missing, set intent=ask_missing and write a SHORT targeted ask_message to get exactly ONE missing field. "
    "If all fields are present, set intent=summarize_booking and write a short summary_message that re-states all fields clearly. "
    "Never invent prices. Do not promise Saturday rides without manual confirmation."
)


def openai_extract(user_text: str, prior: Dict[str, Any]) -> Dict[str, Any]:
    """Call OpenAI Responses API to parse and decide next action.
    If OpenAI is not available, fall back to a simple heuristic.
    """
    lang = detect_language(user_text)

    # Merge prior collected info into a hint for the model
    collected = prior.get("collected", {}) if prior else {}

    if not _openai_client:
        # Heuristic fallback
        parsed = {
            "date": collected.get("date") or None,
            "time": collected.get("time") or None,
            "pickup_address": collected.get("pickup_address") or None,
            "dropoff_address": collected.get("dropoff_address") or None,
            "passengers": collected.get("passengers") or None,
            "bags_large": collected.get("bags_large") or None,
            "bags_small": collected.get("bags_small") or None,
        }
        text_lower = user_text.lower()
        # rudimentary captures
        m = re.search(r"(\d{1,2}[:\.]?\d{2})", user_text)
        if m and not parsed["time"]:
            parsed["time"] = m.group(1).replace(".", ":")
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\.\d{1,2}\.\d{2,4})", user_text)
        if m and not parsed["date"]:
            parsed["date"] = m.group(1)
        m = re.search(r"(\d{1,2})\s*(passengers|pax|נוסעים)", text_lower)
        if m and not parsed["passengers"]:
            parsed["passengers"] = int(m.group(1))

        missing = [k for k, v in parsed.items() if v in (None, "", [])]
        if not prior.get("first_greeting_sent"):
            intent = "greeting"
            ask_message = None
            summary_message = None
        elif missing:
            intent = "ask_missing"
            ask_field = missing[0]
            ask_message = "What is the {}?".format(ask_field.replace("_", " ")) if lang == "en" else f"מה ה{ask_field.replace('_',' ')}?"
            summary_message = None
        else:
            intent = "summarize_booking"
            ask_message = None
            summary_message = (
                "Summary: {date} at {time}, pickup: {pickup_address}, dropoff: {dropoff_address}, "
                "passengers: {passengers}, large bags: {bags_large}, small bags: {bags_small}."
            ).format(**parsed)
        return {
            "intent": intent,
            "language": lang,
            "missing_field": missing[0] if intent == "ask_missing" else None,
            "ask_message": ask_message,
            "summary_message": summary_message,
            "parsed": parsed,
        }

    # With OpenAI
    messages = [
        {"role": "system", "content": SYSTEM_GUIDE},
        {
            "role": "user",
            "content": (
                json.dumps({
                    "user_text": user_text,
                    "collected": collected,
                }, ensure_ascii=False)
            ),
        },
    ]

    try:
        resp = _openai_client.responses.create(
            model=OPENAI_MODEL,
            input=messages,
            response_format={
                "type": "json_schema",
                "json_schema": BOOKING_SCHEMA,
            },
            temperature=0.2,
        )
        # The Responses API returns structured output in JSON form
        # Try to locate a JSON object in the response
        parsed_json: Optional[Dict[str, Any]] = None
        # New SDK returns .output with content items
        if hasattr(resp, "output") and resp.output:
            for item in resp.output:
                if hasattr(item, "content"):
                    for c in item.content:
                        if getattr(c, "type", None) == "output_json":
                            parsed_json = c.input_json  # already a dict
                            break
        # Fallback: try to parse text
        if not parsed_json:
            text_out = None
            if hasattr(resp, "output_text"):
                text_out = resp.output_text
            if not text_out and hasattr(resp, "output") and resp.output:
                # search for text blocks
                for item in resp.output:
                    if hasattr(item, "content"):
                        for c in item.content:
                            if getattr(c, "type", None) == "output_text":
                                text_out = c.text
                                break
                
            if text_out:
                try:
                    parsed_json = json.loads(text_out)
                except Exception:
                    parsed_json = None
        if not parsed_json:
            raise RuntimeError("No JSON from Responses API")
        parsed_json.setdefault("language", detect_language(user_text))
        return parsed_json
    except Exception as e:
        log_event({"level": "error", "where": "openai", "error": str(e)})
        # graceful fallback
        return openai_extract(user_text, prior={"collected": collected, "first_greeting_sent": prior.get("first_greeting_sent", False)})


# ==========================
# Conversation orchestrator
# ==========================

HE_OPENING = """
היי! תודה שפנית ל־Tayri Tours 🚗
אני כאן כדי לעזור עם הזמנת נסיעה – נצטרך תאריך, שעה, כתובת איסוף, יעד, מספר נוסעים וכמות מזוודות (גדולות וקטנות).
(תשובה חכמה מ"סוכן וירטואלי" – פיילוט בבדיקה)
""".strip()

EN_OPENING = """
Hey! Thanks for contacting Tayri Tours 🚗
I can help book your ride – I need the date, time, pickup address, dropoff, passengers, and number of bags (large/small).
(Smart reply from "Virtual Agent" – pilot)
""".strip()


def handle_logic(user_id: str, user_text: str, user_lang: Optional[str] = None) -> None:
    sess = get_session(user_id)
    lang = user_lang or detect_language(user_text)

    # Step 1: First greeting
    if not sess.get("first_greeting_sent"):
        send_whatsapp_text(user_id, HE_OPENING if lang == "he" else EN_OPENING)
        sess["first_greeting_sent"] = True
        save_state()
        # don't return; also process the message to extract data

    # Step 2: Extract with OpenAI
    analysis = openai_extract(user_text, prior=sess)
    parsed = analysis.get("parsed", {})

    # Merge newly parsed values into session
    for k, v in parsed.items():
        if v not in (None, ""):
            sess["collected"][k] = v

    save_state()

    intent = analysis.get("intent", "other")

    if intent == "ask_missing":
        ask = analysis.get("ask_message") or (
            "What detail is missing?" if lang == "en" else "איזה פרט חסר?"
        )
        send_whatsapp_text(user_id, ask)
        return

    if intent == "summarize_booking":
        # Ensure all fields exist
        c = sess["collected"]
        missing = [k for k, v in c.items() if v in (None, "")]
        if missing:
            # rare fallback if model claimed complete but something is missing
            field = missing[0]
            ask = (
                f"What is the {field.replace('_',' ')}?" if lang == "en" else f"מה ה{field.replace('_',' ')}?"
            )
            send_whatsapp_text(user_id, ask)
            return

        # Build human summary
        if analysis.get("summary_message"):
            summary = analysis["summary_message"]
        else:
            if lang == "he":
                summary = (
                    f"סיכום הזמנה: {c['date']} בשעה {c['time']} | איסוף: {c['pickup_address']} → יעד: {c['dropoff_address']} | "
                    f"נוסעים: {c['passengers']} | מזוודות גדולות: {c['bags_large']} | מזוודות קטנות: {c['bags_small']}."
                )
            else:
                summary = (
                    f"Booking summary: {c['date']} at {c['time']} | Pickup: {c['pickup_address']} → Dropoff: {c['dropoff_address']} | "
                    f"Passengers: {c['passengers']} | Large bags: {c['bags_large']} | Small bags: {c['bags_small']}."
                )

        # Log order
        log_event({"direction": "order", "user": user_id, "collected": c})

        if APPROVAL_MODE:
            # Store pending offer and ask owner for approval
            sess["pending_offer"] = {
                "user": user_id,
                "data": c,
                "lang": lang,
                "created": time.time(),
            }
            save_state()
            # Notify customer that we'll get back with a price
            msg = "נראה מצוין! אנו מכינים הצעת מחיר קצרה ונחזור אליך. 🙌" if lang == "he" else "Looks great! We'll prepare a quick quote and get back to you. 🙌"
            send_whatsapp_text(user_id, msg)
            # Ping owner with a compact approval template
            owner_msg_he = (
                "בקשת אישור מחיר:\n"
                f"לקוח: {user_id}\n"
                f"תאריך {c['date']} שעה {c['time']}\n"
                f"איסוף: {c['pickup_address']} → יעד: {c['dropoff_address']}\n"
                f"נוסעים: {c['passengers']} | מזו' גדולות: {c['bags_large']} | קטנות: {c['bags_small']}\n\n"
                "השב כאן: 'מאושר 250' כדי לשלוח."
            )
            owner_msg_en = (
                "Price approval request:\n"
                f"Customer: {user_id}\n"
                f"{c['date']} {c['time']}\n"
                f"Pickup: {c['pickup_address']} → Dropoff: {c['dropoff_address']}\n"
                f"Passengers: {c['passengers']} | Large bags: {c['bags_large']} | Small bags: {c['bags_small']}\n\n"
                "Reply here: 'approved 250' to send."
            )
            send_whatsapp_text(OWNER_PHONE, owner_msg_he + "\n\n" + owner_msg_en)
        else:
            # Send summary directly to the user (no pricing)
            send_whatsapp_text(user_id, summary)
        return

    if intent == "greeting":
        # Opening already sent; optionally nudge next step
        nudge = "איך אפשר לעזור? אפשר לשלוח את פרטי הנסיעה 😉" if lang == "he" else "How can I help? You can send your ride details 😉"
        send_whatsapp_text(user_id, nudge)
        return

    # Default
    default_reply = "אני כאן! אפשר לשלוח פרטי נסיעה או לשאול שאלה." if lang == "he" else "I'm here! Share your trip details or ask a question."
    send_whatsapp_text(user_id, default_reply)


# ==========================
# Owner approval handler (simple rule: message from OWNER_PHONE)
# ==========================

APPROVE_HE = re.compile(r"מאושר\s*(\d+)")
APPROVE_EN = re.compile(r"approved\s*(\d+)", re.I)


def handle_owner_message(text: str) -> Optional[str]:
    """If matches approval format, return the approved price as string of NIS.
    Returns None if not an approval message.
    """
    m = APPROVE_HE.search(text)
    if m:
        return m.group(1)
    m = APPROVE_EN.search(text)
    if m:
        return m.group(1)
    return None


def dispatch_approved_offer(price_nis: str) -> bool:
    """Send the approved price to the last pending customer (FIFO by creation time)."""
    # find oldest pending
    pending_list = []
    for _, s in sessions.items():
        p = s.get("pending_offer")
        if p:
            pending_list.append(p)
    if not pending_list:
        return False
    pending_list.sort(key=lambda x: x.get("created", 0))
    p = pending_list[0]
    customer = p["user"]
    lang = p.get("lang", "he")
    msg = (
        f"הצעת מחיר: {price_nis}₪ לנסיעה שתיארת. מאשרים להתקדם בהזמנה?" if lang == "he"
        else f"Quote: ₪{price_nis} for the trip you described. Would you like to confirm the booking?"
    )
    send_whatsapp_text(customer, msg)
    # clear pending offer on that session
    if customer in sessions:
        sessions[customer]["pending_offer"] = None
        save_state()
    return True


# ==========================
# Webhook endpoints
# ==========================

@app.route("/", methods=["GET"])  # healthcheck alias
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})


@app.route("/webhook", methods=["GET"])  # VERIFY
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    return "forbidden", 403


# Safety net: if a provider posts to "/" by mistake, pass it to inbound()
@app.route("/", methods=["POST"])  # <-- shim to avoid 405 when URL missing /webhook
def root_post_passthrough():
    return inbound()


@app.route("/webhook", methods=["POST"])
def inbound():
    payload = request.get_json(force=True, silent=True) or {}
    log_event({"direction": "in", "payload": payload})

    # Try to normalize inbound across providers (360dialog and Meta Cloud are very similar)
    # We will iterate over all message objects we can find.
    msgs = []

    # Meta style
    try:
        entry = payload.get("entry", [])
        for e in entry:
            for ch in e.get("changes", []):
                v = ch.get("value", {})
                for m in v.get("messages", []) or []:
                    msgs.append(m)
    except Exception:
        pass

    # 360dialog can also forward messages similarly; if not found, try root-level "messages"
    if not msgs and "messages" in payload:
        if isinstance(payload["messages"], list):
            msgs.extend(payload["messages"])

    # Process collected messages
    for m in msgs:
        from_meta = m.get("from") or m.get("author")
        text = None
        if m.get("type") == "text" and m.get("text"):
            text = m["text"].get("body")
        elif "button" in m:
            text = m.get("button", {}).get("text")
        elif m.get("interactive"):
            # handle replies/selections if needed
            interactive = m.get("interactive", {})
            text = interactive.get("title") or interactive.get("text") or interactive.get("description")

        if not from_meta or not text:
            continue

        # Owner approval path
        if APPROVAL_MODE and from_meta.replace("+", "") == OWNER_PHONE:
            price = handle_owner_message(text or "")
            if price:
                ok = dispatch_approved_offer(price)
                send_whatsapp_text(OWNER_PHONE, "נשלח ללקוח ✅" if ok else "אין בקשות ממתינות")
                continue

        # Customer
        user_id = from_meta.replace("+", "")
        handle_logic(user_id, text)

    return jsonify({"status": "ok"})


# ==========================
# Bootstrap
# ==========================
if __name__ == "__main__":
    load_state()
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
