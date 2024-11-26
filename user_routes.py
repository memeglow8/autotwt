from flask import Blueprint, jsonify, request, session
import logging
from database import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL

# Create blueprint
app = Blueprint('user', __name__, url_prefix='/api/user')

@app.route('/profile', methods=['GET'])
def get_profile():
    """Get user profile information."""
    username = session.get('username')
    if not username:
        return jsonify({"error": "Not authenticated"}), 401
        
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT username, referral_count, referral_reward, token_balance,
                   created_at, last_login
            FROM users 
            WHERE username = %s
        """, (username,))
        
        profile = cursor.fetchone()
        conn.close()
        
        if profile:
            return jsonify(profile)
        return jsonify({"error": "Profile not found"}), 404
        
    except Exception as e:
        logging.error(f"Error fetching profile for {username}: {e}")
        return jsonify({"error": "Database error"}), 500

@app.route('/tasks', methods=['GET'])
def get_user_tasks():
    """Get tasks for current user."""
    username = session.get('username')
    if not username:
        return jsonify({"error": "Not authenticated"}), 401
        
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT t.id, t.title, t.description, t.reward,
                   ut.status, ut.completed_at
            FROM tasks t
            LEFT JOIN user_tasks ut ON t.id = ut.task_id
            LEFT JOIN users u ON ut.user_id = u.id
            WHERE u.username = %s
            ORDER BY ut.completed_at DESC NULLS LAST
        """, (username,))
        
        tasks = cursor.fetchall()
        conn.close()
        
        return jsonify(tasks)
        
    except Exception as e:
        logging.error(f"Error fetching tasks for {username}: {e}")
        return jsonify({"error": "Database error"}), 500

@app.route('/stats', methods=['GET'])
def get_user_stats():
    """Get user statistics."""
    username = session.get('username')
    if not username:
        return jsonify({"error": "Not authenticated"}), 401
        
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                COUNT(CASE WHEN ut.status = 'completed' THEN 1 END) as completed_tasks,
                COUNT(CASE WHEN ut.status = 'in_progress' THEN 1 END) as active_tasks,
                SUM(CASE WHEN ut.status = 'completed' THEN t.reward ELSE 0 END) as total_rewards,
                u.referral_count,
                u.referral_reward,
                u.token_balance
            FROM users u
            LEFT JOIN user_tasks ut ON u.id = ut.user_id
            LEFT JOIN tasks t ON ut.task_id = t.id
            WHERE u.username = %s
            GROUP BY u.id, u.referral_count, u.referral_reward, u.token_balance
        """, (username,))
        
        stats = cursor.fetchone()
        conn.close()
        
        if stats:
            return jsonify(stats)
        return jsonify({"error": "Stats not found"}), 404
        
    except Exception as e:
        logging.error(f"Error fetching stats for {username}: {e}")
        return jsonify({"error": "Database error"}), 500

@app.route('/referrals', methods=['GET'])
def get_referrals():
    """Get user's referral information."""
    username = session.get('username')
    if not username:
        return jsonify({"error": "Not authenticated"}), 401
        
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT referral_count, referral_reward,
                   referral_code, referral_url
            FROM users
            WHERE username = %s
        """, (username,))
        
        referrals = cursor.fetchone()
        conn.close()
        
        if referrals:
            return jsonify(referrals)
        return jsonify({"error": "Referral info not found"}), 404
        
    except Exception as e:
        logging.error(f"Error fetching referrals for {username}: {e}")
        return jsonify({"error": "Database error"}), 500
