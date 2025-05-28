from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=['GET'])
def verify():
    challenge = request.args.get('hub.challenge')
    if challenge:
        return challenge, 200
    return "Missing challenge", 400

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 התקבלה הודעה:", data)
    return 'OK', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
