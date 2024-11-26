import requests
from .base_task import BaseTask

class TwitterTask(BaseTask):
    """Handler for Twitter-based tasks"""
    
    def verify(self, user_id, submission_data):
        tweet_id = submission_data.get('tweet_id')
        if not tweet_id:
            return {
                'status': 'failed',
                'message': 'Tweet ID is required'
            }

        # Verify tweet exists and matches requirements
        tweet_url = f"https://api.twitter.com/2/tweets/{tweet_id}"
        headers = {
            "Authorization": f"Bearer {submission_data.get('access_token')}"
        }
        
        try:
            response = requests.get(tweet_url, headers=headers)
            if response.status_code == 200:
                tweet_data = response.json().get('data', {})
                tweet_text = tweet_data.get('text', '').lower()
                
                # Check task requirements
                task_type = self.parameters.get('twitter_action', 'tweet')
                required_text = self.parameters.get('required_text', '').lower()
                
                if task_type == 'retweet':
                    # Check if it's a retweet
                    if not tweet_data.get('referenced_tweets', [{'type': None}])[0].get('type') == 'retweeted':
                        return {
                            'status': 'failed',
                            'message': 'Tweet must be a retweet'
                        }
                elif task_type == 'quote':
                    # Check if it's a quote tweet
                    if not tweet_data.get('referenced_tweets', [{'type': None}])[0].get('type') == 'quoted':
                        return {
                            'status': 'failed',
                            'message': 'Tweet must be a quote tweet'
                        }
                
                # Check required text if specified
                if required_text and required_text not in tweet_text:
                    return {
                        'status': 'failed',
                        'message': 'Tweet does not contain required text'
                    }
                
                return {
                    'status': 'completed',
                    'message': 'Tweet verification successful'
                }
            return {
                'status': 'failed',
                'message': 'Tweet does not meet requirements'
            }
        except Exception as e:
            return {
                'status': 'failed',
                'message': f'Error verifying tweet: {str(e)}'
            }

    def get_task_details(self):
        # Default instructions for different Twitter actions
        default_instructions = {
            'tweet': '1. Create a new tweet\n2. Include required text/hashtags\n3. Submit tweet URL',
            'retweet': '1. Find the specified tweet\n2. Click Retweet button\n3. Submit retweet URL',
            'quote': '1. Click Quote Tweet\n2. Add required text/hashtags\n3. Submit quote tweet URL',
            'follow': '1. Visit the specified profile\n2. Click Follow button\n3. Submit profile URL'
        }

        action_type = self.parameters.get('twitter_action', 'tweet')
        
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'twitter',
            'twitter_action': action_type,
            'required_text': self.parameters.get('required_text', ''),
            'target_account': self.parameters.get('target_account', ''),
            'submission_type': 'tweet_link',
            'instructions': default_instructions.get(action_type, default_instructions['tweet']),
            'verification_time': '1-2 minutes',
            'important_notes': [
                'Tweet/Retweet must remain public until verification',
                'Account must be public during verification',
                'Follow tasks require maintaining follow status'
            ]
        }
