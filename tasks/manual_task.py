import psycopg2
from config import DATABASE_URL
from .base_task import BaseTask

class ManualTask(BaseTask):
    """Handler for manually verified tasks"""
    
    def get_required_parameters(self):
        return ['proof_type', 'instructions']
        
    def verify(self, user_id, submission_data):
        proof = submission_data.get('proof')
        if not proof:
            return {
                'status': 'failed',
                'message': 'Proof of completion is required'
            }

        proof_type = self.parameters.get('proof_type')
        if not self._validate_proof(proof, proof_type):
            return {
                'status': 'failed',
                'message': f'Invalid proof format. Expected {proof_type}'
            }

        # Store proof for admin verification
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_tasks 
                SET status = 'pending', 
                    proof = %s,
                    submitted_at = CURRENT_TIMESTAMP,
                    proof_type = %s
                WHERE user_id = %s AND task_id = %s
                RETURNING id
            """, (proof, proof_type, user_id, self.task_id))
            conn.commit()
            conn.close()

            return {
                'status': 'pending',
                'message': 'Task submission is pending admin review'
            }
        except Exception as e:
            logging.error(f"Error storing proof: {e}")
            return {
                'status': 'failed',
                'message': f'Error storing proof: {str(e)}'
            }

    def _validate_proof(self, proof, proof_type):
        """Validate proof based on required type"""
        if proof_type == 'screenshot':
            return proof.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        elif proof_type == 'link':
            return proof.startswith(('http://', 'https://'))
        elif proof_type == 'text':
            return len(proof.strip()) > 0
        return True

    def get_task_details(self):
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'manual',
            'submission_type': 'proof',
            'instructions': self.parameters.get('instructions', ''),
            'proof_type': self.parameters.get('proof_type', 'text'),
            'proof_format': self.parameters.get('proof_format', 'text'),
            'requirements': self.requirements
        }
