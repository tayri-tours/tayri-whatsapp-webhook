from flask import Flask, request
import requests, os, re
from datetime import datetime
import pytz

app = Flask(__name__)

# ===== הגדרות =====
VERIFY_TOKEN    = "tayribot"                                      # חייב להתאים למה שהגדרת
ACCESS_TOKEN    = os.environ.get("WHATSAPP_TOKEN", "").strip()     # Meta Cloud Bearer או D360-API-KEY
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "").strip()    # אם קיים -> נשלח דרך Cloud
REPLIED_USERS   = set()

# ===== נתיב כללי: "/" וגם כל path (מונע 404) =====
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def webhook(path):
    if request.method == "GET":
        token     = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode      = request.args.get("hub.mode")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return (challenge or ""), 200
        return "Verification failed", 403

    data = request.get_json(silent=True) or {}
    print(f"📩 Incoming POST to /{path} :", data)
    try:
        process_message(data)
    except Exception as e:
        print("❌ Error processing:", e)
    return "EVENT_RECEIVED", 200


# ===== עיבוד הודעה =====
def process_message(data):
    entry    = (data.get("entry") or [{}])[0]
    change   = (entry.get("changes") or [{}])[0]
    value    = change.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return

    msg   = messages[0]
    phone = msg.get("from", "unknown")                  # זה wa_id מה‑Inbound
    name  = extract_name(value, msg)
    body  = (msg.get("text") or {}).get("body", "[לא טקסט]")

    print(f"\n📨 הודעה מ: {name} ({phone})")
    print(f"🕒 {get_time()} | 💬 {body}")

    # הזמנה מלאה? תיעוד (אפשר להרחיב בהמשך)
    if is_complete_booking(body):
        print("📌 זוהתה הזמנה מלאה – מועבר לבדיקת מנהל בלבד.")
        return

    # תשובת פתיחה פעם אחת
    if phone not in REPLIED_USERS:
        lang  = detect_language(body)
        reply = opening_reply(lang)
        send_reply_auto(phone, reply, value)            # <<< שליחה אוטומטית: Cloud או 360
        REPLIED_USERS.add(phone)


# ===== זיהוי שם הלקוח =====
def extract_name(value, msg):
    name = ((value.get("contacts") or [{}])[0].get("profile") or {}).get("name")
    if not name:
        name = (msg.get("profile") or {}).get("name")
    if not name:
        name = msg.get("from", "לא ידוע")
    return name


# ===== זיהוי אם הטקסט כולל כל רכיבי ההזמנה =====
def is_complete_booking(text: str) -> bool:
    checks = [
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",        # תאריך
        r"\b\d{1,2}:\d{2}\b",                  # שעה
        r"(איסוף|מ(?:[ן]|־)|מרחוב|מרח׳)",      # נק׳ איסוף
        r"(יעד|ל(?:[־ ]|))",                   # יעד / ל־
        r"\b(\d+)\s*נוסע(?:ים|ות)?",           # נוסעים
        r"\b(\d+)\s*מזוודות?",                 # מזוודות
    ]
    return all(re.search(p, text) for p in checks)


# ===== זיהוי שפה + תשובת פתיחה =====
def detect_language(text):
    heb = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb for c in text) else "en"

def opening_reply(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום?"
        )
    return (
        "Hi! I'm the smart agent of Tayri Tours\n"
        "(Smart reply from a virtual assistant – pilot in testing) 😊\n"
        "How can I help you today?"
    )


# ===== שליחה אוטומטית: Cloud (אם יש PHONE_NUMBER_ID) או 360dialog =====
def send_reply_auto(phone_wa_id, text, value):
    if not ACCESS_TOKEN:
        print("⚠️ Missing WHATSAPP_TOKEN – cannot send reply")
        return

    # אם יש PHONE_NUMBER_ID – נשלח ב‑Meta Cloud (Graph API)
    if PHONE_NUMBER_ID:
        ok = send_via_cloud(phone_wa_id, text)
        if ok:
            return
        # אם מסיבה כלשהי נכשל – ננסה גם דרך 360 כ‑fallback
        print("↪️ Cloud send failed – trying 360dialog fallback...")

    send_via_360(phone_wa_id, text)


# ----- Meta Cloud API -----
def send_via_cloud(phone_wa_id, text) -> bool:
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": str(phone_wa_id),            # ה‑wa_id שמגיע מה‑Inbound
        "type": "text",
        "text": {"preview_url": False, "body": str(text)},
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        print(f"➡️  Cloud → {url} | payload={payload}")
        print(f"📤 Cloud response → {r.status_code} | {r.text}")
        return r.status_code in (200, 201)
    except Exception as e:
        print("❌ Error sending via Cloud:", e)
        return False


# ----- 360dialog API -----
def send_via_360(phone_wa_id, text) -> bool:
    urls = [
        "https://waba-v2.360dialog.io/v1/messages",
        "https://waba.360dialog.io/v1/messages",
    ]
    tos = [str(phone_wa_id)]
    if not str(phone_wa_id).startswith("+"):
        tos.append("+" + str(phone_wa_id))  # לפעמים נדרש עם פלוס

    headers = {
        "D360-API-KEY": ACCESS_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    for url in urls:
        for to in tos:
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
                if r.status_code in (200, 201):
                    return True
            except Exception as e:
                print(f"❌ Error sending via 360 ({url}):", e)
    print("⛔ Failed to send via 360dialog")
    return False


# ===== שעה ישראל =====
def get_time():
    return datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")


# ===== הפעלה =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

