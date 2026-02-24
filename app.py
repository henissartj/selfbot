from flask import Flask, render_template, request, redirect, url_for, session
import multiprocessing
import selfbot
import os
import signal
import sys

app = Flask(__name__)
# Use a fixed secret key or environment variable to prevent logout on restart
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_selfbot_12345')

# Security headers middleware
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:;"
    return response

# Global variable to store the bot process
# Note: In a production environment with multiple workers (gunicorn), this simple global approach 
# won't work correctly for tracking state across requests handled by different workers.
# However, for a simple single-user selfbot host, this is sufficient if running with 1 worker.
BOT_PROCESS = None

def run_bot_process(token):
    # Wrapper to run the bot
    selfbot.run_bot(token)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        token = request.form.get('token')
        if token:
            # Clean token similar to selfbot.ask_token
            token = token.strip().strip('"').strip("'")
            session['token'] = token
            return redirect(url_for('dashboard'))
            
    if 'token' in session:
        return redirect(url_for('dashboard'))
        
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    if 'token' not in session:
        return redirect(url_for('index'))
    
    global BOT_PROCESS
    is_running = False
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        is_running = True
        
    return render_template('dashboard.html', token=session['token'], is_running=is_running)

@app.route('/start', methods=['POST'])
def start_bot():
    global BOT_PROCESS
    if 'token' not in session:
        return redirect(url_for('index'))
    
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        return redirect(url_for('dashboard'))
        
    token = session['token']
    # Start bot in a separate process
    BOT_PROCESS = multiprocessing.Process(target=run_bot_process, args=(token,))
    BOT_PROCESS.daemon = True
    BOT_PROCESS.start()
    return redirect(url_for('dashboard'))

@app.route('/stop', methods=['POST'])
def stop_bot():
    global BOT_PROCESS
    if BOT_PROCESS and BOT_PROCESS.is_alive():
        BOT_PROCESS.terminate()
        BOT_PROCESS.join()
        BOT_PROCESS = None
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    # Optional: Stop bot on logout? 
    # Usually users want the bot to keep running even if they close the tab.
    # But if they logout explicitly, maybe stop it? 
    # Let's keep it running unless they click stop.
    session.pop('token', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Fix for multiprocessing on Windows
    multiprocessing.freeze_support()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
