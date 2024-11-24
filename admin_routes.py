from flask import redirect, request, session, render_template, url_for, jsonify
import logging
from database import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL
import os

# Admin credentials from environment variables
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'password')

def validate_admin_credentials(username, password):
    return username == ADMIN_USERNAME and password == ADMIN_PASSWORD

def get_analytics_overview():
    """Fetch analytics data for the admin dashboard."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    analytics = {}
    
    try:
        cursor.execute("SELECT COUNT(*) AS total_users FROM users")
        analytics['total_users'] = cursor.fetchone()['total_users']

        cursor.execute("SELECT COUNT(*) AS total_completed_tasks FROM user_tasks WHERE status = 'completed'")
        analytics['total_completed_tasks'] = cursor.fetchone()['total_completed_tasks']

        cursor.execute("SELECT SUM(referral_count) AS total_referrals FROM users")
        analytics['total_referrals'] = cursor.fetchone()['total_referrals']

        cursor.execute("SELECT SUM(referral_reward + token_balance) AS total_rewards FROM users")
        analytics['total_rewards'] = cursor.fetchone()['total_rewards']

    except Exception as e:
        logging.error(f"Error fetching analytics data: {e}")
    finally:
        conn.close()

    return analytics

def get_all_users():
    """Retrieve all users for admin management."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT id, username, referral_count, referral_reward, token_balance 
        FROM users 
        ORDER BY username ASC
    """)
    users = cursor.fetchall()
    conn.close()
    return users
