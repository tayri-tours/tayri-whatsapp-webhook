from flask import Flask, request
import requests, os, re
from datetime import datetime
import pytz

app = Flask(__name__)

# ===== הגדרות =====
VERIFY_TOKEN = "tayribot"                                  # חייב להתאים למה שהגדרת
ACCESS_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()  # D360-API-KEY של 360dialog
REPLIED_USERS = set()

# ===== נתיב כללי: שורש + כל path (מונע 404 מכל כתובת) =====
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def webhook(path):
    if request.method == "GET":
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        mode = request.args.get("hub.mode")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return (challenge or ""), 200
        return "Verification failed", 403

    # POST – תמיד 200 כדי לא לחסום משלוחים
    data = request.get_json(silent=True) or {}
    print(f"📩 Incoming POST to /{path} :", data)
    try:
        process_message(data)
    except Exception as e:
        print("❌ Error processing:", e)
    return "EVENT_RECEIVED", 200


# ===== עיבוד הודעה =====
def process_message(data):
    entry = (data.get("entry") or [{}])[0]
    change = (entry.get("changes") or [{}])[0]
    value = change.get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return

    msg = messages[0]
    phone = msg.get("from", "unknown")
    name = (msg.get("profile") or {}).get("name", "לא ידוע")
    body = (msg.get("text") or {}).get("body", "[לא טקסט]")

    print(f"\n📨 הודעה מ: {name} ({phone})")
    print(f"🕒 {get_time()} | 💬 {body}")

    # הזמנה מלאה? שמירה ללוג בלבד (אפשר להחליף בהמשך לדוא״ל/CRM)
    if is_complete_booking(body):
        summary = (
            f"📥 הזמנה מלאה מהלקוח {name} ({phone}):\n\n{body}\n\n"
            f"🕒 התקבלה: {get_time()}"
        )
        print("📌 זוהתה הזמנה מלאה >> לבדיקת מנהל:\n" + summary)
        return

    # אחרת – מענה פתיחה חכם פעם אחת
    if phone not in REPLIED_USERS:
        lang = detect_language(body)
        reply = opening_reply(lang)
        send_reply(phone, reply)
        REPLIED_USERS.add(phone)


# ===== זיהוי אם הטקסט כולל כל רכיבי ההזמנה =====
def is_complete_booking(text: str) -> bool:
    checks = [
        r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",        # תאריך: 1/8/2025
        r"\b\d{1,2}:\d{2}\b",                  # שעה: 05:30
        r"(איסוף|מ(?:[ן]|־)|מרחוב|מרח׳)",      # נק׳ איסוף
        r"(יעד|ל(?:[־ ]|))",                   # יעד / ל־
        r"\b(\d+)\s*נוסע(?:ים|ות)?",           # נוסעים
        r"\b(\d+)\s*מזוודות?",                 # מזוודות
    ]
    return all(re.search(p, text) for p in checks)


# ===== זיהוי שפה + תשובת פתיחה =====
def detect_language(text):
    heb = set("אבגדהוזחטיכלמנסעפצקרשת")
    return "he" if any(c in heb for c in text) else "en"

def opening_reply(lang):
    if lang == "he":
        return (
            "היי! כאן הסוכן החכם של טיירי טורס\n"
            "(תשובה חכמה מ״סוכן וירטואלי״ – פיילוט בבדיקה) 😊\n"
            "איך אפשר לעזור לך היום?"
        )
    return (
        "Hi! I'm the smart agent of Tayri Tours\n"
        "(Smart reply from a virtual assistant – pilot in testing) 😊\n"
        "How can I help you today?"
    )


# ===== שליחת הודעה דרך 360dialog =====
def send_reply(phone, text):
    if not ACCESS_TOKEN:
        print("⚠️ Missing WHATSAPP_TOKEN (D360-API-KEY) – cannot send reply")
        return
    url = "https://waba-v2.360dialog.io/v1/messages"
    headers = {
        "D360-API-KEY": ACCESS_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"📤 Reply sent → {r.status_code} | {r.text[:300]}")
    except Exception as e:
        print("❌ Error sending reply:", e)


# ===== שעה ישראל =====
def get_time():
    return datetime.now(pytz.timezone("Asia/Jerusalem")).strftime("%Y-%m-%d %H:%M:%S")


# ===== הפעלה =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
