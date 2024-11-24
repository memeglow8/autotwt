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
        return {
            'id': self.task_id,
            'title': self.title,
            'description': self.description,
            'reward': self.reward,
            'type': 'twitter',
            'required_text': self.parameters.get('required_text', ''),
            'submission_type': 'tweet_link'
        }
