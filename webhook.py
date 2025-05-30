בקשתָה,בקשתָהָ מֵבא יבואן מן קבּוק
אַפּליקַציָה = בקבוק(__נָא__)
אסימון אַימות = "tayriToken2025"  # <<< שים כאן את הטוקן בדיוק כמו שהגדרת ב-Meta

@אַפּליקַציָה.route('/', שיטות=['GET'])
def לאמת():
    אסימון = בקשתָה.ארגומנטים.get('hub.verify_token')
    אם אסימון == אסימון אַימות:
        return בקשתָה.ארגומנטים.get('hub.challenge'), 200
    return 'Error', 403

@אַפּליקַציָה.route('/', שיטות=['POST'])
def לקלוט():
    מידע = בקשתָה.get_json()
    print("📩 קיבלתי מידע:", מידע)
    return "קיבלתי", 200

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    האַפּליקַציָה.run(host='0.0.0.0', port=port)
