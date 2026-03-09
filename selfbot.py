import discord
from discord.ext import commands
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

class BotInstance:
    def __init__(self, token):
        self.token = token
        self.bot = commands.Bot(
            command_prefix=".",
            self_bot=True,
            help_command=None
        )
        self.is_running = False
        self.user_info = "Unknown"
        self.status = "Initialized"
        self.loop = asyncio.new_event_loop()
        
        # Enregistrement des événements et commandes
        self.setup_events()
        self.setup_commands()

    def setup_events(self):
        @self.bot.event
        async def on_ready():
            self.status = "Online"
            self.user_info = str(self.bot.user)
            logger.info(f"✅ Connecté en tant que {self.bot.user} (ID: {self.bot.user.id})")

    def setup_commands(self):
        @self.bot.command()
        async def ping(ctx):
            """Vérifie que le bot répond."""
            await ctx.message.delete()
            await ctx.send("🏓 Pong!", delete_after=5)

        @self.bot.command()
        async def stop(ctx):
            """Arrête le bot."""
            await ctx.message.delete()
            await ctx.send("🛑 Arrêt du bot...", delete_after=3)
            await self.bot.close()

    async def start_async(self):
        try:
            self.status = "Connecting..."
            await self.bot.start(self.token)
        except Exception as e:
            self.status = f"Error: {e}"
            logger.error(f"Erreur de connexion: {e}")
            raise e
        finally:
            self.is_running = False

    def stop_bot(self):
        if self.is_running:
            asyncio.run_coroutine_threadsafe(self.bot.close(), self.loop)

    def run_in_thread(self):
        asyncio.set_event_loop(self.loop)
        self.is_running = True
        try:
            self.loop.run_until_complete(self.start_async())
        except Exception as e:
            logger.error(f"Thread error: {e}")
        finally:
            self.is_running = False

# Gestionnaire global des instances de bots
# Dictionnaire : token -> instance
active_bots = {}

def get_bot(token):
    return active_bots.get(token)

def start_bot(token):
    if token in active_bots and active_bots[token].is_running:
        return active_bots[token]
    
    bot_instance = BotInstance(token)
    active_bots[token] = bot_instance
    
    import threading
    t = threading.Thread(target=bot_instance.run_in_thread, daemon=True)
    t.start()
    
    return bot_instance

def stop_bot(token):
    if token in active_bots:
        active_bots[token].stop_bot()
        del active_bots[token]
