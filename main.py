from flask import Flask, request
import requests
import json
import os
from datetime import datetime
import pytz
import re

app = Flask(__name__)

# הגדרות כלליות
VERIFY_TOKEN = "tayribot"
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # משתנה סביבה
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")  # משתנה סביבה
REPLIED_USERS = set()  # למניעת מענה כפול
LOG_FILE = "log.txt"  # שם קובץ התיעוד

# אימות Webhook
@app.route("/", methods=["GET", "POST"])
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Verification failed", 403

    if request.method == "POST":
        data = request.get_json()
        log_to_file(data)
        process_incoming_message(data)
        return "EVENT_RECEIVED", 200

# עיבוד הודעה נכנסת
def process_incoming_message(data):
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return

        message = messages[0]
        phone_number = message["from"]
        name = message.get("profile", {}).get("name", "לא ידוע")
        msg_body = message["text"]["body"] if "text" in message else "[לא טקסט]"

        print(f"\n📨 הודעה חדשה מ: {name} ({phone_number})")
        print(f"🕒 שעת קבלה: {get_il_time()}")
        print(f"💬 תוכן: {msg_body}")

        lang = detect_language(msg_body)

        # בדיקת השלמת פרטי נסיעה
        if is_full_trip_request(msg_body):
            send_reply(phone_number, get_order_received_msg(lang))
            log_order_for_review(phone_number, name, msg_body)
        elif phone_number not in REPLIED_USERS:
            reply_text = generate_opening_reply(lang)
            send_reply(phone_number, reply_text)
            REPLIED_USERS.add(phone_number)

    except Exception as e:
        print("❌ שגיאה:", e)

# זיהוי שפה
def detect_language(text):
    heb_chars = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb_chars for c in text) else "en"

# נוסח פתיחה לפי שפה
def generate_opening_reply(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום? אם אתה צריך הסעה, אשמח לקבל את פרטי הנסיעה כדי להכין לך הצעת מחיר."
        )
    else:
        return (
            "Hi! I'm the smart agent of Tayri Tours\n"
            "(Smart reply from a virtual assistant – pilot in testing) 😊\n"
            "How can I help you today? If you need a ride, please send me your trip details for a quote."
        )

# הודעה אם פרטי הנסיעה מלאים
def get_order_received_msg(lang):
    if lang == "he":
        return "קיבלתי את כל פרטי הנסיעה, אני בודק את הזמינות וחוזר אליך בהקדם ✨"
    else:
        return "Got all your trip details. I'm checking availability and will get back to you shortly ✨"

# שליחת תגובה
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
    response = requests.post(url, headers=headers, json=payload)
    print(f"📤 נשלחה תשובה: {response.status_code} - {response.text}")

# תיעוד כל שיחה לקובץ
def log_to_file(data):
    try:
        msg = data.get("entry", [])[0].get("changes", [])[0].get("value", {}).get("messages", [])[0]
        phone = msg["from"]
        name = msg.get("profile", {}).get("name", "לא ידוע")
        body = msg.get("text", {}).get("body", "[לא טקסט]")
        time = get_il_time()

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time}] {name} ({phone}): {body}\n")

    except Exception as e:
        print("❌ שגיאה בלוג:", e)

# שמירת בקשה מלאה לבדיקה
def log_order_for_review(phone, name, body):
    time = get_il_time()
    log_entry = f"[{time}] 📥 הזמנה מלאה מ: {name} ({phone}):\n{body}\n\n"
    with open("orders_to_review.txt", "a", encoding="utf-8") as f:
        f.write(log_entry)

# זיהוי אם יש בהודעה את כל רכיבי ההזמנה
def is_full_trip_request(text):
    keywords = ["תאריך", "שעה", "איסוף", "יעד", "נוסעים", "מזוודות"]
    hits = sum(1 for word in keywords if word in text)
    return hits >= 5

# קבלת זמן ישראל
def get_il_time():
    return datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")

# הרצת השרת
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
