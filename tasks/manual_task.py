import psycopg2
from config import DATABASE_URL
from .base_task import BaseTask

class ManualTask(BaseTask):
    """Handler for manually verified tasks"""
    
    def verify(self, user_id, submission_data):
        proof = submission_data.get('proof')
        if not proof:
            return {
                'status': 'failed',
                'message': 'Proof of completion is required'
            }

        # Store proof for admin verification
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_tasks 
                SET status = 'pending', 
                    proof = %s,
                    submitted_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND task_id = %s
                RETURNING id
            """, (proof, user_id, self.task_id))
            conn.commit()
            conn.close()

            return {
                'status': 'pending',
                'message': 'Task submission is pending admin review'
            }
        except Exception as e:
            return {
                'status': 'failed',
                'message': f'Error storing proof: {str(e)}'
            }

    def get_task_details(self):
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'manual',
            'submission_type': 'proof',
            'instructions': self.parameters.get('instructions', ''),
            'proof_format': self.parameters.get('proof_format', 'text')
        }
