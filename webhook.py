from flask import Flask, request, make_response
import os

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")

@app.before_request
def log_all_requests():
    print(f"\n📥 בקשה נכנסת: {request.method} {request.path}")
    if request.method == "POST":
        try:
            print("📨 תוכן POST:", request.get_json())
        except:
            print("⚠️ שגיאת ניתוח JSON")

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
        return make_response("EVENT_RECEIVED", 200)

    elif request.method == "HEAD":
        return make_response("", 200)  # מאפשר בדיקות זמינות מ-Meta

    return make_response("Method Not Allowed", 405)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


