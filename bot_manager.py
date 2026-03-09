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
# Dictionnaire : user_id -> instance de SelfbotClient
active_selfbots = {}

class TokenModal(ui.Modal, title="Connexion Selfbot"):
    token = ui.TextInput(label="Votre Token Discord", placeholder="Mettez votre token ici...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        token_value = self.token.value.strip().replace('"', '')

        if user_id in active_selfbots and active_selfbots[user_id].is_running:
            await interaction.response.send_message("❌ Vous avez déjà un selfbot actif.", ephemeral=True)
            return

        await interaction.response.send_message("⏳ Tentative de connexion...", ephemeral=True)

        # Lancement du selfbot dans un thread séparé pour ne pas bloquer le bot manager
        try:
            client = SelfbotClient(token_value, user_id)
            active_selfbots[user_id] = client
            
            def run_selfbot():
                asyncio.run(client.start_bot())

            thread = threading.Thread(target=run_selfbot, daemon=True)
            thread.start()
            
            # On attend un peu pour voir si ça connecte (c'est asynchrone donc approximatif ici)
            # Dans une vraie implémentation robuste, il faudrait un callback.
            
        except Exception as e:
            await interaction.followup.send(f"❌ Erreur au lancement : {e}", ephemeral=True)

class ControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Vue persistante

    @ui.button(label="Connexion", style=discord.ButtonStyle.green, custom_id="btn_connect")
    async def connect_button(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id in active_selfbots and active_selfbots[interaction.user.id].is_closed() is False:
             await interaction.response.send_message("✅ Votre selfbot est déjà en ligne.", ephemeral=True)
        else:
            await interaction.response.send_modal(TokenModal())

    @ui.button(label="Déconnexion", style=discord.ButtonStyle.red, custom_id="btn_disconnect")
    async def disconnect_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id in active_selfbots:
            bot = active_selfbots[user_id]
            await bot.close()
            del active_selfbots[user_id]
            await interaction.response.send_message("🛑 Selfbot arrêté.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Aucun selfbot actif trouvé.", ephemeral=True)

    @ui.button(label="Statut", style=discord.ButtonStyle.gray, custom_id="btn_status")
    async def status_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = interaction.user.id
        if user_id in active_selfbots and not active_selfbots[user_id].is_closed():
             await interaction.response.send_message(f"✅ Votre selfbot est **EN LIGNE** (Connecté en tant que : {active_selfbots[user_id].user})", ephemeral=True)
        else:
             await interaction.response.send_message("⚪ Votre selfbot est **HORS LIGNE**.", ephemeral=True)

class BotManager(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def on_ready(self):
        logger.info(f"🤖 Manager connecté en tant que {self.user}")
        # On ajoute la vue persistante pour qu'elle fonctionne après redémarrage
        self.add_view(ControlView())

    async def setup_hook(self):
        # Permet de charger la vue persistante avant que le bot soit prêt
        self.add_view(ControlView())

# Instance globale
manager = BotManager()

@manager.command()
@commands.is_owner()
async def panel(ctx):
    """Affiche le panel de contrôle (Admin seulement)"""
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
        logger.error("❌ DISCORD_TOKEN manquant dans les variables d'environnement !")
        return
    manager.run(token)

if __name__ == "__main__":
    run()
