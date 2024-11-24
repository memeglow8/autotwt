import logging
from flask import Blueprint, jsonify

# Create blueprint
app = Blueprint('tasks', __name__, url_prefix='/api/tasks')
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL

def get_tasks(status):
    """Fetch tasks based on their status."""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT title, description FROM tasks WHERE status = %s", (status,))
    tasks = cursor.fetchall()
    conn.close()
    
    return tasks

def get_user_tasks(username):
    """Retrieve all tasks and the user's task statuses."""
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
        return tasks
    except Exception as e:
        logging.error(f"Error fetching tasks: {e}")
        return []

def create_sample_tasks():
    """Insert sample tasks into the tasks table if it's empty."""
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cursor = conn.cursor()

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
            logging.info("Sample tasks created successfully.")
        else:
            logging.info("Sample tasks already exist in the database.")

        conn.close()
    except Exception as e:
        logging.error(f"Error creating sample tasks: {e}")
