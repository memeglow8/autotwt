from .base_task import BaseTask

class ManualTask(BaseTask):
    """Handler for manually verified tasks"""
    
    def verify(self, user_id, submission_data):
        # Manual tasks require admin verification
        # Return pending status until approved
        return {
            'status': 'pending',
            'message': 'Task submission is pending admin review'
        }

    def get_task_details(self):
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'manual',
            'submission_type': 'text'
        }
