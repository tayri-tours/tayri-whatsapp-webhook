from flask import Flask, request
import json
from datetime import datetime
import pytz

app = Flask(__name__)

# אימות webhook (GET)
@app.route('/', methods=['GET'])
def verify():
    verify_token = 'tayribot'
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')
    if mode and token:
        if mode == 'subscribe' and token == verify_token:
            print('[SUCCESS] Webhook verified.')
            return challenge, 200
        else:
            return 'Verification failed', 403
    return 'No content', 400

# קבלת הודעה חדשה (POST)
@app.route('/', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print("Received JSON:")
        print(json.dumps(data, indent=2))

        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']
        messages = value.get('messages')

        if messages:
            msg = messages[0]
            text = msg['text']['body']
            sender = msg['from']
            timestamp = int(msg['timestamp'])

            israel_tz = pytz.timezone('Asia/Jerusalem')
            dt_object = datetime.fromtimestamp(timestamp, israel_tz)
            readable_time = dt_object.strftime('%Y-%m-%d %H:%M:%S')

            print("====== הודעה חדשה ======")
            print(f"שם/מספר: {sender}")
            print(f"תוכן: {text}")
            print(f"שעה: {readable_time}")
            print("========================")

        return 'EVENT_RECEIVED', 200

    except Exception as e:
        print(f'[ERROR] {e}')
        return 'Error', 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
