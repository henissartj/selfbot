import json
import os

TOKENS_FILE = 'tokens.json'

class TokenManager:
    def __init__(self):
        self.file_path = TOKENS_FILE
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, 'w') as f:
                json.dump({}, f)

    def load_tokens(self):
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def save_token(self, user_info, token):
        tokens = self.load_tokens()
        user_id = user_info['id']
        
        # Construct avatar URL
        avatar_url = None
        if user_info.get('avatar'):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{user_info['avatar']}.png"
        else:
            # Default avatar based on discriminator
            discriminator = int(user_info.get('discriminator', 0))
            if discriminator == 0:
                 # New username system (pomelo)
                 # Calculate index: (user_id >> 22) % 6
                 index = (int(user_id) >> 22) % 6
                 avatar_url = f"https://cdn.discordapp.com/embed/avatars/{index}.png"
            else:
                 index = discriminator % 5
                 avatar_url = f"https://cdn.discordapp.com/embed/avatars/{index}.png"

        tokens[user_id] = {
            'token': token,
            'username': user_info['username'],
            'discriminator': user_info.get('discriminator', '0'),
            'avatar_url': avatar_url,
            'id': user_id
        }
        
        with open(self.file_path, 'w') as f:
            json.dump(tokens, f, indent=4)

    def get_token(self, user_id):
        tokens = self.load_tokens()
        return tokens.get(user_id)

    def delete_token(self, user_id):
        tokens = self.load_tokens()
        if user_id in tokens:
            del tokens[user_id]
            with open(self.file_path, 'w') as f:
                json.dump(tokens, f, indent=4)
            return True
        return False
