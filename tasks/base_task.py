from abc import ABC, abstractmethod

class BaseTask(ABC):
    """Base class for all task types"""
    
    def __init__(self, task_data):
        self.task_id = task_data.get('id')
        self.title = task_data.get('title')
        self.description = task_data.get('description')
        self.reward = task_data.get('reward', 0)
        self.status = task_data.get('status', 'active')
        self.parameters = task_data.get('parameters', {})

    @abstractmethod
    def verify(self, user_id, submission_data):
        """Verify if the task was completed correctly"""
        pass

    @abstractmethod
    def get_task_details(self):
        """Get the task details in a format suitable for the frontend"""
        pass
