import base64
import hashlib
import os
import requests
from flask import Flask, request, jsonify, render_template
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import logging

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = 'https://gifter-7vz7.onrender.com/'  # Update with your callback URL
ALERT_BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')
AUTOMATION_BOT_TOKEN = os.getenv('AUTOMATION_BOT_TOKEN')
ALERT_CHAT_ID = os.getenv('ALERT_CHAT_ID')
AUTOMATION_CHAT_ID = os.getenv('AUTOMATION_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')  # URL to set as the webhook for the bot

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Telegram Bot and Dispatcher
alert_bot = Bot(token=ALERT_BOT_TOKEN)
automation_bot = Bot(token=AUTOMATION_BOT_TOKEN)
dispatcher = Dispatcher(automation_bot, None, workers=4)

# Function to set up the webhook
def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"
    alert_bot.set_webhook(url=webhook_url)
    automation_bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

# Function to handle start command
def start(update, context):
    update.message.reply_text("Welcome! This bot is running using webhooks.")

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
    elif query.data == 'main_menu':
        send_automation_startup_message()

# Function to refresh all tokens
def refresh_all_tokens():
    # Example implementation to simulate token refresh
    logger.info("Refreshing all tokens...")

# Function to send a message to the automation bot with options
def send_automation_startup_message():
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    automation_bot.send_message(chat_id=AUTOMATION_CHAT_ID,
                                text="Automation Bot Started. Choose an option below.",
                                reply_markup=reply_markup)

# Webhook route to handle incoming updates
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), automation_bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'})

# Flask Routes for OAuth
@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        # Post tweet logic goes here
        return render_template('tweet_result.html', result="Tweet posted.")
    return render_template('tweet_form.html', access_token=access_token)

@app.route('/')
def home():
    return "Server is running and ready to receive webhooks!"

# Setting up command handlers
dispatcher.add_handler(CommandHandler('start', start))
dispatcher.add_handler(CallbackQueryHandler(handle_button))

if __name__ == '__main__':
    set_webhook()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
