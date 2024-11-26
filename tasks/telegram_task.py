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
            message_text = update.message.text
            required_groups = self.parameters.get('group_ids', [])
            required_text = self.parameters.get('required_text', '').lower()
            
            if str(chat_id) in required_groups:
                # Log user activity and check message content if required
                logging.info(f"User {user_id} active in monitored group {chat_id}")
                if required_text and required_text in message_text.lower():
                    logging.info(f"User {user_id} posted required text in group {chat_id}")
                    # Store this verification for later checking
                    self._store_verification(user_id, chat_id)
        except Exception as e:
            logging.error(f"Error handling message in task bot: {e}")

    def _store_verification(self, user_id, chat_id):
        """Store successful message verification"""
        # Implementation depends on your storage needs
        # Could use database, cache, or in-memory storage
        pass

    async def verify(self, user_id, submission_data):
        telegram_username = submission_data.get('telegram_username')
        telegram_id = submission_data.get('telegram_id')
        
        if not telegram_username or not telegram_id:
            return {
                'status': 'failed',
                'message': 'Telegram username and ID are required'
            }

        try:
            required_groups = self.parameters.get('group_ids', [])
            required_actions = self.parameters.get('required_actions', [])
            
            for group_id in required_groups:
                try:
                    # Check membership
                    member = await self.bot.get_chat_member(
                        chat_id=group_id,
                        user_id=telegram_id
                    )
                    if member.status not in ['member', 'administrator', 'creator']:
                        return {
                            'status': 'failed',
                            'message': f'User is not a member of required group {group_id}'
                        }
                    
                    # Check required actions
                    if 'send_message' in required_actions:
                        if not self._verify_message_sent(telegram_id, group_id):
                            return {
                                'status': 'failed',
                                'message': f'Required message not sent in group {group_id}'
                            }
                            
                except Exception as e:
                    logging.error(f"Error checking requirements for group {group_id}: {e}")
                    return {
                        'status': 'failed',
                        'message': 'Could not verify task completion'
                    }
            
            return {
                'status': 'completed',
                'message': 'Telegram task verification successful'
            }
        except Exception as e:
            logging.error(f"Error in telegram task verification: {e}")
            return {
                'status': 'failed',
                'message': f'Error verifying Telegram task: {str(e)}'
            }

    def _verify_message_sent(self, user_id, group_id):
        """Verify if user sent required message in group"""
        # Implementation depends on your storage method
        # Check stored verifications from _store_verification
        return True  # Placeholder

    def get_task_details(self):
        # Default instructions for Telegram tasks
        default_instructions = {
            'join': '1. Click the group/channel link\n2. Click "Join" or "Subscribe"\n3. Stay in the group/channel until task verification',
            'message': '1. Send the required message in the group/channel\n2. Do not delete the message\n3. Wait for verification',
            'both': '1. Join the group/channel\n2. Send the required message\n3. Stay active and do not delete message'
        }

        actions = self.parameters.get('required_actions', [])
        task_type = 'both' if 'send_message' in actions and 'join' in actions else ('message' if 'send_message' in actions else 'join')

        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'telegram',
            'group_ids': self.parameters.get('group_ids', []),
            'required_actions': actions,
            'required_text': self.parameters.get('required_text', ''),
            'submission_type': 'telegram_credentials',
            'instructions': default_instructions.get(task_type, default_instructions['join']),
            'verification_time': '5-10 minutes',
            'important_notes': [
                'Must remain in group/channel until verification is complete',
                'Do not delete messages sent as part of task',
                'Ensure your Telegram privacy settings allow task verification'
            ]
        }
        
    def __del__(self):
        """Cleanup when task is deleted"""
        if hasattr(self, 'app'):
            asyncio.create_task(self.app.stop())
