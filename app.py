from flask import Flask, render_template, request, redirect, url_for, session
import multiprocessing
import selfbot
import os
import signal
import sys
import requests
import secrets
import time
from token_manager import TokenManager

app = Flask(__name__)
token_manager = TokenManager()
# Use a fixed secret key or environment variable to prevent logout on restart
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_selfbot_12345')

# CSRF Protection
@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get('csrf_token')
        header_token = request.headers.get('X-CSRFToken')
        form_token = request.form.get('csrf_token')
        
        if not token or (token != header_token and token != form_token):
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
# We use a PID file to track the process across workers
PID_FILE = "bot.pid"

def is_bot_running():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if process exists
            # On Windows, we can use psutil if available, or just assume it's running if file exists
            # but for cross-platform (and Render/Linux), sending signal 0 checks existence
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                # Process not found
                return False
        except (ValueError, Exception):
            return False
    return False

def run_bot_process(token):
    # Wrapper to run the bot
    # Write PID to file
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
        
    try:
        selfbot.run_bot(token)
    except Exception as e:
        print(f"Bot process crashed: {e}", file=sys.stderr)
    finally:
        # Cleanup PID file on exit
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except:
                pass

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
        # Cas 1: Nouveau token
        token = request.form.get('token')
        if token:
            # Clean token similar to selfbot.ask_token
            token = token.strip().strip('"').strip("'")
            # Vérifier si le token est valide
            user_info = get_discord_user_info(token)
            if user_info:
                # Sauvegarder le token
                token_manager.save_token(user_info, token)
                
                session['token'] = token
                session['user_info'] = user_info
                return redirect(url_for('dashboard'))
            else:
                return render_template('index.html', error="Token invalide", step="token", saved_tokens=token_manager.load_tokens())
        
        # Cas 2: Sélection d'un profil existant
        profile_id = request.form.get('profile_id')
        if profile_id:
            saved_data = token_manager.get_token(profile_id)
            if saved_data:
                session['token'] = saved_data['token']
                # Reconstruire user_info minimal pour l'affichage
                session['user_info'] = {
                    'id': saved_data['id'],
                    'username': saved_data['username'],
                    'discriminator': saved_data['discriminator'],
                    'avatar': saved_data['avatar_url'].split('/')[-1].split('.')[0] if 'avatars' in saved_data['avatar_url'] else None
                }
                return redirect(url_for('dashboard'))

    if 'token' in session:
        return redirect(url_for('dashboard'))
        
    # Charger les profils sauvegardés
    saved_tokens = token_manager.load_tokens()
    return render_template('index.html', step="token", saved_tokens=saved_tokens)

@app.route('/delete_profile/<profile_id>', methods=['POST'])
def delete_profile(profile_id):
    if not session.get('site_access'):
        return redirect(url_for('index'))
    
    token_manager.delete_token(profile_id)
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if not session.get('site_access'):
        return redirect(url_for('index'))
    if 'token' not in session:
        return redirect(url_for('index'))
    
    is_running = is_bot_running()
        
    user_info = session.get('user_info', {})
    return render_template('dashboard.html', token=session['token'], is_running=is_running, user=user_info)

@app.route('/start', methods=['POST'])
def start_bot():
    if 'token' not in session:
        return "Unauthorized", 401
    
    if is_bot_running():
        return "Already running", 200
        
    token = session['token']
    # Start bot in a separate process
    # Note: On Windows with Flask reloader, this might spawn recursively if not careful.
    # But since we use multiprocessing.Process with target function, it should be fine.
    p = multiprocessing.Process(target=run_bot_process, args=(token,))
    p.daemon = True
    p.start()
    
    # Wait a bit to see if it crashes immediately
    time.sleep(2)
    if not is_bot_running():
        return "Failed to start", 500
        
    return "Started", 200

@app.route('/stop', methods=['POST'])
def stop_bot():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM) # Or SIGKILL if stubborn
            # Wait for it to die
            time.sleep(1)
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except:
            pass
            
    return "Stopped", 200

@app.route('/toggle', methods=['POST'])
def toggle_bot():
    if 'token' not in session:
        return redirect(url_for('index'))
    
    action = request.form.get('action')
    
    if action == 'start':
        if not is_bot_running():
            token = session['token']
            # Start bot in a separate process
            p = multiprocessing.Process(target=run_bot_process, args=(token,))
            p.daemon = True
            p.start()
            
            # Wait a bit to see if it crashes immediately
            time.sleep(2)
    
    elif action == 'stop':
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                # Force cleanup if still exists
                if os.path.exists(PID_FILE):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
                    try:
                        os.remove(PID_FILE)
                    except:
                        pass
            except Exception as e:
                print(f"Error stopping bot: {e}")
                # Try to clean up file anyway
                if os.path.exists(PID_FILE):
                    os.remove(PID_FILE)
            
    return redirect(url_for('dashboard'))

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('token', None)
    session.pop('site_access', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Fix for multiprocessing on Windows
    multiprocessing.freeze_support()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
