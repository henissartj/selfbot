import discord
from discord.ext import commands
from discord import ui
import os
import bot_manager
import asyncio

# Retrieve the token from environment variable
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    print("Erreur: La variable d'environnement DISCORD_TOKEN n'est pas définie.")
    exit(1)

# Intents are required for message content (to read !setup)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

class TokenModal(ui.Modal, title="Connexion Selfbot"):
    token_input = ui.TextInput(
        label="Token Discord",
        placeholder="Entrez votre token ici...",
        style=discord.TextStyle.short,
        required=True,
        min_length=50, # Tokens are usually long
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        token = self.token_input.value.strip().strip('"').strip("'")
        
        # Check if already running
        if bot_manager.is_bot_running():
            await interaction.response.send_message("Le selfbot est déjà en ligne !", ephemeral=True)
            return

        # Start the bot
        success, message = bot_manager.start_bot(token)
        
        if success:
            await interaction.response.send_message(f"✅ {message}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Erreur: {message}", ephemeral=True)

class ControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    @ui.button(label="Connexion", style=discord.ButtonStyle.green, custom_id="selfbot_connect")
    async def connect_button(self, interaction: discord.Interaction, button: ui.Button):
        if bot_manager.is_bot_running():
            await interaction.response.send_message("Le selfbot est déjà en ligne !", ephemeral=True)
        else:
            await interaction.response.send_modal(TokenModal())

    @ui.button(label="Déconnexion", style=discord.ButtonStyle.red, custom_id="selfbot_disconnect")
    async def disconnect_button(self, interaction: discord.Interaction, button: ui.Button):
        if not bot_manager.is_bot_running():
            await interaction.response.send_message("Le selfbot n'est pas en ligne.", ephemeral=True)
            return
        
        success, message = bot_manager.stop_bot()
        if success:
            await interaction.response.send_message("🛑 Selfbot arrêté avec succès.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Erreur lors de l'arrêt: {message}", ephemeral=True)

    @ui.button(label="Statut", style=discord.ButtonStyle.grey, custom_id="selfbot_status")
    async def status_button(self, interaction: discord.Interaction, button: ui.Button):
        is_running = bot_manager.is_bot_running()
        status_text = "🟢 EN LIGNE" if is_running else "🔴 HORS LIGNE"
        await interaction.response.send_message(f"Statut du Selfbot: **{status_text}**", ephemeral=True)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")
    print("Prêt à gérer le selfbot.")

@bot.command()
async def setup(ctx):
    embed = discord.Embed(
        title="Panel de Contrôle Selfbot",
        description="Utilisez les boutons ci-dessous pour gérer votre selfbot.",
        color=discord.Color.blue()
    )
    embed.add_field(name="État actuel", value="Cliquez sur Statut pour vérifier", inline=False)
    embed.set_footer(text="Gestionnaire de Selfbot")
    
    await ctx.send(embed=embed, view=ControlView())

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
