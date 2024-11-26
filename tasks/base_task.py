import logging
import psycopg2
from abc import ABC, abstractmethod
from config import DATABASE_URL

class BaseTask(ABC):
    """Base class for all task types"""
    
    def __init__(self, task_data):
        self.task_id = task_data.get('id')
        self.title = task_data.get('title')
        self.description = task_data.get('description')
        self.reward = task_data.get('reward', 0)
        self.status = task_data.get('status', 'active')
        self.parameters = task_data.get('parameters', {})
        self.type = task_data.get('type', 'manual')
        self.requirements = task_data.get('requirements', {})

    @abstractmethod
    def verify(self, user_id, submission_data):
        """Verify if the task was completed correctly"""
        pass

    @abstractmethod
    def get_task_details(self):
        """Get the task details in a format suitable for the frontend"""
        pass

    def validate_requirements(self):
        """Validate that all required parameters are present"""
        required_params = self.get_required_parameters()
        missing_params = [param for param in required_params if param not in self.parameters]
        if missing_params:
            raise ValueError(f"Missing required parameters: {', '.join(missing_params)}")
        return True

    @abstractmethod
    def get_required_parameters(self):
        """Return list of required parameters for this task type"""
        pass

    def update_status(self, user_id, new_status):
        """Update task status for a user"""
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_tasks 
                SET status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND task_id = %s
                RETURNING id
            """, (new_status, user_id, self.task_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logging.error(f"Error updating task status: {e}")
            return False
