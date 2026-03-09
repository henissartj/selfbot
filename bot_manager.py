import discord
from discord.ext import commands
from discord import ui
import os
import asyncio
import logging
import sys
from selfbot_client import SelfbotClient
import threading

# Configuration Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("manager")

# Gestion des instances de Selfbots
# Dictionnaire : TOKEN -> instance de SelfbotClient
active_selfbots = {}

def get_bot_by_token(token):
    return active_selfbots.get(token)

def get_bot_by_owner(owner_id):
    for token, bot in active_selfbots.items():
        if bot.owner_id == owner_id:
            return bot
    return None

def start_selfbot_thread(token, owner_id=None):
    if token in active_selfbots and active_selfbots[token].is_running:
        return active_selfbots[token]

    # Si owner_id est None (via Web), il sera mis à jour au on_ready du bot
    client = SelfbotClient(token, owner_id)
    active_selfbots[token] = client
    
    def run_selfbot():
        asyncio.run(client.start_bot())

    thread = threading.Thread(target=run_selfbot, daemon=True)
    thread.start()
    return client

def stop_selfbot_by_token(token):
    if token in active_selfbots:
        bot = active_selfbots[token]
        asyncio.run_coroutine_threadsafe(bot.close(), bot.loop)
        # On ne supprime pas tout de suite du dict, on attend que ce soit closed, 
        # mais pour simplifier ici on le retire
        del active_selfbots[token]

class TokenModal(ui.Modal, title="Connexion Selfbot"):
    token = ui.TextInput(label="Votre Token Discord", placeholder="Mettez votre token ici...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        token_value = self.token.value.strip().replace('"', '')

        existing_bot = get_bot_by_owner(user_id)
        if existing_bot and existing_bot.is_running:
            await interaction.response.send_message("❌ Vous avez déjà un selfbot actif.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Tentative de connexion...", ephemeral=True)
        
        try:
            start_selfbot_thread(token_value, user_id)
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur au lancement : {e}", ephemeral=True)

class ControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) 

    @ui.button(label="Connexion", style=discord.ButtonStyle.green, custom_id="btn_connect")
    async def connect_button(self, interaction: discord.Interaction, button: ui.Button):
        existing_bot = get_bot_by_owner(interaction.user.id)
        if existing_bot and not existing_bot.is_closed():
             await interaction.response.send_message("✅ Votre selfbot est déjà en ligne.", ephemeral=True)
        else:
            await interaction.response.send_modal(TokenModal())

    @ui.button(label="Déconnexion", style=discord.ButtonStyle.red, custom_id="btn_disconnect")
    async def disconnect_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        bot = get_bot_by_owner(user_id)
        
        if bot:
            await bot.close()
            # Retrouver le token pour supprimer du dict
            token_to_remove = None
            for t, b in active_selfbots.items():
                if b == bot:
                    token_to_remove = t
                    break
            if token_to_remove:
                del active_selfbots[token_to_remove]
                
            await interaction.response.send_message("🛑 Selfbot arrêté.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Aucun selfbot actif trouvé pour vous.", ephemeral=True)

    @ui.button(label="Statut", style=discord.ButtonStyle.gray, custom_id="btn_status")
    async def status_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        bot = get_bot_by_owner(user_id)
        
        if bot and not bot.is_closed() and bot.is_ready():
             await interaction.response.send_message(f"✅ Votre selfbot est **EN LIGNE** (Connecté en tant que : {bot.user})", ephemeral=True)
        else:
             await interaction.response.send_message("⚪ Votre selfbot est **HORS LIGNE**.", ephemeral=True)

class BotManager(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def on_ready(self):
        logger.info(f"🤖 Manager connecté en tant que {self.user}")
        self.add_view(ControlView())

    async def setup_hook(self):
        self.add_view(ControlView())

manager = BotManager()

@manager.command()
# @commands.is_owner() # Retiré pour permettre l'usage général si besoin, ou réactiver si vous voulez être le seul à lancer le panel
async def panel(ctx):
    """Affiche le panel de contrôle"""
    embed = discord.Embed(
        title="Panel de Contrôle Selfbot",
        description="Utilisez les boutons ci-dessous pour gérer votre selfbot.\n\n**État actuel**\nCliquez sur Statut pour vérifier",
        color=0x2b2d31
    )
    embed.set_author(name="SELFBOT \\\ L'EMPRISE", icon_url=manager.user.avatar.url if manager.user.avatar else None)
    embed.set_footer(text="Gestionnaire de Selfbot")
    
    await ctx.send(embed=embed, view=ControlView())

def run():
    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        logger.error("❌ DISCORD_TOKEN manquant !")
        return
    manager.run(token)
