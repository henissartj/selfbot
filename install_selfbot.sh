#!/bin/bash

# Configuration
ENV_NAME="selfbot_env"
PYTHON_BIN="python3"

echo "=============================================="
echo "      INSTALLATION DU SELFBOT (DÉPENDANCES)   "
echo "=============================================="

# Vérifier si python3 est installé
if ! command -v $PYTHON_BIN &> /dev/null; then
    echo "❌ Erreur: python3 n'est pas installé."
    exit 1
fi

# Créer l'environnement virtuel s'il n'existe pas
if [ ! -d "$ENV_NAME" ]; then
    echo "📦 Création de l'environnement virtuel '$ENV_NAME'..."
    $PYTHON_BIN -m venv $ENV_NAME
else
    echo "✅ L'environnement virtuel '$ENV_NAME' existe déjà."
fi

# Activer l'environnement et installer les dépendances
source $ENV_NAME/bin/activate

echo "⬇️  Installation de discord.py-self..."
pip install --upgrade pip
# Force uninstall standard discord.py if present
pip uninstall -y discord.py
pip install "discord.py-self==1.9.2"
pip install requests aiohttp
# PyNaCl est optionnel mais recommandé pour la voix
pip install PyNaCl

echo ""
echo "=============================================="
echo "✅ INSTALLATION TERMINÉE AVEC SUCCÈS !"
echo "=============================================="
echo "Le selfbot utilisera désormais cet environnement isolé."
echo "Vous pouvez relancer le manager bot."
echo "=============================================="
