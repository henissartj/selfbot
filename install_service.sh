#!/bin/bash

# Vérifier si l'utilisateur est root
if [ "$EUID" -ne 0 ]; then 
  echo "❌ Erreur: Veuillez lancer ce script en tant que root (sudo ./install_service.sh)"
  exit 1
fi

echo "=============================================="
echo "      INSTALLATION DU SERVICE MANAGER BOT     "
echo "=============================================="

# Récupérer le dossier actuel
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PYTHON_BIN="$DIR/manager_env/bin/python"

# Vérifier si l'environnement virtuel existe
if [ ! -f "$PYTHON_BIN" ]; then
    echo "⚠️  L'environnement virtuel 'manager_env' n'a pas été trouvé."
    echo "    Tentative d'utilisation de 'python3' par défaut..."
    PYTHON_BIN=$(which python3)
fi

echo "📂 Dossier du bot : $DIR"
echo "🐍 Python utilisé : $PYTHON_BIN"
echo ""

# Demander le Token du Bot Manager
echo "Entrez le TOKEN de votre BOT Manager (celui du Portail Développeur Discord) :"
read -p "> " DISCORD_TOKEN

if [ -z "$DISCORD_TOKEN" ]; then
    echo "❌ Erreur: Le token ne peut pas être vide !"
    exit 1
fi

SERVICE_FILE="/etc/systemd/system/manager_bot.service"

echo ""
echo "⚙️  Création du fichier service systemd..."

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Discord Selfbot Manager
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$DIR
ExecStart=$PYTHON_BIN $DIR/manager_bot.py
Restart=always
RestartSec=10
Environment="DISCORD_TOKEN=$DISCORD_TOKEN"
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

echo "🔄 Rechargement des services..."
systemctl daemon-reload

echo "✅ Activation du service au démarrage..."
systemctl enable manager_bot

echo "🚀 Démarrage du bot..."
systemctl restart manager_bot

echo ""
echo "=============================================="
echo "✅ INSTALLATION TERMINÉE AVEC SUCCÈS !"
echo "=============================================="
echo "Le bot tourne maintenant en arrière-plan 24/7."
echo ""
echo "Commandes utiles :"
echo "📜 Voir les logs : journalctl -u manager_bot -f"
echo "🛑 Stopper le bot : systemctl stop manager_bot"
echo "▶️  Relancer le bot : systemctl restart manager_bot"
echo "=============================================="
