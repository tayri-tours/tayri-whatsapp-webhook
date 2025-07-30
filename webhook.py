from flask import Flask, request
import os

app = Flask(__name__)

VERIFY_TOKEN = request.args.get('hub.verify_token')

@app.route('/', methods=['GET'])
def verify():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode and token:
        if token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return 'Error: Invalid verification token', 403
    return 'Error: Missing parameters', 400

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 קיבלנו פוסט:", data)
    return 'Received', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
