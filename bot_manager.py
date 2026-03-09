import discord
from discord.ext import commands
import os
import threading
import asyncio
import logging

# Configuration logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot_manager")

# Configuration du bot manager (Le bot officiel du serveur)
# On utilise discord.py-self mais configuré comme un vrai bot si possible,
# ou comme un selfbot si l'utilisateur met un token utilisateur.
# Pour un vrai bot, il faut un token de bot.

class BotManager:
    def __init__(self):
        self.token = os.getenv("MANAGER_TOKEN")
        self.prefix = os.getenv("MANAGER_PREFIX", "!")
        
        # On tente de détecter si c'est un token bot ou user
        # En général, on assume que c'est un bot classique pour le manager
        # Mais avec discord.py-self, il faut faire attention
        
        # self_bot=False permet d'utiliser le bot comme un bot classique
        self.bot = commands.Bot(command_prefix=self.prefix, self_bot=False, help_command=None)
        self.is_running = False
        self.loop = asyncio.new_event_loop()

        self.setup_events()
        self.setup_commands()

    def setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f"✅ Bot Manager connecté en tant que {self.bot.user}")
            # Mettre un statut
            await self.bot.change_presence(activity=discord.Game(name=f"{self.prefix}panel | Gestion"))

    def setup_commands(self):
        @self.bot.command(name="panel")
        async def panel(ctx):
            """Envoie le lien vers le panel web"""
            render_url = os.getenv("RENDER_EXTERNAL_URL", "https://votre-app.onrender.com")
            
            embed = discord.Embed(
                title="🎛️ Panel de Gestion Selfbot",
                description=f"Connectez-vous au panel pour gérer votre selfbot.\n\n[🔗 Accéder au Panel]({render_url})",
                color=0x5865F2
            )
            embed.set_footer(text="Selfbot Manager")
            
            await ctx.send(embed=embed)
            
        @self.bot.command(name="ping")
        async def ping(ctx):
            await ctx.send(f"🏓 Pong! {round(self.bot.latency * 1000)}ms")

    def run(self):
        if not self.token:
            logger.warning("⚠️ MANAGER_TOKEN n'est pas défini. Le bot manager ne démarrera pas.")
            return

        asyncio.set_event_loop(self.loop)
        self.is_running = True
        
        try:
            self.loop.run_until_complete(self.bot.start(self.token))
        except Exception as e:
            logger.error(f"Erreur du Bot Manager: {e}")
        finally:
            self.is_running = False

# Instance globale
manager = BotManager()

def start_manager():
    if not manager.is_running and manager.token:
        t = threading.Thread(target=manager.run, daemon=True)
        t.start()
        return True
    return False
