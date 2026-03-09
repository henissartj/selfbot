from flask import Flask, render_template, request, session, redirect, url_for
from flask_session import Session
import threading
import os
import bot_manager
import logging

# Configuration Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Démarrer le Bot Manager Discord en background
def run_manager():
    bot_manager.run()

threading.Thread(target=run_manager, daemon=True).start()

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'token' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        token = request.form.get('token')
        if token:
            session['token'] = token
            # Lancer le bot via le manager (sans owner_id connu au début)
            bot_manager.start_selfbot_thread(token, owner_id=None)
            return redirect(url_for('dashboard'))
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'token' not in session:
        return redirect(url_for('index'))
    
    token = session['token']
    bot = bot_manager.get_bot_by_token(token)
    
    status = "Initialisation..."
    user_info = "Inconnu"
    
    if bot:
        if bot.is_ready():
            status = "Online ✅"
            user_info = str(bot.user)
            # Mise à jour rétroactive de l'owner_id si besoin (pas critique pour le web mais utile)
        else:
            status = "Connexion en cours... ⏳"
    else:
        # Si le bot n'est pas trouvé (redémarrage serveur ?), on le relance
        bot_manager.start_selfbot_thread(token, owner_id=None)
        status = "Redémarrage... 🔄"

    return render_template('dashboard.html', status=status, user=user_info)

@app.route('/logout')
def logout():
    token = session.get('token')
    if token:
        bot_manager.stop_selfbot_by_token(token)
    session.pop('token', None)
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
