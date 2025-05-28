from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=['GET'])
def verify():
    return request.args.get('hub.challenge')

@app.route('/', methods=['POST'])
def webhook():
    data = request.get_json()
    print('📩 קיבלנו הודעה:', data)
    return 'OK', 200

if __name__ == '__main__':
    app.run()
