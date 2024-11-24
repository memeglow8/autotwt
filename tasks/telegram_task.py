from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
from .base_task import BaseTask
import os
import asyncio
import logging
from config import TELEGRAM_TASK_BOT_TOKEN

class TelegramTask(BaseTask):
    """Handler for Telegram-based tasks"""
    
    def __init__(self, task_data):
        super().__init__(task_data)
        self.bot = Bot(token=TELEGRAM_TASK_BOT_TOKEN)
        self._setup_bot()
        
    def _setup_bot(self):
        """Initialize the bot and set up message handlers"""
        try:
            self.app = Application.builder().token(TELEGRAM_TASK_BOT_TOKEN).build()
            self.app.add_handler(MessageHandler(filters.ALL, self._handle_message))
            asyncio.create_task(self.app.run_polling())
            logging.info("Task verification bot started successfully")
        except Exception as e:
            logging.error(f"Failed to initialize task verification bot: {e}")

    async def _handle_message(self, update, context):
        """Handle incoming messages to monitor group activity"""
        try:
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            required_groups = self.parameters.get('group_ids', [])
            
            if str(chat_id) in required_groups:
                # Log user activity in this group
                logging.info(f"User {user_id} active in monitored group {chat_id}")
        except Exception as e:
            logging.error(f"Error handling message in task bot: {e}")

    async def verify(self, user_id, submission_data):
        telegram_username = submission_data.get('telegram_username')
        if not telegram_username:
            return {
                'status': 'failed',
                'message': 'Telegram username is required'
            }

        try:
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
                            'message': 'User is not a member of required group'
                        }
                except Exception as e:
                    logging.error(f"Error checking membership for group {group_id}: {e}")
                    return {
                        'status': 'failed',
                        'message': 'Could not verify group membership'
                    }
            
            return {
                'status': 'completed',
                'message': 'Telegram verification successful'
            }
        except Exception as e:
            logging.error(f"Error in telegram task verification: {e}")
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
        
    def __del__(self):
        """Cleanup when task is deleted"""
        if hasattr(self, 'app'):
            asyncio.create_task(self.app.stop())
