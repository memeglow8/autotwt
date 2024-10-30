import psycopg2
import json
import requests
from config import DATABASE_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Telegram messaging function moved here to avoid circular import
def send_message_via_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=data)

def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tokens (
        id SERIAL PRIMARY KEY,
        access_token TEXT NOT NULL,
        refresh_token TEXT,
        username TEXT NOT NULL
    )''')
    conn.commit()
    conn.close()

def store_token(access_token, refresh_token, username):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tokens WHERE username = %s", (username,))
    if cursor.fetchone():
        cursor.execute("DELETE FROM tokens WHERE username = %s", (username,))
    cursor.execute("INSERT INTO tokens (access_token, refresh_token, username) VALUES (%s, %s, %s)", (access_token, refresh_token, username))
    conn.commit()
    conn.close()

def restore_from_backup():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM tokens')
    if cursor.fetchone()[0] == 0:
        if os.path.exists("tokens_backup.txt"):
            with open("tokens_backup.txt", 'r') as f:
                backup_data = json.load(f)
                for token_data in backup_data:
                    access_token, refresh_token, username = token_data.values()
                    cursor.execute("INSERT INTO tokens (access_token, refresh_token, username) VALUES (%s, %s, %s)", (access_token, refresh_token, username))
                    conn.commit()
            send_message_via_telegram("📂 Backup restored successfully")
        else:
            print("No backup file found.")
    conn.close()

def get_all_tokens():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('SELECT access_token, refresh_token, username FROM tokens')
    tokens = cursor.fetchall()
    conn.close()
    return tokens

def get_total_tokens():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM tokens')
    total = cursor.fetchone()[0]
    conn.close()
    return total
