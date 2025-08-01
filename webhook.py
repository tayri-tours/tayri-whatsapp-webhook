from flask import Flask, request, make_response
import os
import json
from datetime import datetime
import pytz
import requests

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")
DIALOG_API_KEY = os.environ.get("DIALOG_API_KEY", "הכנס_כאן_את_הטוקן_שלך")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "הכנס_כאן_את_ID_של_מספר_054")

CHATLOG_PATH = "chatlog.json"

# שומר כל הודעה לקובץ לוג
def save_chat_log(entry):
    if os.path.exists(CHATLOG_PATH):
        with open(CHATLOG_PATH, "r", encoding="utf-8") as f:
            chatlog = json.load(f)
    else:
        chatlog = []

    chatlog.append(entry)

    with open(CHATLOG_PATH, "w", encoding="utf-8") as f:
        json.dump(chatlog, f, ensure_ascii=False, indent=2)


# זיהוי שפה פשוט לפי תוכן ההודעה
def detect_language(text):
    heb_chars = sum(c.isalpha() and 'א' <= c <= 'ת' for c in text)
    eng_chars = sum(c.isalpha() and 'a' <= c.lower() <= 'z' for c in text)
    return "he" if heb_chars >= eng_chars else "en"


# יוצר תשובה מותאמת לשפה
def generate_response(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום?\nאם אתה צריך הסעה – אשמח לקבל את פרטי הנסיעה כדי להכין לך הצעת מחיר."
        )
    else:
        return (
            "Hi! This is Tayri Tours' smart assistant.\n"
            "(Pilot response from a virtual agent under testing) 😊\n"
            "How can I help you today? If you need a ride, feel free to send me your travel details."
        )


# שליחת תשובה חזרה דרך Dialog360
def send_reply(to_number, text):
    url = f"https://waba.360dialog.io/v1/messages"
    headers = {
        "D360-API-KEY": DIALOG_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    response = requests.post(url, headers=headers, json=payload)
    print("📤 שליחת תגובה:", response.status_code, response.text)
    return response.status_code == 200


@app.before_request
def log_all_requests():
    print(f"\n📥 בקשה נכנסת: {request.method} {request.path}")
    if request.method == "POST":
        try:
            print("📨 POST:", request.get_json())
        except:
            print("⚠️ שגיאת JSON")


@app.route("/", methods=["GET", "POST", "HEAD"])
@app.route("/webhook", methods=["GET", "POST", "HEAD"])
def webhook():
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode = request.args.get("hub.mode")
        if token == VERIFY_TOKEN and mode == "subscribe":
            return make_response(challenge, 200)
        else:
            return make_response("❌ אימות נכשל", 403)

    elif request.method == "POST":
        try:
            data = request.get_json()
            contact = data["contacts"][0]
            msg = data["messages"][0]

            name = contact.get("profile", {}).get("name", "")
            phone = contact["wa_id"]
            text = msg.get("text", {}).get("body", "")
            ts = int(msg.get("timestamp", 0))

            # זמן מקומי
            tz = pytz.timezone("Asia/Jerusalem")
            local_time = datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d %H:%M:%S")

            lang = detect_language(text)
            reply = generate_response(lang)

            # שליחת תשובה
            send_reply(phone, reply)

            # שמירת תיעוד
            save_chat_log({
                "timestamp": local_time,
                "from": phone,
                "name": name,
                "language": lang,
                "message": text,
                "response": reply
            })

        except Exception as e:
            print("⚠️ שגיאה בטיפול ב־POST:", e)
            return make_response("Error", 500)

        return make_response("EVENT_RECEIVED", 200)

    elif request.method == "HEAD":
        return make_response("", 200)

    return make_response("Method Not Allowed", 405)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
