from flask import Flask, request
import os

האַפּליקַציָה = Flask(__name__)

אסימון_אימות = "tayriToken2025"

@האַפּליקַציָה.route('/', methods=['GET'])
def אימות():
    אסימון = request.args.get('hub.verify_token')
    if אסימון == אסימון_אימות:
        return request.args.get('hub.challenge'), 200
    return 'Error', 403

@האַפּליקַציָה.route('/', methods=['POST'])
def קליטה():
    מידע = request.get_json()
    print("📩 קיבלתי מידע:", מידע)
    return "Received", 200
