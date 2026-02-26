#!/bin/bash

echo "=============================================="
echo "      RÉPARATION AUTOMATIQUE DU SELFBOT       "
echo "=============================================="

# 1. Forcer la mise à jour du code (écrase les modifications locales)
echo "🔄 Mise à jour forcée du code..."
git fetch --all
git reset --hard origin/main

# 2. Réinstaller l'environnement selfbot proprement
echo "🗑️  Nettoyage de l'ancien environnement..."
rm -rf selfbot_env

echo "📦 Réinstallation des dépendances..."
chmod +x install_selfbot.sh
./install_selfbot.sh

# 3. Redémarrer le service
echo "🚀 Redémarrage du bot manager..."
systemctl restart manager_bot

echo ""
echo "=============================================="
echo "✅ RÉPARATION TERMINÉE !"
echo "=============================================="
echo "Essayez de vous connecter maintenant."
