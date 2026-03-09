from flask import Flask, render_template_string
import threading
import os
import selfbot
import time

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Selfbot Status</title>
    <style>
        body { font-family: sans-serif; text-align: center; padding: 50px; background-color: #1a1a1a; color: #fff; }
        .status { padding: 20px; border-radius: 10px; display: inline-block; margin: 20px 0; }
        .online { background-color: #2ecc71; color: white; }
        .error { background-color: #e74c3c; color: white; }
        .warning { background-color: #f39c12; color: white; }
        .info { background-color: #3498db; color: white; }
    </style>
</head>
<body>
    <h1>🤖 Selfbot Dashboard</h1>
    
    <div class="status {{ status_class }}">
        Status: <strong>{{ status }}</strong>
    </div>

    {% if user != "Unknown" %}
    <p>Logged in as: <strong>{{ user }}</strong></p>
    {% endif %}

    {% if "Missing Token" in status %}
    <div style="margin-top: 30px; text-align: left; max-width: 600px; margin-left: auto; margin-right: auto; background: #333; padding: 20px; border-radius: 5px;">
        <h3>⚠️ Action Requise : Configuration du Token</h3>
        <p>Le bot ne peut pas démarrer car le token Discord est manquant.</p>
        <p><strong>Sur Render :</strong></p>
        <ol>
            <li>Allez dans le Dashboard Render > Votre Service</li>
            <li>Cliquez sur l'onglet <strong>Environment</strong></li>
            <li>Ajoutez une variable : <code>DISCORD_TOKEN</code></li>
            <li>Valeur : Votre token Discord</li>
            <li>Sauvegardez. Le bot redémarrera automatiquement.</li>
        </ol>
    </div>
    {% endif %}

    <p style="margin-top: 50px; color: #777; font-size: 0.8em;">Auto-refresh in 10s</p>
    <script>setTimeout(function(){location.reload()}, 10000);</script>
</body>
</html>
"""

@app.route('/')
def index():
    status = selfbot.BOT_STATUS
    user = getattr(selfbot, 'BOT_USER', 'Unknown')
    
    status_class = "info"
    if status == "Online":
        status_class = "online"
    elif "Error" in status or "Missing" in status:
        status_class = "error"
    elif "Starting" in status or "Connecting" in status:
        status_class = "warning"

    return render_template_string(HTML_TEMPLATE, status=status, status_class=status_class, user=user)

def run_bot():
    # Petit délai pour laisser Flask démarrer
    time.sleep(2)
    selfbot.run()

# Démarrer le bot dans un thread séparé
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
