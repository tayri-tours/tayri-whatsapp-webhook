from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = "tayriToken2025"  # <<< שים כאן את אותו הטוקן בדיוק כמו שהזנת ב-Meta

@app.route('/', methods=['GET'])
def verify():
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if token == VERIFY_TOKEN:
        return challenge, 200
    return 'Invalid verification token', 403

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📥 התקבלה הודעה:", data)
    return 'OK', 200

if __name__ == '__main__':
    app.run()
