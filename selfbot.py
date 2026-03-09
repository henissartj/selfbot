import discord
from discord.ext import commands
import os
import json
import logging
import asyncio
import sys

# Configuration du Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("selfbot")

# Configuration par défaut
DEFAULT_CONFIG = {
    "token": "",
    "prefix": ".",
    "whitelist": []
}

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG.copy()

CONFIG = load_config()

# Récupération du token (Priorité: Env Var > Config > Input)
TOKEN = os.environ.get("DISCORD_TOKEN") or CONFIG.get("token")

# Initialisation du Bot
bot = commands.Bot(
    command_prefix=CONFIG.get("prefix", "."),
    self_bot=True,  # Important pour discord.py-self
    help_command=None
)

@bot.event
async def on_ready():
    logger.info(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    logger.info(f"Prefixe: {bot.command_prefix}")

@bot.command()
async def ping(ctx):
    """Vérifie que le bot répond."""
    await ctx.message.delete()
    await ctx.send("🏓 Pong!", delete_after=5)

@bot.command()
async def stop(ctx):
    """Arrête le bot (Redémarrage automatique sur Render)."""
    await ctx.message.delete()
    await ctx.send("🛑 Arrêt en cours...", delete_after=3)
    await bot.close()

def run():
    global TOKEN
    if not TOKEN:
        logger.warning("Aucun token trouvé ! Configurez DISCORD_TOKEN ou config.json")
        return
    
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Erreur au lancement: {e}")

if __name__ == "__main__":
    run()
