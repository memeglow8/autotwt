from telegram import Bot
from .base_task import BaseTask
import os

class TelegramTask(BaseTask):
    """Handler for Telegram-based tasks"""
    
    def __init__(self, task_data):
        super().__init__(task_data)
        self.bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))

    async def verify(self, user_id, submission_data):
        telegram_username = submission_data.get('telegram_username')
        if not telegram_username:
            return {
                'status': 'failed',
                'message': 'Telegram username is required'
            }

        try:
            # Check if user is member of required groups
            required_groups = self.parameters.get('group_ids', [])
            for group_id in required_groups:
                try:
                    member = await self.bot.get_chat_member(
                        chat_id=group_id,
                        user_id=submission_data.get('telegram_id')
                    )
                    if member.status not in ['member', 'administrator', 'creator']:
                        return {
                            'status': 'failed',
                            'message': f'User is not a member of required group'
                        }
                except Exception:
                    return {
                        'status': 'failed',
                        'message': f'Could not verify group membership'
                    }
            
            return {
                'status': 'completed',
                'message': 'Telegram verification successful'
            }
        except Exception as e:
            return {
                'status': 'failed',
                'message': f'Error verifying Telegram task: {str(e)}'
            }

    def get_task_details(self):
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'telegram',
            'group_ids': self.parameters.get('group_ids', []),
            'submission_type': 'telegram_username'
        }
