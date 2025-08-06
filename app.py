from flask import Flask, request
import os, re, requests
from datetime import datetime
import pytz

# ---------- OpenAI ----------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        print("⚠️ OpenAI SDK not available:", e)

app = Flask(__name__)

# ---------- Config ----------
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()
TIMEZONE = "Asia/Jerusalem"
SESSIONS = {}

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def webhook(path):
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode = request.args.get("hub.mode")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return (challenge or ""), 200
        return "Verification failed", 403

    data = request.get_json(silent=True) or {}
    print(f"📩 Incoming POST to /{path} :", data)
    try:
        handle_message(data)
    except Exception as e:
        print("❌ Error:", e)
    return "EVENT_RECEIVED", 200

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

    sess = SESSIONS.setdefault(wa_id, {"stage": "start", "data": {}, "lang": lang, "name": name})
    sess["lang"], sess["name"] = lang, name

    extracted = extract_with_openai(text, lang) if client and text else extract_with_regex(text)

    for k, v in (extracted or {}).items():
        if v:
            sess["data"][k] = v

    if has_all_fields(sess["data"]):
        summary = finalize_order(wa_id)
        send_reply_auto(wa_id, summary)
        sess["stage"] = "done"
        return

    stage = sess["stage"]
    if stage == "start":
        send_reply_auto(wa_id, opening_reply(lang))
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
        if extracted:
            summary = finalize_order(wa_id)
            send_reply_auto(wa_id, summary)
        else:
            send_reply_auto(wa_id, thanks_reply(lang))

# ---------- Extraction ----------
BOOKING_FIELDS = ["date", "time", "pickup", "destination", "passengers", "luggage"]

def extract_with_openai(text, lang) -> dict:
    try:
        prompt = "Extract booking details into JSON: date, time, pickup, destination, passengers, luggage."
        if lang == "he":
            prompt = "חלץ פרטי הזמנה לקובץ JSON: תאריך, שעה, איסוף, יעד, נוסעים, מזוודות."
        message = f"טקסט לקוח: {text}" if lang == "he" else f"Customer message: {text}"

        response = client.chat.completions.create(
            model="gpt-4.0-turbo",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ]
        )

        content = response.choices[0].message.content
        try:
            import json
            data = json.loads(content)
            return normalize_fields(data)
        except:
            return extract_with_regex(content)
    except Exception as e:
        print("⚠️ OpenAI extract error:", e)
        return extract_with_regex(text)

DATE_RE = r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b"
TIME_RE = r"\b(\d{1,2}:\d{2})\b"
PICKUP_RE = r"(?:איסוף|מ-|מרחוב|מרח׳)\s*([^\n,]+)"
DEST_RE = r"(?:יעד|ל |ל־)\s*([^\n,]+)"
PAX_RE = r"\b(\d+)\s*נוסע(?:ים|ות)?\b"
LUG_RE = r"\b(\d+)\s*מזוודות?\b"

def extract_with_regex(text: str) -> dict:
    d = {}
    m = re.search(DATE_RE, text);       d["date"] = m.group(1) if m else None
    m = re.search(TIME_RE, text);       d["time"] = m.group(1) if m else None
    m = re.search(PICKUP_RE, text);     d["pickup"] = m.group(1).strip() if m else None
    m = re.search(DEST_RE, text);       d["destination"] = m.group(1).strip() if m else None
    m = re.search(PAX_RE, text);        d["passengers"] = m.group(1) if m else None
    m = re.search(LUG_RE, text);        d["luggage"] = m.group(1) if m else None
    return {k: v for k, v in d.items() if v}

def normalize_fields(obj: dict) -> dict:
    return {k: str(obj.get(k)).strip() for k in BOOKING_FIELDS if obj.get(k)}

# ---------- Utils ----------
def has_all_fields(d): return all(d.get(k) for k in BOOKING_FIELDS)
def missing_fields(d): return [k for k in BOOKING_FIELDS if not d.get(k)]

def detect_language(text): return "he" if any(c in set("אבגדהוזחטיכלמנסעפצקרשת") for c in text) else "en"

def extract_name(value, msg):
    name = ((value.get("contacts") or [{}])[0].get("profile") or {}).get("name")
    if not name:
        name = (msg.get("profile") or {}).get("name")
    return name or msg.get("from", "לקוח")

def get_time():
    return datetime.now(pytz.timezone(TIMEZONE)).strftime("%Y-%m-%d %H:%M:%S")

# ---------- Replies ----------
def opening_reply(lang):
    return ("היי! כאן הסוכן החכם של טיירי טורס (פיילוט) 😊\n"
            "כדי להכין הצעת מחיר אצטרך: תאריך, שעה, כתובת איסוף, יעד, מספר נוסעים ומספר מזוודות.\n"
            "אפשר לכתוב הכול בהודעה אחת — ואם חסר, אשאל צעד-צעד.") if lang == "he" else \
           ("Hi! I'm Tayri Tours smart agent (pilot) 😊\n"
            "To prepare a quote I need: date, time, pickup, destination, passengers, luggage.\n"
            "You can write everything in one message — if something is missing, I’ll ask step by step.")

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

def finalize_order(wa_id):
    sess = SESSIONS.get(wa_id, {})
    d = sess.get("data", {})
    name = sess.get("name", "לקוח")
    lang = sess.get("lang", "he")
    ts = get_time()

    print("🗂 Order captured:\n" +
          f"לקוח: {name} ({wa_id}) | {ts}\n"
          f"תאריך: {d.get('date')} | שעה: {d.get('time')}\n"
          f"איסוף: {d.get('pickup')} → יעד: {d.get('destination')}\n"
          f"נוסעים: {d.get('passengers')} | מזוודות: {d.get('luggage')}\n---")

    if lang == "he":
        return (f"✅ קיבלתי הזמנה מלאה מ-{name}:\n"
                f"• תאריך: {d.get('date')}\n"
                f"• שעה: {d.get('time')}\n"
                f"• איסוף: {d.get('pickup')}\n"
                f"• יעד: {d.get('destination')}\n"
                f"• נוסעים: {d.get('passengers')}\n"
                f"• מזוודות: {d.get('luggage')}\n\n"
                f"מעביר למנהל לאישור הצעת מחיר ויחזרו אליך מיד.")
    else:
        return (f"✅ Got your full request, {name}:\n"
                f"• Date: {d.get('date')}\n"
                f"• Time: {d.get('time')}\n"
                f"• Pickup: {d.get('pickup')}\n"
                f"• Destination: {d.get('destination')}\n"
                f"• Passengers: {d.get('passengers')}\n"
                f"• Luggage: {d.get('luggage')}\n\n"
                f"I’m sending this to the manager for quote approval and will get back to you shortly.")

# ---------- Send via 360 ----------
def send_reply_auto(wa_id, text):
    if not ACCESS_TOKEN:
        print("⚠️ Missing WHATSAPP_TOKEN – cannot send reply")
        return
    send_via_360(wa_id, text)

def send_via_360(wa_id, text) -> bool:
    url = "https://waba.360dialog.io/messages"
    headers = {
        "D360-API-KEY": ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    to = str(wa_id).lstrip("+")
    payload = {
        "to": to,
        "recipient_type": "individual",
        "type": "text",
        "text": {"body": str(text), "preview_url": False},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print(f"➡️  360 → {url} | to={to} | payload={payload}")
        print(f"📤 360 response → {r.status_code} | {r.text}")
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"❌ Error sending via 360 ({url}):", e)
        return False
