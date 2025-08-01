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

@app.route("/", methods=["GET", "POST"])
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    if request.method == "POST":
        data = request.get_json()
        log_to_file(data)
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

        message = messages[0]
        phone = message["from"]
        name = message["profile"]["name"]
        body = message.get("text", {}).get("body", "[לא טקסט]")

        print(f"\n📨 הודעה מ: {name} ({phone})")
        print(f"🕒 {get_time()} | 💬 {body}")

        if phone not in REPLIED_USERS:
            lang = detect_language(body)
            reply = opening_reply(lang)
            send_reply(phone, reply)
            REPLIED_USERS.add(phone)

    except Exception as e:
        print(f"❌ שגיאה: {e}")

def detect_language(text):
    heb_chars = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb_chars for c in text) else "en"

def opening_reply(lang):
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
    print(f"📤 תשובה נשלחה ({response.status_code})")

def log_to_file(data):
    try:
        msg = data.get("entry", [])[0].get("changes", [])[0].get("value", {}).get("messages", [])[0]
        phone = msg["from"]
        name = msg.get("profile", {}).get("name", "לא ידוע")
        text = msg.get("text", {}).get("body", "[לא טקסט]")
        time = get_time()

        with open("log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{time}] {name} ({phone}): {text}\n")

    except Exception as e:
        print(f"❌ שגיאה בלוג: {e}")

def get_time():
    return datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")

if __name__ == "__main__":
    app.run(port=5000)
