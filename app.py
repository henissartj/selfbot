from flask import Flask
import threading
import os
import bot_manager

app = Flask(__name__)

@app.route('/')
def index():
    return "Manager Bot is running! 🤖 Use Discord to interact."

def run_manager():
    bot_manager.run()

# Lancer le Manager Bot dans un thread
threading.Thread(target=run_manager, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
