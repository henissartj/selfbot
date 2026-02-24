from flask import Flask, render_template, request, redirect, url_for, session
import multiprocessing
import selfbot
import os
import signal
import sys
import requests
import secrets
import time

app = Flask(__name__)
# Use a fixed secret key or environment variable to prevent logout on restart
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_selfbot_12345')

# CSRF Protection
@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get('csrf_token')
        if not token or token != request.headers.get('X-CSRFToken'):
            # Allow login form without X-CSRFToken header if it uses form field (handled manually below)
            if request.endpoint == 'index':
                pass 
            else:
                return "CSRF Token invalid", 403

def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(16)
    return session['csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

# Configuration du mot de passe du site
# On cherche d'abord dans une variable d'environnement
SITE_PASSWORD = os.environ.get('SITE_PASSWORD')
# Si pas trouvé, on cherche dans un fichier (pour les Secret Files de Render)
if not SITE_PASSWORD:
    secret_path = '/etc/secrets/site_password'
    if os.path.exists(secret_path):
        with open(secret_path, 'r') as f:
            SITE_PASSWORD = f.read().strip()

# Si toujours pas trouvé, on utilise la valeur par défaut (seulement si pas en prod idéalement, mais ici pour dépanner)
if not SITE_PASSWORD:
    SITE_PASSWORD = "viced1920" # Valeur par défaut demandée par l'utilisateur

# Security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self' https://cdn.discordapp.com; script-src 'self' 'unsafe-inline' https://cdn.discordapp.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https://cdn.discordapp.com; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self';"
    return response

# Global variable to store the bot process
# Note: In a production environment with multiple workers (gunicorn), this simple global approach 
# won't work correctly for tracking state across requests handled by different workers.
# However, for a simple single-user selfbot host, this is sufficient if running with 1 worker.
BOT_PROCESS = None

def run_bot_process(token):
    # Wrapper to run the bot
    selfbot.run_bot(token)

def get_discord_user_info(token):
    try:
        headers = {'Authorization': token}
        response = requests.get('https://discord.com/api/v9/users/@me', headers=headers)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Erreur récupération user info: {e}")
    return None

@app.route('/', methods=['GET', 'POST'])
def index():
    # Vérification du mot de passe du site
    if not session.get('site_access'):
        if request.method == 'POST':
            time.sleep(1) # Simple brute-force delay
            password = request.form.get('password')
            if password == SITE_PASSWORD:
                session['site_access'] = True
                return redirect(url_for('index'))
            else:
                return render_template('index.html', error="Mot de passe incorrect", step="password")
        return render_template('index.html', step="password")

    # Si on a l'accès site, on gère le token
    if request.method == 'POST':
        token = request.form.get('token')
        if token:
            # Clean token similar to selfbot.ask_token
            token = token.strip().strip('"').strip("'")
            # Vérifier si le token est valide
            user_info = get_discord_user_info(token)
            if user_info:
                session['token'] = token
                session['user_info'] = user_info
                return redirect(url_for('dashboard'))
            else:
                return render_template('index.html', error="Token invalide", step="token")
            
    if 'token' in session:
        return redirect(url_for('dashboard'))
        
    return render_template('index.html', step="token")

@app.route('/dashboard')
def dashboard():
    if not session.get('site_access'):
        return redirect(url_for('index'))
    if 'token' not in session:
        return redirect(url_for('index'))
    
    global BOT_PROCESS
    is_running = False
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        is_running = True
        
    user_info = session.get('user_info', {})
    return render_template('dashboard.html', token=session['token'], is_running=is_running, user=user_info)

@app.route('/start', methods=['POST'])
def start_bot():
    global BOT_PROCESS
    if 'token' not in session:
        return "Unauthorized", 401
    
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        return "Already running", 200
        
    token = session['token']
    # Start bot in a separate process
    BOT_PROCESS = multiprocessing.Process(target=run_bot_process, args=(token,))
    BOT_PROCESS.daemon = True
    BOT_PROCESS.start()
    
    # Wait a bit to see if it crashes immediately
    time.sleep(1)
    if not BOT_PROCESS.is_alive():
        return "Failed to start", 500
        
    return "Started", 200

@app.route('/stop', methods=['POST'])
def stop_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        BOT_PROCESS.terminate()
        BOT_PROCESS.join(timeout=0.1)
        if BOT_PROCESS.is_alive():
            BOT_PROCESS.kill()
            BOT_PROCESS.join()
        BOT_PROCESS = None
    return "Stopped", 200

@app.route('/logout')
def logout():
    session.pop('token', None)
    session.pop('site_access', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Fix for multiprocessing on Windows
    multiprocessing.freeze_support()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
