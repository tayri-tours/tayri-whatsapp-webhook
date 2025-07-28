from flask import Flask, request
import os

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")

@app.route('/', methods=['GET'])
def verify():
    token = request.args.get('hub.verify_token')
    if token == VERIFY_TOKEN:
        return request.args.get('hub.challenge'), 200
    return 'Error: Invalid verification token', 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 קיבלנו מידע:", data)
    return 'Received', 200
