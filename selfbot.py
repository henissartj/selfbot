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
from datetime import datetime
from typing import Optional, List

try:
    import tkinter as tk
    from tkinter import scrolledtext, messagebox
except ImportError:
    tk = None

import discord
from discord.ext import commands
import aiohttp

# ──────────────────────────────────────────────────────────────────────────────
#                          CONFIGURATION GLOBALE
# ──────────────────────────────────────────────────────────────────────────────

# Préfixes pour les commandes
PREFIXES = [".", "!", "+", "-", "?"]

# Token (sera demandé au lancement)
TOKEN = None

# Configuration Anti-Raid (modules activables/désactivables)
ANTIRAID_MODULES = {
    "antispam": True,           # Anti-spam rapide
    "antimassmention": True,    # Anti-mass mentions
    "antichannelcreate": True,  # Anti-création de salons
    "antichanneldelete": True,  # Anti-suppression de salons
    "antirolecreate": True,     # Anti-création de rôles
    "antiroledelete": True,     # Anti-suppression de rôles
    "antibotjoin": True,        # Anti-ajout de bots
    "antiban": True,            # Anti-ban non autorisé
    "antiunban": True,          # Anti-unban non autorisé
    "antikick": True,           # Anti-kick non autorisé
    "antiwebhook": True,        # Anti-création de webhooks
    "antiupdate": True,         # Anti-modification du serveur
    "antieveryone": True,       # Anti-@everyone/@here
    "antilink": True,           # Anti-liens
    "antitoken": True,          # Anti-leak de tokens
    "antirank": True,           # Anti-ajout de rôles admin
    "protected": True,          # Protection globale
}

# Whitelist des utilisateurs protégés (IDs)
WHITELIST: set[int] = set()

# Cache pour anti-spam (par user ID)
spam_cache: collections.defaultdict = collections.defaultdict(list)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("selfbot.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
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
        case_insensitive=True
    )
except Exception:
    # Fallback si discord.py-self non installé (standard discord.py requires intents)
    # Re-enable intents locally if needed for standard discord.py
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(
        command_prefix=PREFIXES,
        intents=intents,
        case_insensitive=True
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
    logger.info(f"Préfixes: {', '.join(PREFIXES)}")
    logger.info(f"Guilds connectés: {len(bot.guilds)}")
    # Pas de changement de statut automatique (reste en ligne ou reprend le statut du client)

@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Gestion des erreurs de commandes."""
    if isinstance(error, commands.CommandNotFound):
        return
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
    if not message.guild or message.author.bot:
        await bot.process_commands(message)
        return

    if message.author.id == bot.user.id or message.author.id in WHITELIST:
        await bot.process_commands(message)
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

# ──────────────────────────────────────────────────────────────────────────────
#                               COMMANDES
# ──────────────────────────────────────────────────────────────────────────────

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
                ".nuke - Détruit le serveur (channels, roles)",
                ".raid <nb> <msg> - Mass ping + delete channels",
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
                ".massban - Ban tous les membres possibles",
                ".masskick - Kick tous les membres possibles",
                ".massrole <action> <nb> [nom] - Crée/Supprime rôles",
                ".channelspam <nb> [nom] - Crée plein de salons"
            ]
        },
        "antiraid": {
            "title": "Anti-Raid / Protection",
            "icon": "🛡️",
            "cmds": [
                ".antiraid [module] [on/off] - Configure modules",
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
        "troll": {
            "title": "Troll / Fun",
            "icon": "🤡",
            "cmds": [
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
    # await safe_send(ctx.channel, f"Pong! Latence: {latency}ms", delete_after=10)
    print(f"Pong! Latence: {latency}ms")

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
    count = 0
    for channel in bot.private_channels:
        async for msg in channel.history(limit=None):
            if msg.author == bot.user:
                await safe_delete(msg)
                count += 1
                await asyncio.sleep(random_delay(0.3, 0.8))
    # await safe_send(ctx.channel, f"{count} messages supprimés en DM.", delete_after=10)
    print(f"{count} messages supprimés en DM.")

@bot.command()
async def nuke(ctx: commands.Context):
    """Nuke le serveur: supprime channels et roles."""
    await safe_delete(ctx.message)
    guild = ctx.guild
    tasks = []
    for channel in list(guild.channels):
        tasks.append(channel.delete(reason="Nuke"))
    for role in list(guild.roles):
        if role != guild.default_role:
            tasks.append(role.delete(reason="Nuke"))
    await asyncio.gather(*tasks, return_exceptions=True)
    await guild.create_text_channel("nuked")
    # await safe_send(ctx.channel, "Serveur nuké!", delete_after=5)

@bot.command()
async def raid(ctx: commands.Context, amount: int, *, message: str):
    """Mass ping + delete channels."""
    await safe_delete(ctx.message)
    guild = ctx.guild
    members = guild.members
    for _ in range(amount):
        mentions = " ".join(m.mention for m in random.sample(members, min(50, len(members))))
        await safe_send(ctx.channel, f"{mentions} {message}")
        await asyncio.sleep(random_delay())
    for channel in list(guild.channels):
        await channel.delete(reason="Raid")
    # await safe_send(ctx.channel, "Raid terminé.", delete_after=5)

@bot.command()
async def spam(ctx: commands.Context, amount: int, *, message: str):
    """Spam dans le salon."""
    await safe_delete(ctx.message)
    for _ in range(min(amount, 50)):  # Limite pour éviter ban
        await safe_send(ctx.channel, message)
        await asyncio.sleep(random_delay(0.6, 1.5))

@bot.command()
async def spamid(ctx: commands.Context, user_id: int, amount: int, *, message: str):
    """Spam MP à un user par ID."""
    await safe_delete(ctx.message)
    user = await bot.fetch_user(user_id)
    if not user:
        # await safe_send(ctx.channel, "User introuvable.", delete_after=5)
        return
    for _ in range(min(amount, 20)):
        await user.send(message)
        await asyncio.sleep(random_delay(1.0, 3.0))

@bot.command()
async def spamall(ctx: commands.Context, amount: int, *, message: str):
    """Spam MP à tous les membres."""
    await safe_delete(ctx.message)
    await ctx.guild.chunk()
    members = [m for m in ctx.guild.members if not m.bot and m != ctx.author]
    for member in members:
        for _ in range(amount):
            try:
                await member.send(message)
                await asyncio.sleep(random_delay(1.5, 4.0))
            except:
                pass
    await safe_send(ctx.channel, "Spamall terminé.", delete_after=10)

@bot.command()
async def massdm(ctx: commands.Context, *, message: str):
    """DM unique à tous les membres."""
    await safe_delete(ctx.message)
    await ctx.guild.chunk()
    members = [m for m in ctx.guild.members if not m.bot and m != ctx.author]
    count = 0
    for member in members:
        try:
            await member.send(message)
            count += 1
            await asyncio.sleep(random_delay(2.0, 5.0))
        except:
            pass
    await safe_send(ctx.channel, f"{count} DM envoyés.", delete_after=10)

@bot.command()
async def webhookspam(ctx: commands.Context, url: str, amount: int, *, message: str):
    """Spam via webhook."""
    await safe_delete(ctx.message)
    async with aiohttp.ClientSession() as session:
        webhook = discord.Webhook.from_url(url, session=session)
        for _ in range(min(amount, 50)):
            await webhook.send(message)
            await asyncio.sleep(random_delay(0.8, 2.0))

@bot.command()
async def everyone(ctx: commands.Context, amount: int, *, message: str = ""):
    """Spam @everyone."""
    await safe_delete(ctx.message)
    for _ in range(min(amount, 15)):
        await safe_send(ctx.channel, f"@everyone {message}")
        await asyncio.sleep(random_delay(1.0, 2.5))

@bot.command()
async def here(ctx: commands.Context, amount: int, *, message: str = ""):
    """Spam @here."""
    await safe_delete(ctx.message)
    for _ in range(min(amount, 15)):
        await safe_send(ctx.channel, f"@here {message}")
        await asyncio.sleep(random_delay(1.0, 2.5))

@bot.command()
async def scramble(ctx: commands.Context):
    """Renomme tous les salons aléatoirement."""
    await safe_delete(ctx.message)
    for channel in ctx.guild.channels:
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
    for _ in range(min(amount, 5)):  # Limite Discord ~100 guilds
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
    for member in ctx.guild.members:
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
    """Ban tous les membres possibles."""
    await safe_delete(ctx.message)
    count = 0
    for member in list(ctx.guild.members):
        if member.top_role >= ctx.me.top_role or member == ctx.author:
            continue
        try:
            await member.ban(reason="Mass Ban")
            count += 1
            await asyncio.sleep(random_delay(1.2, 3.0))
        except:
            pass
    await safe_send(ctx.channel, f"{count} bannis.", delete_after=10)

@bot.command()
async def masskick(ctx: commands.Context):
    """Kick tous les membres possibles."""
    await safe_delete(ctx.message)
    count = 0
    for member in list(ctx.guild.members):
        if member.top_role >= ctx.me.top_role or member == ctx.author:
            continue
        try:
            await member.kick(reason="Mass Kick")
            count += 1
            await asyncio.sleep(random_delay(1.0, 2.5))
        except:
            pass
    await safe_send(ctx.channel, f"{count} kickés.", delete_after=10)

@bot.command()
async def antiraid(ctx: commands.Context, module: Optional[str] = None, state: Optional[str] = None):
    """Configure les modules anti-raid."""
    await safe_delete(ctx.message)
    if not module:
        status = "\n".join(f"{k}: {'ON' if v else 'OFF'}" for k, v in ANTIRAID_MODULES.items())
        await safe_send(ctx.channel, f"```yaml\n{status}\n```", delete_after=30)
        return

    module = module.lower()
    if module not in ANTIRAID_MODULES:
        await safe_send(ctx.channel, "Module inconnu.", delete_after=5)
        return

    if state and state.lower() in ["on", "true", "enable"]:
        ANTIRAID_MODULES[module] = True
        await safe_send(ctx.channel, f"{module} activé.", delete_after=5)
    elif state and state.lower() in ["off", "false", "disable"]:
        ANTIRAID_MODULES[module] = False
        await safe_send(ctx.channel, f"{module} désactivé.", delete_after=5)
    else:
        await safe_send(ctx.channel, "Usage: .antiraid <module> <on/off>", delete_after=5)

@bot.command()
async def whitelist(ctx: commands.Context, member: discord.Member):
    """Ajoute un user à la whitelist."""
    await safe_delete(ctx.message)
    WHITELIST.add(member.id)
    await safe_send(ctx.channel, f"{member} ajouté à la whitelist.", delete_after=5)

@bot.command()
async def unwhitelist(ctx: commands.Context, member: discord.Member):
    """Retire un user de la whitelist."""
    await safe_delete(ctx.message)
    if member.id in WHITELIST:
        WHITELIST.remove(member.id)
        await safe_send(ctx.channel, f"{member} retiré de la whitelist.", delete_after=5)

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
        logger.error(f"Token invalide ou connexion refusée par Discord. Détails: {e}")
        logger.error("Vérifiez que le token est correct et qu'il n'est pas expiré.")
        logger.error("Si vous êtes sur un VPS, Discord a peut-être bloqué l'IP (Geo-lock).")
    except Exception as e:
        logger.error(f"Erreur démarrage: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    TOKEN = ask_token()
    run_bot(TOKEN)