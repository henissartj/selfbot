from flask import Flask, render_template, request, session, redirect, url_for
from flask_session import Session
import os
import selfbot
import bot_manager

# Configuration Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

print("✅ Flask App starting...")

# Démarrer le Bot Manager Discord en background (si token présent)
# Cela permet d'avoir le bot officiel qui répond à !panel
try:
    if os.getenv("MANAGER_TOKEN"):
        print("🚀 Démarrage du Bot Manager...")
        bot_manager.start_manager()
    else:
        print("⚠️ MANAGER_TOKEN non défini. Le bot manager ne démarrera pas.")
except Exception as e:
    print(f"❌ Erreur démarrage Bot Manager: {e}")

@app.route('/', methods=['GET', 'POST'])
def index():
    if 'token' in session:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        token = request.form.get('token')
        if token:
            session['token'] = token
            # Démarrer le bot pour cet utilisateur
            selfbot.start_bot(token)
            return redirect(url_for('dashboard'))
            
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'token' not in session:
        return redirect(url_for('index'))
    
    token = session['token']
    bot_instance = selfbot.get_bot(token)
    
    if not bot_instance:
        # Si le bot n'est pas lancé (redémarrage serveur par ex), on le relance
        bot_instance = selfbot.start_bot(token)
    
    return render_template('dashboard.html', 
                         status=bot_instance.status, 
                         user=bot_instance.user_info)

@app.route('/logout')
def logout():
    token = session.get('token')
    if token:
        selfbot.stop_bot(token)
    session.pop('token', None)
    return redirect(url_for('index'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
