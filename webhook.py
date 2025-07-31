from flask import Flask, request
import os

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "tayribot")

@app.route('/', methods=['GET', 'POST'])
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')
        mode = request.args.get('hub.mode')

        if token == VERIFY_TOKEN and mode == 'subscribe':
            return challenge, 200
        else:
            return 'Error: Invalid token or mode', 403

    elif request.method == 'POST':
        try:
            data = request.get_json()
            print("📩 קיבלתי מידע:", data)
            return 'EVENT_RECEIVED', 200
        except Exception as e:
            print("⚠️ שגיאה:", e)
            return 'ERROR', 500

    return 'Invalid request method', 405

@app.before_request
def log_all_requests():
    print(f"📥 התקבלה בקשה: {request.method} {request.path}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

