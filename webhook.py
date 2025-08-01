from flask import Flask, request
import requests
import json
import os
from datetime import datetime
import pytz

app = Flask(__name__)

VERIFY_TOKEN = "tayribot"
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
REPLIED_USERS = set()

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    if request.method == "POST":
        data = request.get_json()
        if data:
            process_message(data)
        return "EVENT_RECEIVED", 200

def process_message(data):
    try:
        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return

        msg = messages[0]
        phone = msg["from"]
        name = msg.get("profile", {}).get("name", "לא ידוע")
        text = msg.get("text", {}).get("body", "")
        timestamp = int(msg.get("timestamp", 0))

        time_str = datetime.fromtimestamp(timestamp, pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")

        print(f"\n📩 הודעה חדשה מ: {name} ({phone})")
        print(f"🕒 שעה: {time_str}")
        print(f"💬 תוכן: {text}")

        log_to_file(name, phone, text, time_str)

        if phone not in REPLIED_USERS:
            lang = detect_language(text)
            reply = generate_reply(lang)
            send_reply(phone, reply)
            REPLIED_USERS.add(phone)

    except Exception as e:
        print(f"❌ שגיאה: {e}")

def detect_language(text):
    heb_chars = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb_chars for c in text) else "en"

def generate_reply(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום? אם אתה צריך הסעה, אשמח לקבל את פרטי הנסיעה כדי להכין לך הצעת מחיר."
        )
    else:
        return (
            "Hi! This is the smart assistant of Tayri Tours\n"
            "(Smart reply from a virtual agent – pilot testing) 😊\n"
            "How can I help you today? If you need a ride, send me your trip details for a quote."
        )

def send_reply(phone, text):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"📤 נשלחה תשובה ({response.status_code})")

def log_to_file(name, phone, text, time_str):
    try:
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time_str}] {name} ({phone}): {text}\n")
    except Exception as e:
        print(f"❌ שגיאה בלוג: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
