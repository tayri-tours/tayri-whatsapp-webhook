from flask import Flask, request, make_response
import json
import os
import pytz
import requests
from datetime import datetime

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")
DIALOG_API_KEY = os.environ.get("DIALOG_API_KEY", "הכנס_כאן_את_הטוקן_שלך")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "הכנס_כאן_את_PhoneNumberID")
LOG_FILE = "log.txt"
RESPONDED_USERS = {}

# זיהוי שפת ההודעה
def detect_language(text):
    heb_chars = sum(1 for c in text if 'א' <= c <= 'ת')
    eng_chars = sum(1 for c in text.lower() if 'a' <= c <= 'z')
    return "he" if heb_chars >= eng_chars else "en"

# נוסח פתיחה אוטומטי
def get_opening_response(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום? אם אתה צריך הסעה, אשמח לקבל את פרטי הנסיעה כדי להכין לך הצעת מחיר."
        )
    else:
        return (
            "Hi! This is the smart assistant of Tayri Tours\n"
            "(Pilot response from a virtual agent under testing) 😊\n"
            "How can I help you today? If you need a ride, feel free to send me your trip details for a quote."
        )

# שליחת תגובה אוטומטית
def send_reply(phone_number, message):
    url = "https://waba.360dialog.io/v1/messages"
    headers = {
        "D360-API-KEY": DIALOG_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "to": phone_number,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"[RESPONSE {response.status_code}] {response.text}")
    return response.status_code == 200

# תיעוד שיחה
def log_message(entry):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# אימות webhook מ־Meta
@app.route("/", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    mode = request.args.get("hub.mode")
    if token == VERIFY_TOKEN and mode == "subscribe":
        return make_response(challenge, 200)
    return make_response("Verification failed", 403)

# קבלת הודעה
@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json()
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        messages = value.get('messages')

        if messages:
            msg = messages[0]
            text = msg.get('text', {}).get('body', '')
            phone = msg.get('from')
            timestamp = int(msg.get('timestamp'))

            # תאריך עברי לפי אזור זמן ישראל
            tz = pytz.timezone('Asia/Jerusalem')
            dt = datetime.fromtimestamp(timestamp, tz)
            readable_time = dt.strftime('%Y-%m-%d %H:%M:%S')

            # שפה + מענה
            lang = detect_language(text)
            response_text = get_opening_response(lang)

            # שליחת מענה רק פעם אחת
            if phone not in RESPONDED_USERS:
                send_reply(phone, response_text)
                RESPONDED_USERS[phone] = datetime.now()

            # שמירת תיעוד
            log_message({
                "time": readable_time,
                "from": phone,
                "lang": lang,
                "message": text,
                "response": response_text
            })

    except Exception as e:
        print(f"[ERROR] {e}")
        return make_response("Error", 500)

    return make_response("EVENT_RECEIVED", 200)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
