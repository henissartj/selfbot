import discord
from discord.ext import commands
import asyncio
import logging

# Logger spécifique pour les selfbots
logger = logging.getLogger("selfbot_client")

class SelfbotClient(commands.Bot):
    def __init__(self, token, owner_id):
        super().__init__(command_prefix=".", self_bot=True, help_command=None)
        self.token = token
        self.owner_id = owner_id # ID de l'utilisateur qui a lancé ce selfbot
        self.is_running = False
        self.remove_command("help")

    async def on_ready(self):
        self.is_running = True
        logger.info(f"✅ Selfbot connecté: {self.user} (pour l'utilisateur {self.owner_id})")

    async def on_message(self, message):
        # Ne traiter que ses propres messages
        if message.author.id != self.user.id:
            return
        await self.process_commands(message)

    # --- Commandes du Selfbot ---
    async def cmd_ping(self, ctx):
        await ctx.message.delete()
        await ctx.send("🏓 Pong!", delete_after=5)

    async def cmd_stop(self, ctx):
        await ctx.message.delete()
        await ctx.send("🛑 Arrêt du selfbot...", delete_after=3)
        await self.close()

    def setup_commands(self):
        self.add_command(commands.Command(self.cmd_ping, name="ping"))
        self.add_command(commands.Command(self.cmd_stop, name="stop"))

    async def start_bot(self):
        self.setup_commands()
        try:
            await self.start(self.token)
        except Exception as e:
            logger.error(f"Erreur selfbot {self.owner_id}: {e}")
            raise e
