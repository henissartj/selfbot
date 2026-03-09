from flask import Flask
import threading
import os
import selfbot

app = Flask(__name__)

@app.route('/')
def index():
    return "Selfbot is running! 🚀"

def run_bot():
    selfbot.run()

# Démarrer le bot dans un thread séparé au lancement de l'app
# Attention: avec Gunicorn et plusieurs workers, cela lancerait plusieurs bots.
# On configure Gunicorn avec --workers 1 pour éviter cela.
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
