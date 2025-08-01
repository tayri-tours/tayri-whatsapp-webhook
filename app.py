from flask import Flask, request
import requests
import json
import os
from datetime import datetime
import pytz

app = Flask(__name__)

# הגדרות כלליות
VERIFY_TOKEN = "tayribot"  # שם הסוכן שלך
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # נשמר במשתני סביבה
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")  # גם כן משתנה סביבה
REPLIED_USERS = set()  # כדי למנוע מענה כפול

# אימות webhook מ-360dialog
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
        name = message["profile"]["name"]
        msg_body = message["text"]["body"] if "text" in message else "[לא טקסט]"

        print(f"\n📨 הודעה חדשה מ: {name} ({phone_number})")
        print(f"🕒 שעת קבלה: {get_il_time()}")
        print(f"💬 תוכן: {msg_body}")

        if phone_number not in REPLIED_USERS:
            lang = detect_language(msg_body)
            reply_text = generate_reply(lang)
            send_reply(phone_number, reply_text)
            REPLIED_USERS.add(phone_number)

    except Exception as e:
        print("❌ שגיאה:", e)

# זיהוי עברית מול אנגלית
def detect_language(text):
    heb_chars = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb_chars for c in text) else "en"

# תגובה לפי שפה
def generate_reply(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום?"
        )
    else:
        return (
            "Hi! I'm the smart agent of Tayri Tours\n"
            "(Smart reply from a virtual assistant – pilot in testing) 😊\n"
            "How can I help you today?"
        )

# שליחת הודעה בחזרה
def send_reply(phone, text):
    url = f"https://waba-v2.360dialog.io/v1/messages"
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
    print(f"📤 נשלחה תשובה: {response.status_code}")

# תיעוד שיחה לקובץ
def log_to_file(data):
    try:
        message = data.get("entry", [])[0].get("changes", [])[0].get("value", {}).get("messages", [])[0]
        phone = message["from"]
        name = message["profile"]
