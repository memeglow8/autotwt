import logging
import psycopg2
from config import DATABASE_URL
from .base_task import BaseTask
import requests

class SurveyTask(BaseTask):
    """Handler for survey-based tasks"""
    
    def get_required_parameters(self):
        return ['survey_url', 'min_time', 'questions']
        
    def verify(self, user_id, submission_data):
        completion_code = submission_data.get('completion_code')
        time_spent = submission_data.get('time_spent', 0)
        
        if not completion_code:
            return {
                'status': 'failed',
                'message': 'Survey completion code is required'
            }

        # Verify minimum time spent
        min_time = self.parameters.get('min_time', 0)
        if time_spent < min_time:
            return {
                'status': 'failed',
                'message': f'Minimum time requirement not met. Please spend at least {min_time} seconds.'
            }

        try:
            # Verify completion with survey provider
            if self._verify_completion_code(completion_code):
                self.update_status(user_id, 'completed')
                return {
                    'status': 'completed',
                    'message': 'Survey completed successfully'
                }
            return {
                'status': 'failed',
                'message': 'Invalid completion code'
            }
        except Exception as e:
            logging.error(f"Error verifying survey completion: {e}")
            return {
                'status': 'failed',
                'message': 'Error verifying survey completion'
            }

    def _verify_completion_code(self, code):
        """Verify completion code with survey provider"""
        # Implementation depends on survey provider's API
        # This is a placeholder that always returns True
        return True

    def get_task_details(self):
        min_time = self.parameters.get('min_time', 5)
        question_count = self.parameters.get('questions', 0)
        
        instructions = [
            '1. Click the survey link to open in a new tab',
            '2. Read each question carefully and provide honest answers',
            f'3. Spend at least {min_time} seconds completing the survey',
            '4. Copy the completion code shown at the end',
            '5. Submit the completion code here'
        ]

        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'survey',
            'survey_url': self.parameters.get('survey_url'),
            'estimated_time': min_time,
            'question_count': question_count,
            'requirements': self.requirements,
            'instructions': '\n'.join(instructions),
            'verification_time': 'Instant',
            'important_notes': [
                'Complete survey in one session',
                'Do not refresh page during survey',
                'Keep completion code safe',
                f'Survey contains {question_count} questions',
                f'Minimum time requirement: {min_time} seconds'
            ]
        }
