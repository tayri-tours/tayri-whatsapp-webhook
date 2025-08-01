from flask import Flask, request
import requests
import os
from datetime import datetime
import pytz
import re

app = Flask(__name__)

# ===== הגדרות =====
VERIFY_TOKEN = "tayribot"
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN")   # D360-API-KEY של 360dialog
REPLIED_USERS = set()
LOG_FILE = "log.txt"
ORDERS_FILE = "orders.txt"

# ===== Route יחיד: שורש בלבד (כמו ב-Callback של 360dialog) =====
@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode = request.args.get("hub.mode")
        # אימות פשוט: אם הטוקן תואם – מחזירים את ה-challenge
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    # POST – חשוב: תמיד להחזיר 200 כדי לא לחסום משלוחים
    data = request.get_json(silent=True) or {}
    print("📩 Incoming POST to / :", data)
    try:
        log_to_file(data)
        process_message(data)
    except Exception as e:
        print("❌ Error processing:", e)
    return "EVENT_RECEIVED", 200


# ===== עיבוד הודעה =====
def process_message(data):
    entry = (data.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return

    msg = messages[0]
    phone = msg.get("from")
    name = (msg.get("profile") or {}).get("name", "לא ידוע")
    body = (msg.get("text") or {}).get("body", "[לא טקסט]")

    print(f"\n📨 הודעה מ: {name} ({phone})")
    print(f"🕒 {get_time()} | 💬 {body}")

    # אם ההודעה הראשונה מכילה את כל פרטי ההזמנה – מעבירים לבדיקה
    if is_complete_booking(body):
        send_to_admin(phone, name, body)
        return

    # אחרת – מענה פתיחה חכם פעם אחת בלבד
    if phone not in REPLIED_USERS:
        lang = detect_language(body)
        reply = opening_reply(lang)
        send_reply(phone, reply)
        REPLIED_USERS.add(phone)


# ===== זיהוי אם הטקסט כולל כל רכיבי ההזמנה =====
def is_complete_booking(text: str) -> bool:
    checks = [
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",        # תאריך: 1/8/2025 וכד'
        r"\b\d{1,2}:\d{2}\b",                  # שעה: 05:30
        r"(איסוף|מ(?:[ן]|־)|מרחוב|מרח׳)",      # כתובת איסוף (מ/מאיסוף/מרחוב)
        r"(יעד|ל(?:[־ ]|))",                   # יעד / ל־
        r"\b(\d+)\s*נוסע(?:ים|ות)?",           # מספר נוסעים
        r"\b(\d+)\s*מזוודות?",                 # מספר מזוודות
    ]
    return all(re.search(p, text) for p in checks)


# ===== שליחת סיכום אליך (כעת ללוג + קובץ; אפשר להרחיב לאימייל/טלגרם) =====
def send_to_admin(phone, name, text):
    summary = (
        f"📥 הזמנה מלאה מהלקוח {name} ({phone}):\n\n{text}\n\n"
        f"🕒 התקבלה: {get_time()}"
    )
    print("📌 זוהתה הזמנה מלאה >> נשמרת לבדיקת מנהל:\n" + summary)
    with open(ORDERS_FILE, "a", encoding="utf-8") as f:
        f.write(summary + "\n\n")


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


# ===== שליחת הודעה דרך 360dialog =====
def send_reply(phone, text):
    url = "https://waba-v2.360dialog.io/v1/messages"
    headers = {
        "D360-API-KEY": ACCESS_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"📤 Reply sent → {r.status_code} | {r.text[:300]}")
    except Exception as e:
        print("❌ Error sending reply:", e)


# ===== תיעוד קבצים =====
def log_to_file(data):
    try:
        msg = (data.get("entry") or [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0]
        phone = msg.get("from", "unknown")
        name = (msg.get("profile") or {}).get("name", "לא ידוע")
        body = (msg.get("text") or {}).get("body", "[לא טקסט]")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{get_time()}] {name} ({phone}): {body}\n")
    except Exception as e:
        print("❌ Error writing log:", e)


# ===== שעה ישראל =====
def get_time():
    return datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")


# ===== הפעלה =====
if __name__ == "__main__":
    # ברנדר מוסיף PORT כ-ENV; בריצה לוקאלית 5000
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
