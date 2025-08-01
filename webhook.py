from flask import Flask, request, make_response
import os
from datetime import datetime
import pytz

app = Flask(__name__)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")

@app.before_request
def log_all_requests():
    print(f"\n📥 בקשה נכנסת: {request.method} {request.path}")
    if request.method == "POST":
        try:
            data = request.get_json()
            print("📨 JSON שהתקבל:", data)

            # חילוץ נתונים
            name = data["contacts"][0]["profile"]["name"]
            phone = data["contacts"][0]["wa_id"]
            message = data["messages"][0]["text"]["body"]
            ts_unix = int(data["messages"][0]["timestamp"])
            
            # המרת זמן ל־ישראל
            tz = pytz.timezone("Asia/Jerusalem")
            ts_local = datetime.fromtimestamp(ts_unix, tz).strftime('%Y-%m-%d %H:%M:%S')

            # הדפסה מסודרת
            print(f"\n🧾 הודעה מ־{name} ({phone})")
            print(f"🕒 נשלחה בתאריך: {ts_local}")
            print(f"💬 תוכן ההודעה: {message}\n")

        except Exception as e:
            print("⚠️ שגיאת ניתוח JSON:", e)

@app.route('/', methods=['GET', 'POST', 'HEAD'])
@app.route('/webhook', methods=['GET', 'POST', 'HEAD'])
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
        return make_response("EVENT_RECEIVED", 200)

    elif request.method == "HEAD":
        return make_response("", 200)

    return make_response("Method Not Allowed", 405)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


