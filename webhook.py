from flask import Flask, request
import os

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        # אימות Webhook מול Dialog360 / Meta
        VERIFY_TOKEN = os.environ.get('VERIFY_TOKEN')  # נלקח מתוך הגדרת Environment
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge')

        if mode == 'subscribe' and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return 'Error: Invalid verification token', 403

    if request.method == 'POST':
        # כאן יגיעו ההודעות בפורמט JSON
        data = request.get_json()
        print("✅ New webhook event received:")
        print(data)

        # תחזיר תשובה תקינה ל-WhatsApp כדי שיזהה שהכל תקין
        return 'EVENT_RECEIVED', 200

    return 'Unsupported method', 405

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
