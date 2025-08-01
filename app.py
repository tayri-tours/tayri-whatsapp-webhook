from flask import Flask, request, jsonify
import os, re, requests, json
from datetime import datetime
import pytz

# =========================
#        CONFIG
# =========================
# Webhook verification token
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot").strip()

# 360dialog API key (REQUIRED when using 360dialog)
D360_API_KEY = os.environ.get("D360_API_KEY", "").strip()

# OpenAI (optional for smart extraction)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        print("⚠️ OpenAI SDK not available:", e)

TIMEZONE = "Asia/Jerusalem"

# =========================
#        APP
# =========================
app = Flask(__name__)

# In-memory session per customer
SESSIONS = {}  # { wa_id: {"stage": str, "data": dict, "lang": "he"/"en", "name": str, "msisdn": str} }

# ---------- Universal webhook (GET verify + POST receive) ----------
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def webhook(path):
    if request.method == "GET":
        # Verify subscription
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode = request.args.get("hub.mode")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return (challenge or ""), 200
        return "Verification failed", 403

    # POST: inbound message
    data = request.get_json(silent=True) or {}
    print(f"📩 Incoming POST to /{path} :", data)
    try:
        handle_message(data)
    except Exception as e:
        print("❌ Error handling message:", e)
    return "EVENT_RECEIVED", 200


# =========================
#        CORE LOGIC
# =========================

def handle_message(data):
    entry = (data.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return

    msg = messages[0]
    wa_id = msg.get("from", "unknown")
    text = (msg.get("text") or {}).get("body", "").strip()
    name = extract_name(value, msg)
    lang = detect_language(text or name)
    msisdn = format_msisdn(wa_id)

    sess = SESSIONS.setdefault(wa_id, {"stage": "start", "data": {}, "lang": lang, "name": name, "msisdn": msisdn})
    sess["lang"], sess["name"], sess["msisdn"] = lang, name, msisdn

    # 1) Attempt structured extraction via OpenAI; fallback to regex
    extracted = {}
    if client and text:
        extracted = extract_with_openai(text, lang)
    else:
        extracted = extract_with_regex(text)

    # Merge into session
    for k, v in (extracted or {}).items():
        if v:
            sess["data"][k] = v

    # If all fields already present → finalize
    if has_all_fields(sess["data"]):
        summary = finalize_order(wa_id)
        send_reply_auto(wa_id, summary)
        sess["stage"] = "done"
        return

    # Conversation flow
    stage = sess["stage"]
    if stage == "start":
        send_reply_auto(wa_id, opening_reply(lang, name, msisdn))
        sess["stage"] = "collect"
        return

    if stage == "collect":
        missing = missing_fields(sess["data"])
        if not missing:
            summary = finalize_order(wa_id)
            send_reply_auto(wa_id, summary)
            sess["stage"] = "done"
            return
        send_reply_auto(wa_id, ask_for_next(missing, lang))
        return

    if stage == "done":
        # If user sends updates after summary
        if extracted:
            summary = finalize_order(wa_id)
            send_reply_auto(wa_id, summary)
        else:
            send_reply_auto(wa_id, thanks_reply(lang))


# =========================
#        OPENAI (CHAT JSON)
# =========================

def extract_with_openai(text: str, lang: str) -> dict:
    """חילוץ פרטי נסיעה באמצעות Chat Completions במצב JSON – תואם לאחור לגרסאות openai שונות."""
    try:
        system = (
            "Return ONLY a JSON object with these keys (omit missing): "
            "date (DD/MM/YYYY), time (HH:MM), pickup, destination, passengers, luggage."
        )
        user = f"טקסט לקוח: {text}" if lang == "he" else f"Customer text: {text}"

        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # או gpt-4.1-mini אם זמין
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return normalize_fields(data)

    except Exception as e:
        print("⚠️ OpenAI extract error (chat):", e)
        return extract_with_regex(text)


# =========================
#        REGEX FALLBACK
# =========================

DATE_RE = r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"
TIME_RE = r"\b(\d{1,2}:\d{2})\b"
PICKUP_RE = r"(?:איסוף|מאיסוף|מ-|מ־|מ |מרחוב|מרח׳)\s*([^\n,]+)"
DEST_RE = r"(?:יעד|ל |ל־)\s*([^\n,]+)"
PAX_RE = r"\b(\d+)\s*נוסע(?:ים|ות)?\b"
LUG_RE = r"\b(\d+)\s*מזוודות?\b"

def extract_with_regex(text: str) -> dict:
    d = {}
    m = re.search(DATE_RE, text);        d["date"] = m.group(1) if m else None
    m = re.search(TIME_RE, text);        d["time"] = m.group(1) if m else None
    m = re.search(PICKUP_RE, text);      d["pickup"] = m.group(1).strip() if m else None
    m = re.search(DEST_RE, text);        d["destination"] = m.group(1).strip() if m else None
    m = re.search(PAX_RE, text);         d["passengers"] = m.group(1) if m else None
    m = re.search(LUG_RE, text);         d["luggage"] = m.group(1) if m else None
    return {k: v for k, v in d.items() if v}


def normalize_fields(obj: dict) -> dict:
    out = {}
    for k in ["date", "time", "pickup", "destination", "passengers", "luggage"]:
        if k in obj and obj[k]:
            out[k] = str(obj[k]).strip()
    return out


def has_all_fields(d: dict) -> bool:
    need = ["date", "time", "pickup", "destination", "passengers", "luggage"]
    return all(d.get(k) for k in need)


def missing_fields(d: dict):
    order = ["date", "time", "pickup", "destination", "passengers", "luggage"]
    return [k for k in order if not d.get(k)]


# =========================
#        DIALOG TEXTS
# =========================

def detect_language(text):
    heb = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb for c in text) else "en"


def opening_reply(lang, name, msisdn):
    if lang == "he":
        who = f"{name} (☎️ {msisdn})" if (name or msisdn) else ""
        return (
            f"היי {who}! כאן הסוכן החכם של טיירי טורס (פיילוט) 😊\n"
            "כדי להכין הצעת מחיר אצטרך: תאריך, שעה, כתובת איסוף, יעד, מספר נוסעים ומספר מזוודות.\n"
            "אפשר לכתוב הכול בהודעה אחת — ואם חסר, אשאל צעד-צעד."
        )
    return (
        f"Hi {name} (☎️ {msisdn})! I'm Tayri Tours smart agent (pilot) 😊\n"
        "To prepare a quote I need: date, time, pickup, destination, passengers, luggage.\n"
        "Share everything in one message — if something is missing I’ll ask step by step."
    )


def ask_for_next(missing, lang):
    nxt = missing[0]
    he = {
        "date": "מה תאריך הנסיעה? (למשל 03/08/2025)",
        "time": "באיזו שעה? (למשל 17:30)",
        "pickup": "מה כתובת האיסוף המדויקת?",
        "destination": "מה היעד?",
        "passengers": "כמה נוסעים יהיו?",
        "luggage": "כמה מזוודות?",
    }
    en = {
        "date": "What’s the date? (e.g., 08/03/2025)",
        "time": "What time? (e.g., 17:30)",
        "pickup": "Pickup address?",
        "destination": "Destination?",
        "passengers": "How many passengers?",
        "luggage": "How many suitcases?",
    }
    return (he if lang == "he" else en)[nxt]


def thanks_reply(lang):
    return "תודה! קיבלתי 🙌" if lang == "he" else "Thanks! Noted 🙌"


# =========================
#        FINALIZE & LOG
# =========================

def finalize_order(wa_id):
    sess = SESSIONS.get(wa_id, {})
    d = sess.get("data", {})
    name = sess.get("name", "לקוח")
    lang = sess.get("lang", "he")
    msisdn = sess.get("msisdn", format_msisdn(wa_id))
    ts = get_time()

    # Operational log (hook for CRM/Sheets/email)
    print("👤 Inbound from:", f"{name} ({msisdn})")
    print(
        "🗂 Order captured:\n"
        + f"לקוח: {name} ({msisdn}) | {ts}\n"
        + f"תאריך: {d.get('date')} | שעה: {d.get('time')}\n"
        + f"איסוף: {d.get('pickup')} → יעד: {d.get('destination')}\n"
        + f"נוסעים: {d.get('passengers')} | מזוודות: {d.get('luggage')}\n---"
    )

    if lang == "he":
        return (
            f"✅ קיבלתי הזמנה מלאה מ-{name} (☎️ {msisdn}):\n"
            f"• תאריך: {d.get('date')}\n"
            f"• שעה: {d.get('time')}\n"
            f"• איסוף: {d.get('pickup')}\n"
            f"• יעד: {d.get('destination')}\n"
            f"• נוסעים: {d.get('passengers')}\n"
            f"• מזוודות: {d.get('luggage')}\n\n"
            f"מעביר למנהל לאישור הצעת מחיר ויחזרו אליך מיד."
        )
    else:
        return (
            f"✅ Got your full request, {name} (☎️ {msisdn}):\n"
            f"• Date: {d.get('date')}\n"
            f"• Time: {d.get('time')}\n"
            f"• Pickup: {d.get('pickup')}\n"
            f"• Destination: {d.get('destination')}\n"
            f"• Passengers: {d.get('passengers')}\n"
            f"• Luggage: {d.get('luggage')}\n\n"
            f"I’m sending this to the manager for a quote approval and will get back to you shortly."
        )


def extract_name(value, msg):
    name = ((value.get("contacts") or [{}])[0].get("profile") or {}).get("name")
    if not name:
        name = (msg.get("profile") or {}).get("name")
    if not name:
        name = msg.get("from", "לא ידוע")
    return name


def format_msisdn(wa_id: str) -> str:
    """Normalize WhatsApp wa_id to +E.164 for display/logs."""
    digits = re.sub(r"[^0-9]", "", str(wa_id or ""))
    return "+" + digits if digits else ""


# =========================
#        SENDING (360dialog)
# =========================

def send_reply_auto(wa_id, text):
    if not D360_API_KEY:
        print("⛔ No D360_API_KEY configured")
        return
    if send_via_360(wa_id, text):
        return
    print("⛔ 360dialog send failed")


def send_via_360(wa_id, text) -> bool:
    # 360dialog expects E.164 number WITHOUT '+'
    to = re.sub(r"[^0-9]", "", str(wa_id))
    urls = [
        "https://waba-v2.360dialog.io/v1/messages",
        "https://waba.360dialog.io/v1/messages",
    ]
    headers = {
        "D360-API-KEY": D360_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "to": to,
        "type": "text",
        "text": {"body": str(text)}
    }
    for url in urls:
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            print(f"➡️  360 → {url} | payload={payload}")
            print(f"📤 360 response → {r.status_code} | {r.text}")
            if r.status_code in (200, 201):
                return True
        except Exception as e:
            print("❌ Error sending via 360:", e)
    return False


# =========================
#        UTILS / DEBUG
# =========================

def get_time():
    return datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")


@app.route("/debug/openai", methods=["GET"])  # remove or protect before production
def debug_openai():
    if not OPENAI_API_KEY:
        return jsonify(ok=False, error="OPENAI_API_KEY missing"), 500
    if not client:
        return jsonify(ok=False, error="OpenAI client not initialized"), 500
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
        )
        body = resp.choices[0].message.content
        return jsonify(ok=True, status="200", body=body)
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@app.route("/debug/360")  # /debug/360?to=9725XXXXXXX&text=בדיקה
def debug_360():
    if not D360_API_KEY:
        return jsonify(ok=False, error="D360_API_KEY missing"), 500
    to = request.args.get("to")
    text = request.args.get("text", "בדיקה")
    if not to:
        return jsonify(ok=False, error="missing ?to=9725XXXXXXX"), 400
    ok = send_via_360(to, text)
    return jsonify(ok=ok)


if __name__ == "__main__":
    # For local testing only; Render will use its own server
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
