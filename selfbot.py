import asyncio
import threading
try:
    import tkinter as tk
    from tkinter import scrolledtext, messagebox
except ImportError:
    tk = None

import discord
from discord.ext import commands
import random
import string

def ask_token():
    import sys
    print("=== Self‑bot Discord ===")
    token = input("Entrez votre token Discord : ").strip()
    # Nettoyage des guillemets éventuels
    token = token.strip('"').strip("'")
    if not token:
        print("Token invalide. Arrêt.")
        sys.exit(1)
    return token

TOKEN = None # Will be set via run_bot or main
PREFIX = "."

# Configuration Anti-Raid
ANTIRAID_CONFIG = {
    "antispam": True,
    "antimassmention": True,
    "antichannel": True,
    "antirole": True,
    "antibot": True,
    "antiban": True,
    "antitoken": True,
    "antiunban": True,
    "antikick": True,
    "antiwebhook": True,
    "antiupdate": True,
    "antieveryone": True,
    "antilink": True,
    "antirank": True,
    "protected": True
}
WHITELIST = set()

# Cache pour l'antispam
import collections
import time
spam_check = collections.defaultdict(list)

async def punish_user(guild, user, reason):
    """Logique de punition : Derank (suppression des rôles) ou Ban si impossible."""
    if user.id == bot.user.id or user.id in WHITELIST:
        return
    
    print(f"[ANTIRAID] Punition de {user} pour {reason}")
    try:
        # Tentative de derank (retirer tous les rôles sauf @everyone)
        roles = [r for r in user.roles if r != guild.default_role]
        if roles:
            await user.remove_roles(*roles, reason=f"AntiRaid: {reason}")
            print(f"[ANTIRAID] Rôles supprimés pour {user}")
        else:
            # Si pas de rôles ou échec, kick/ban
            await user.ban(reason=f"AntiRaid: {reason}")
            print(f"[ANTIRAID] {user} banni.")
    except Exception as e:
        print(f"[ANTIRAID] Échec punition {user}: {e}")

# Intents requis pour lire les messages et membres (Non requis pour discord.py-self v2.1.0)
# intents = discord.Intents.default()
# intents.messages = True
# intents.guilds = True
# intents.members = True

# Self‑bot avec discord.py-self (si installé) sinon discord.py standard
try:
    # discord.py-self expose self_bot=True
    bot = commands.Bot(command_prefix=PREFIX, self_bot=True)
except Exception:
    # Fallback pour anciennes versions ou autre lib (peut ne pas fonctionner sans intents)
    bot = commands.Bot(command_prefix=PREFIX)

bot.remove_command('help')

@bot.command()
async def whitelist(ctx, user: discord.Member):
    """Ajoute un utilisateur à la whitelist antiraid."""
    await ctx.message.delete()
    WHITELIST.add(user.id)
    await ctx.send(f"{user} ajouté à la whitelist.", delete_after=5)

@bot.command()
async def unwhitelist(ctx, user: discord.Member):
    """Retire un utilisateur de la whitelist antiraid."""
    await ctx.message.delete()
    if user.id in WHITELIST:
        WHITELIST.remove(user.id)
        await ctx.send(f"{user} retiré de la whitelist.", delete_after=5)

# --- Événements Anti-Raid ---

@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.author.id == bot.user.id or message.author.id in WHITELIST or not message.guild:
        return

    # Antispam
    if ANTIRAID_CONFIG["antispam"]:
        now = time.time()
        bucket = spam_check[message.author.id]
        # Nettoyage vieux messages (> 5s)
        spam_check[message.author.id] = [t for t in bucket if now - t < 5]
        spam_check[message.author.id].append(now)
        if len(spam_check[message.author.id]) > 7: # > 7 messages en 5s
             await punish_user(message.guild, message.author, "Spam")
    
    # Antimassmention
    if ANTIRAID_CONFIG["antimassmention"]:
        if len(message.mentions) > 5 or len(message.role_mentions) > 3:
            await punish_user(message.guild, message.author, "Mass Mention")
    
    # Antieveryone
    if ANTIRAID_CONFIG["antieveryone"]:
        if "@everyone" in message.content or "@here" in message.content:
            await punish_user(message.guild, message.author, "Mention everyone/here")

    # Antilink
    if ANTIRAID_CONFIG["antilink"]:
        if "http://" in message.content or "https://" in message.content:
            await punish_user(message.guild, message.author, "Lien interdit")

    # Antitoken
    if ANTIRAID_CONFIG["antitoken"]:
        # Regex simple pour token Discord (pattern approximatif)
        import re
        if re.search(r"[a-zA-Z0-9_-]{23,28}\.[a-zA-Z0-9_-]{6,7}\.[a-zA-Z0-9_-]{27}", message.content):
             await punish_user(message.guild, message.author, "Token posté")

@bot.event
async def on_member_join(member):
    if ANTIRAID_CONFIG["antibot"] and member.bot:
        if member.id not in WHITELIST:
            await punish_user(member.guild, member, "Bot non autorisé")

@bot.event
async def on_guild_channel_create(channel):
    if ANTIRAID_CONFIG["antichannel"]:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(channel.guild, entry.user, "Création de salon")
                await channel.delete()

@bot.event
async def on_guild_channel_delete(channel):
    if ANTIRAID_CONFIG["antichannel"]:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(channel.guild, entry.user, "Suppression de salon")

@bot.event
async def on_guild_role_create(role):
    if ANTIRAID_CONFIG["antirole"]:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(role.guild, entry.user, "Création de rôle")
                await role.delete()

@bot.event
async def on_guild_role_delete(role):
    if ANTIRAID_CONFIG["antirole"]:
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(role.guild, entry.user, "Suppression de rôle")

@bot.event
async def on_member_ban(guild, user):
    if ANTIRAID_CONFIG["antiban"]:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(guild, entry.user, "Ban non autorisé")
                try:
                    await guild.unban(user)
                except:
                    pass

@bot.event
async def on_member_unban(guild, user):
    if ANTIRAID_CONFIG["antiunban"]:
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(guild, entry.user, "Unban non autorisé")
                await guild.ban(user)

@bot.event
async def on_webhooks_update(channel):
    if ANTIRAID_CONFIG["antiwebhook"]:
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.webhook_create):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(channel.guild, entry.user, "Création de webhook")
                # Supprimer le webhook si possible
                try:
                    hooks = await channel.webhooks()
                    for hook in hooks:
                        if hook.user == entry.user:
                            await hook.delete()
                except:
                    pass

@bot.event
async def on_guild_update(before, after):
    if ANTIRAID_CONFIG["antiupdate"]:
        async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                await punish_user(after, entry.user, "Modification du serveur")
                # Tentative de rollback basique (nom)
                if before.name != after.name:
                    await after.edit(name=before.name)

@bot.event
async def on_member_update(before, after):
    # Antirank: check si un membre a gagné un rôle admin/dangereux
    if ANTIRAID_CONFIG["antirank"]:
        if len(before.roles) < len(after.roles):
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_role_update):
                if entry.user.id != bot.user.id and entry.user.id not in WHITELIST:
                    # Si l'utilisateur qui a ajouté le rôle n'est pas whitelisté
                    await punish_user(after.guild, entry.user, "Ajout de rôle suspect")
                    # Retirer le rôle ajouté
                    added_roles = [r for r in after.roles if r not in before.roles]
                    await after.remove_roles(*added_roles)

@bot.command()
async def antiraid(ctx, setting: str = None, value: str = None):
    """Configure les modules antiraid. Usage: .antiraid <module> <on/off>"""
    await ctx.message.delete()
    if not setting:
        status = "\n".join(f"{k}: {'ON' if v else 'OFF'}" for k, v in ANTIRAID_CONFIG.items())
        await ctx.send(f"**Configuration Anti-Raid**\n```{status}```", delete_after=20)
        return

    if setting.lower() not in ANTIRAID_CONFIG:
        await ctx.send("Module inconnu.", delete_after=5)
        return

    if value and value.lower() in ["on", "true", "enable"]:
        ANTIRAID_CONFIG[setting.lower()] = True
        await ctx.send(f"Module {setting} activé.", delete_after=5)
    elif value and value.lower() in ["off", "false", "disable"]:
        ANTIRAID_CONFIG[setting.lower()] = False
        await ctx.send(f"Module {setting} désactivé.", delete_after=5)
    else:
        await ctx.send("Usage: .antiraid <module> <on/off>", delete_after=5)

@bot.command()
async def help(ctx):
    await ctx.message.delete()
    cmds = (
        ".help – Affiche ce message\n"
        ".ping – Pong!\n"
        ".nuke – Supprime tous les salons et rôles, recrée des salons basiques\n"
        ".spam <amount> <message> – Spam le message amount fois\n"
        ".spamid <user_id> <amount> <message> – Spam en MP l’ID\n"
        ".spamall <amount> <message> – Spam tous les membres du serveur en MP\n"
        ".raid <amount> <message> – Mass ping + suppression des salons\n"
        ".massdm <message> – Envoie un MP à tous les membres du serveur\n"
        ".purge <amount> – Supprime les amount derniers messages\n"
        ".webhookspam <url> <amount> <message> – Spam via webhook\n"
        ".cleardm <user_id> – Supprime les MPs avec cet utilisateur\n"
        ".firstmessage – Lien vers le premier message du salon\n"
        ".guildicon – Icône du serveur\n"
        ".delall – Supprime tous vos messages du salon\n"
        ".deluser <user> – Supprime les messages d'un utilisateur\n"
        ".ghostping <amount> <user> – Mentions fantômes\n"
        ".everyone <amount> <message> – Spam @everyone\n"
        ".here <amount> <message> – Spam @here\n"
        ".reactspam <msg_id> <emoji> <amount> – Spam réactions\n"
        ".nickspam <amount> – Change le pseudo en boucle\n"
        ".statusspam <amount> <text> – Change le statut en boucle\n"
        ".tokeninfo – Infos du token\n"
        ".copyguild <guild_id> – Clone un serveur\n"
        ".stealall – Vole tous les emojis\n"
        ".scramble – Renomme les salons aléatoirement\n"
        ".dmhistory <user_id> <limit> – Historique MP\n"
        ".clearmydms – Supprime vos messages dans tous les MPs\n"
        ".bypassverify <invite> – Bypass vérification\n"
        ".massreact <amount> <emoji> – Réagit aux messages récents\n"
        ".tokencheck – Vérifie la validité du token\n"
        ".autoguild <name> <amount> – Crée des serveurs\n"
        ".dhikr – Envoie une phrase de dhikr\n"
        ".antiraid [module] [on/off] – Gestion des modules anti-raid\n"
        ".whitelist <user> – Ajoute un utilisateur à la whitelist\n"
        ".unwhitelist <user> – Retire un utilisateur de la whitelist"
    )
    await ctx.send(f"```\n{cmds}\n```")

@bot.command()
async def ping(ctx):
    await ctx.message.delete()
    await ctx.send("pong")

@bot.command()
async def nuke(ctx):
    guild = ctx.guild
    await ctx.message.delete()
    for channel in guild.channels:
        try:
            await channel.delete()
        except discord.Forbidden:
            pass
    for role in guild.roles:
        if role != guild.default_role:
            try:
                await role.delete()
            except discord.Forbidden:
                pass
    await guild.create_text_channel("general")
    await guild.create_text_channel("spam")
    await guild.create_voice_channel("Vocal 1")
    await ctx.send("Serveur nuké !")

@bot.command()
async def spam(ctx, amount: int, *, message: str):
    await ctx.message.delete()
    for _ in range(amount):
        await ctx.send(message)

@bot.command()
async def spamid(ctx, user_id: int, amount: int, *, message: str):
    await ctx.message.delete()
    user = bot.get_user(user_id)
    if not user:
        await ctx.send("Utilisateur introuvable.")
        return
    for _ in range(amount):
        try:
            await user.send(message)
        except discord.Forbidden:
            break

@bot.command()
async def spamall(ctx, amount: int, *, message: str):
    await ctx.message.delete()
    for member in ctx.guild.members:
        if member.bot:
            continue
        for _ in range(amount):
            try:
                await member.send(message)
            except discord.Forbidden:
                break

@bot.command()
async def raid(ctx, amount: int, *, message: str):
    await ctx.message.delete()
    # Mass ping
    for _ in range(amount):
        mentions = " ".join(m.mention for m in ctx.guild.members if not m.bot)
        await ctx.send(f"{mentions} {message}")
    for channel in ctx.guild.channels:
        try:
            await channel.delete()
        except discord.Forbidden:
            pass

@bot.command()
async def massdm(ctx, *, message: str):
    await ctx.message.delete()
    for member in ctx.guild.members:
        if member.bot:
            continue
        try:
            await member.send(message)
        except discord.Forbidden:
            continue

@bot.command()
async def purge(ctx, amount: int):
    await ctx.message.delete()
    async for msg in ctx.channel.history(limit=amount):
        try:
            await msg.delete()
        except discord.Forbidden:
            pass

@bot.command()
async def delall(ctx):
    """Supprime tous vos messages visibles dans le salon actuel."""
    await ctx.message.delete()
    async for msg in ctx.channel.history(limit=None):
        if msg.author == bot.user:
            try:
                await msg.delete()
            except discord.Forbidden:
                pass

@bot.command()
async def deluser(ctx, user: discord.Member):
    """Supprime tous les messages de l'utilisateur spécifié dans le salon actuel."""
    await ctx.message.delete()
    async for msg in ctx.channel.history(limit=None):
        if msg.author == user:
            try:
                await msg.delete()
            except discord.Forbidden:
                pass

@bot.command()
async def ghostping(ctx, amount: int = None, user: discord.Member = None):
    """Envoie des mentions qui se suppriment instantanément."""
    await ctx.message.delete()
    if amount is None or user is None:
        await ctx.send("Usage: .ghostping <amount> <user>", delete_after=5)
        return
    for _ in range(amount):
        m = await ctx.send(user.mention)
        await asyncio.sleep(0.1)
        await m.delete()

@bot.command()
async def everyone(ctx, amount: int, *, message: str = ""):
    """Spam @everyone + message."""
    await ctx.message.delete()
    for _ in range(amount):
        await ctx.send(f"@everyone {message}")

@bot.command()
async def here(ctx, amount: int, *, message: str = ""):
    """Spam @here + message."""
    await ctx.message.delete()
    for _ in range(amount):
        await ctx.send(f"@here {message}")

@bot.command()
async def reactspam(ctx, message_id: int, emoji: str, amount: int):
    """Spame une réaction sur un message précis."""
    await ctx.message.delete()
    try:
        msg = await ctx.channel.fetch_message(message_id)
        for _ in range(amount):
            await msg.add_reaction(emoji)
    except discord.NotFound:
        await ctx.send("Message introuvable.")

@bot.command()
async def nickspam(ctx, amount: int):
    """Change votre pseudo en boucle."""
    await ctx.message.delete()
    original = ctx.guild.me.nick
    for i in range(amount):
        await ctx.guild.me.edit(nick=f"[{i}] {original or bot.user.name}")
        await asyncio.sleep(0.5)
    await ctx.guild.me.edit(nick=original)

@bot.command()
async def statusspam(ctx, amount: int, *, text: str):
    """Spamme votre statut en boucle."""
    await ctx.message.delete()
    for i in range(amount):
        await bot.change_presence(activity=discord.Game(name=f"{text} [{i}]"))
        await asyncio.sleep(1)

@bot.command()
async def tokeninfo(ctx):
    """Affiche les infos du token utilisé."""
    await ctx.message.delete()
    user = bot.user
    await ctx.send(f"**Token Infos**\nNom: {user}\nID: {user.id}\nEmail: {user.email if hasattr(user, 'email') else 'N/A'}\nVérifié: {user.verified}")

@bot.command()
async def copyguild(ctx, guild_id: int):
    """Clone les salons d'un autre serveur où vous êtes."""
    await ctx.message.delete()
    target = bot.get_guild(guild_id)
    if not target:
        await ctx.send("Serveur introuvable ou accès refusé.")
        return
    for chan in target.channels:
        if isinstance(chan, discord.TextChannel):
            await ctx.guild.create_text_channel(chan.name, topic=chan.topic, position=chan.position)
        elif isinstance(chan, discord.VoiceChannel):
            await ctx.guild.create_voice_channel(chan.name, bitrate=chan.bitrate, user_limit=chan.user_limit, position=chan.position)
    await ctx.send("Salons copiés.")

@bot.command()
async def stealall(ctx):
    """Vole tous les emojis du serveur."""
    await ctx.message.delete()
    for emoji in ctx.guild.emojis:
        try:
            await ctx.guild.create_custom_emoji(name=emoji.name, image=await emoji.url.read(), reason="Vol d'emoji")
        except discord.Forbidden:
            pass

@bot.command()
async def scramble(ctx):
    """Renomme tous les salons textuels avec des caractères aléatoires."""
    await ctx.message.delete()
    for chan in ctx.guild.text_channels:
        try:
            new_name = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            await chan.edit(name=new_name)
        except discord.Forbidden:
            pass

@bot.command()
async def dmhistory(ctx, user_id: int, limit: int = 20):
    """Affiche les derniers messages d'un MP avec un utilisateur."""
    await ctx.message.delete()
    user = bot.get_user(user_id)
    if not user:
        await ctx.send("Utilisateur introuvable.")
        return
    async for msg in user.history(limit=limit):
        await ctx.send(f"[{msg.created_at}] {msg.author}: {msg.content}")

@bot.command()
async def clearmydms(ctx):
    """Supprime tous vos messages dans tous vos MPs."""
    await ctx.message.delete()
    for dm in bot.private_channels:
        async for msg in dm.history(limit=None):
            if msg.author == bot.user:
                try:
                    await msg.delete()
                except discord.Forbidden:
                    pass

@bot.command()
async def bypassverify(ctx, invite: str):
    """Tente de rejoindre un serveur avec un lien d'invite (bypass de vérif manuelle)."""
    await ctx.message.delete()
    try:
        await bot.accept_invite(invite)
        await ctx.send("Rejoint avec succès.")
    except Exception as e:
        await ctx.send(f"Erreur: {e}")

@bot.command()
async def massreact(ctx, amount: int, emoji: str):
    """Réagit à tous les messages récents du salon avec une réaction."""
    await ctx.message.delete()
    async for msg in ctx.channel.history(limit=amount):
        try:
            await msg.add_reaction(emoji)
        except discord.Forbidden:
            pass

@bot.command()
async def tokencheck(ctx):
    """Vérifie si le token est valide."""
    await ctx.message.delete()
    try:
        await bot.fetch_user(bot.user.id)
        await ctx.send("Token valide.")
    except Exception:
        await ctx.send("Token invalide ou révoqué.")

@bot.command()
async def autoguild(ctx, name: str, amount: int = 1):
    """Crée des serveurs avec le nom donné."""
    await ctx.message.delete()
    for _ in range(amount):
        try:
            await bot.create_guild(name=name)
        except discord.HTTPException as e:
            await ctx.send(f"Erreur création serveur: {e}")

@bot.command()
async def webhookspam(ctx, url: str, amount: int, *, message: str):
    await ctx.message.delete()
    session = await aiohttp.ClientSession()
    webhook = discord.Webhook.from_url(url, session=session)
    for _ in range(amount):
        await webhook.send(message)
    await session.close()

@bot.command()
async def cleardm(ctx, user_id: int):
    await ctx.message.delete()
    user = bot.get_user(user_id)
    if not user:
        await ctx.send("Utilisateur introuvable.")
        return
    async for msg in user.history(limit=100):
        try:
            await msg.delete()
        except discord.Forbidden:
            pass

@bot.command()
async def firstmessage(ctx):
    await ctx.message.delete()
    async for msg in ctx.channel.history(limit=1, oldest_first=True):
        await ctx.send(msg.jump_url)
        break

@bot.command()
async def guildicon(ctx):
    await ctx.message.delete()
    await ctx.send(ctx.guild.icon_url)

@bot.command()
async def dhikr(ctx):
    """Envoie une phrase de dhikr aléatoire."""
    await ctx.message.delete()
    phrases = [
        "SubhanAllah",
        "Alhamdulillah",
        "La ilaha illallah",
        "Allahu Akbar",
        "SubhanAllahi wa bihamdihi",
        "SubhanAllahil Azeem",
        "Astaghfirullah",
        "La hawla wa la quwwata illa billah",
        "Allahumma salli ala Sayyidina Muhammad"
    ]
    await ctx.send(random.choice(phrases))

def run_bot(token):
    global TOKEN
    TOKEN = token
    try:
        bot.run(token)
    except Exception as e:
        print(f"Erreur au démarrage : {e}")

if __name__ == "__main__":
    TOKEN = ask_token()
    run_bot(TOKEN)