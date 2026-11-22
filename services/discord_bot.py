"""The optional Discord bot.

The bot runs in its own thread with its own event loop, keeps a bounded context
per channel, and saves each exchange through the history store. This module
never imports app; app.py starts and stops it.
"""

import asyncio
import json
import re
import threading
import uuid
from collections import deque
from typing import Any

import requests

from core.config import TOOL_CALL_BLOCK_PATTERN
from core.history import save_discord_turn, save_history
from core.log import log_event
from core.model_cache import remember_model_names
from core.prompts import build_system_prompt
from core.providers import (
    FALLBACK_MODELS,
    STATUS_CACHE,
    call_provider,
    clean_messages,
    list_models,
    model_names_for_autocomplete,
    provider_readiness,
    same_secret,
    schedule_model_list_refresh,
)
from core.settings import (
    PROVIDER_LABELS,
    SETTINGS_LOCK,
    discord_access_allowed,
    get_discord_token,
    load_settings,
    normalize_provider,
    save_settings,
)
from core.tools import parse_tool_request, run_local_tool


DISCORD_CONTEXTS: dict[str, deque[dict[str, str]]] = {}
DISCORD_CONVERSATION_IDS: dict[str, str] = {}
DISCORD_CONTEXT_LOCK = threading.Lock()
DISCORD_BOT: Any = None
DISCORD_THREAD: threading.Thread | None = None
DISCORD_LOOP: Any = None
DISCORD_ACTIVE_TOKEN = ""


def send_discord_schedule_result(job: dict[str, Any], answer: str) -> None:
    """Send a scheduled job result to its configured Discord channel."""
    channel_id = str(job.get("discord_channel_id") or "").strip()
    if not channel_id:
        return
    if not channel_id.isdigit():
        raise ValueError("The Discord Channel ID must be a number")
    if DISCORD_BOT is None or DISCORD_LOOP is None or DISCORD_LOOP.is_closed():
        raise RuntimeError("The Discord bot is not connected yet")

    async def deliver() -> None:
        """Send the scheduled result chunks to the Discord channel."""
        channel = DISCORD_BOT.get_channel(int(channel_id))
        if channel is None:
            channel = await DISCORD_BOT.fetch_channel(int(channel_id))
        for chunk in split_discord_message(f"⏰ {job['name']}\n\n{answer}"):
            await channel.send(chunk)

    future = asyncio.run_coroutine_threadsafe(deliver(), DISCORD_LOOP)
    future.result(timeout=30)


def discord_status() -> dict[str, Any]:
    """Report whether the Discord bot is enabled, configured, and connected."""
    token = get_discord_token()
    return {
        "enabled": bool(load_settings().get("discord_enabled")),
        "configured": bool(token),
        "connected": bool(DISCORD_BOT and getattr(DISCORD_BOT, "is_ready", lambda: False)()),
    }


def split_discord_message(text: str, limit: int = 2000) -> list[str]:
    """Split a long reply into Discord-sized message chunks."""
    text = str(text or "")
    return [text[index:index + limit] for index in range(0, len(text), limit)] or ["(No response text)"]


def stop_discord_bot() -> None:
    """Ask the running Discord client to close, if it is connected."""
    if DISCORD_BOT is not None and DISCORD_LOOP is not None and not DISCORD_LOOP.is_closed():
        try:
            DISCORD_LOOP.call_soon_threadsafe(lambda: __import__("asyncio").create_task(DISCORD_BOT.close()))
        except RuntimeError:
            pass


def start_discord_bot() -> None:
    """Run the optional Discord client in a daemon thread beside Flask."""
    global DISCORD_BOT, DISCORD_THREAD, DISCORD_LOOP, DISCORD_ACTIVE_TOKEN
    settings = load_settings()
    token = get_discord_token(settings)
    if not settings.get("discord_enabled") or not token:
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive() and same_secret(DISCORD_ACTIVE_TOKEN, token):
        return
    if DISCORD_THREAD and DISCORD_THREAD.is_alive():
        stop_discord_bot()
    try:
        import discord
    except ImportError:
        log_event("discord.error", "discord.py is not installed")
        return

    intents = discord.Intents.default()
    intents.message_content = True
    prefix = str(settings.get("discord_prefix") or "!ai").strip() or "!ai"
    commands_synced = False
    # A reconnect fires READY again, so the pass is serialised and records each
    # guild only after its own cleanup returned.
    sync_state_lock = asyncio.Lock()
    cleared_guilds: set[int] = set()
    GUILD_CLEAR_ATTEMPTS = 3

    class AccessControlledCommandTree(discord.app_commands.CommandTree):
        """Reject slash commands from channels or users outside the allowlists."""

        async def interaction_check(self, interaction: Any) -> bool:
            if discord_access_allowed(
                load_settings(),
                getattr(interaction, "channel_id", ""),
                getattr(getattr(interaction, "user", None), "id", ""),
            ):
                return True
            await interaction.response.send_message(
                "This bot is limited to specific users or channels.",
                ephemeral=True,
            )
            return False

    class AIClient(discord.Client):
        async def on_ready(self) -> None:
            """Register the global commands and remove legacy guild copies."""
            nonlocal commands_synced
            uncleared = 0
            # Overlapping READY events must not write the same guild twice, so
            # the whole pass runs under one lock and rechecks the per-guild state.
            async with sync_state_lock:
                if not commands_synced:
                    try:
                        await command_tree.sync()
                        commands_synced = True
                        log_event("discord.commands", "Registered the Discord slash commands")
                    except Exception as exc:
                        log_event("discord.error", "Could not register the Discord slash commands", error=str(exc))
                # Global commands are the only registration, so the guild-scoped
                # copies left by older versions must go. If the global sync
                # failed, keep them: no commands is worse than duplicates.
                if commands_synced:
                    pending = [guild for guild in self.guilds if guild.id not in cleared_guilds]
                    failures: list[str] = []
                    cleared_now = 0
                    for guild in pending:
                        last_error = ""
                        for attempt in range(1, GUILD_CLEAR_ATTEMPTS + 1):
                            try:
                                await remove_legacy_guild_commands(guild)
                            except Exception as exc:
                                last_error = f"{guild.id}: {exc}"
                                if attempt < GUILD_CLEAR_ATTEMPTS:
                                    await asyncio.sleep(2 ** (attempt - 1))
                            else:
                                cleared_guilds.add(guild.id)
                                cleared_now += 1
                                break
                        else:
                            failures.append(last_error)
                    if pending:
                        details: dict[str, Any] = {"servers": len(self.guilds), "cleared_now": cleared_now}
                        if failures:
                            details["failed"] = "; ".join(failures)[:300]
                        log_event("discord.commands", "Cleared duplicate guild slash commands", **details)
                    # A guild that never succeeded is retried on the next READY event.
                    uncleared = sum(1 for guild in self.guilds if guild.id not in cleared_guilds)
            if uncleared:
                log_event(
                    "discord.error",
                    "Could not clear guild slash commands on some guilds; retrying on the next connection",
                    uncleared=uncleared,
                )
            settings = load_settings()
            schedule_model_list_refresh(settings.get("provider", "openai"), settings)
            log_event("discord.connected", "Discord bot connected", user=str(self.user))

        async def on_message(self, message: Any) -> None:
            """Reply to mentions, prefixed messages, and DMs through the agent."""
            if message.author == self.user or getattr(message.author, "bot", False):
                return
            if not discord_access_allowed(
                load_settings(),
                getattr(message.channel, "id", ""),
                getattr(message.author, "id", ""),
            ):
                log_event(
                    "discord.ignored",
                    "Ignored a Discord message outside the allowed users or channels",
                    channel=str(getattr(message.channel, "id", "")),
                    user=str(getattr(message.author, "id", "")),
                )
                return
            content = str(message.content or "").strip()
            mentioned = self.user and self.user in message.mentions
            if mentioned:
                content = re.sub(rf"<@!?{self.user.id}>", "", content).strip()
            elif content.lower().startswith(prefix.lower()):
                content = content[len(prefix):].strip()
            elif message.guild is not None:
                return
            if not content:
                await message.reply(f"Type a message after {prefix} or mention the bot to start chatting.")
                return

            answer = await ask_agent(
                str(message.channel.id),
                content,
                getattr(message.channel, "name", "Discord"),
                allow_schedule_tools=member_is_admin(message.author),
            )
            for chunk in split_discord_message(answer):
                await message.reply(chunk, mention_author=False)

    client = AIClient(intents=intents)
    command_tree = AccessControlledCommandTree(client)

    async def remove_legacy_guild_commands(guild: Any) -> None:
        """Remove the guild-scoped copies left by older versions."""
        command_tree.clear_commands(guild=guild)
        await command_tree.sync(guild=guild)

    def member_is_admin(member: Any) -> bool:
        """Return whether a guild member has server administrator rights."""
        permissions = getattr(member, "guild_permissions", None)
        return bool(getattr(permissions, "administrator", False))

    def is_server_admin(interaction: Any) -> bool:
        """Return whether the interaction author has server administrator rights."""
        return member_is_admin(getattr(interaction, "user", None))

    async def require_server_admin(interaction: Any) -> bool:
        """Reject an interaction unless the author is a server administrator."""
        if is_server_admin(interaction):
            return True
        await interaction.response.send_message("This command is available to server administrators only.", ephemeral=True)
        return False

    async def check_model_availability(provider: str, model: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Check a provider and model off the event loop without saving settings."""
        probe_settings = dict(settings)
        probe_settings["provider"] = provider
        probe_settings["model"] = model
        return await asyncio.to_thread(provider_readiness, probe_settings, "en")

    async def ask_agent(
        context_key: str,
        content: str,
        channel_title: str = "Discord",
        allow_schedule_tools: bool = False,
    ) -> str:
        """Run one agent turn while keeping a short per-channel conversation.

        Schedule tools change what the server runs on a timer, so they are only
        auto-approved for a member who can already administer the server.
        """
        with DISCORD_CONTEXT_LOCK:
            context = DISCORD_CONTEXTS.setdefault(context_key, deque(maxlen=12))
            context.append({"role": "user", "content": content, "message_id": str(uuid.uuid4())})
            messages = list(context)
        try:
            settings_for_chat = load_settings()
            settings_for_chat["system_prompt"] = build_system_prompt(
                settings_for_chat, messages, include_memory_review=False
            )
            messages = clean_messages(messages, settings_for_chat)
            fallback_used = ""
            try:
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
            except requests.HTTPError as primary_error:
                channel_fallbacks = settings_for_chat.get("discord_fallback_models")
                channel_fallback = channel_fallbacks.get(context_key) if isinstance(channel_fallbacks, dict) else ""
                fallback_model = str(channel_fallback or settings_for_chat.get("fallback_model") or "").strip()
                fallback_provider = normalize_provider(settings_for_chat.get("fallback_provider"))
                primary_provider = normalize_provider(settings_for_chat.get("provider"))
                status_code = primary_error.response.status_code if primary_error.response is not None else None
                same_target = fallback_model == settings_for_chat.get("model") and (
                    bool(channel_fallback) or fallback_provider == primary_provider
                )
                can_fallback = (
                    bool(settings_for_chat.get("fallback_enabled"))
                    and fallback_model
                    and not same_target
                    and status_code in {400, 404, 429, 500, 502, 503, 504}
                )
                if not can_fallback:
                    raise
                if not channel_fallback:
                    if fallback_provider != primary_provider:
                        settings_for_chat["base_url"] = ""
                    settings_for_chat["provider"] = fallback_provider
                settings_for_chat["model"] = fallback_model
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
                fallback_used = fallback_model
            for _ in range(3):
                try:
                    tool_request = parse_tool_request(answer)
                except ValueError:
                    tool_request = None
                if not tool_request:
                    break
                if tool_request["name"] not in {"create_schedule", "update_schedule"}:
                    break
                if not allow_schedule_tools:
                    log_event(
                        "discord.schedule_denied",
                        "Rejected a scheduled job created by a user without administrator rights",
                        channel=context_key,
                    )
                    stripped = TOOL_CALL_BLOCK_PATTERN.sub("", answer).strip()
                    answer = stripped or "Creating or editing scheduled jobs is available to server administrators only."
                    break
                result = await asyncio.to_thread(
                    run_local_tool,
                    tool_request["name"],
                    tool_request["arguments"],
                    True,
                )
                messages.extend([
                    {"role": "assistant", "content": answer},
                    {"role": "user", "content": f"Scheduled job result:\n{json.dumps(result, ensure_ascii=False)}\n\nReply in plain text, confirming the name, the time, the Cron expression and what the AI will do. Never show a tool_call or JSON."},
                ])
                answer, _usage = await asyncio.to_thread(call_provider, messages, settings_for_chat)
            with DISCORD_CONTEXT_LOCK:
                DISCORD_CONTEXTS[context_key].append({
                    "role": "assistant",
                    "content": answer,
                    "message_id": str(uuid.uuid4()),
                })
                conversation_id = DISCORD_CONVERSATION_IDS.setdefault(context_key, str(uuid.uuid4()))
                history_messages = list(DISCORD_CONTEXTS[context_key])
            save_discord_turn(
                conversation_id,
                f"Discord · {channel_title}"[:100],
                history_messages,
            )
            log_event("discord.message", "Replied to a Discord message", channel=context_key)
            if fallback_used:
                log_event("discord.fallback", "Used the fallback model for Discord", model=fallback_used, channel=context_key)
            return answer
        except Exception as exc:
            log_event("discord.error", "Could not reply to the Discord message", error=str(exc))
            return "Sorry, the AI could not be reached right now. Check the settings on the web page."

    @command_tree.command(name="ai", description="Send a task to or chat with the AI agent")
    async def ai_command(interaction: Any, prompt: str) -> None:
        """Handle the /ai slash command."""
        await interaction.response.defer()
        answer = await ask_agent(
            str(interaction.channel_id),
            prompt,
            getattr(interaction.channel, "name", "Discord"),
            allow_schedule_tools=is_server_admin(interaction),
        )
        for chunk in split_discord_message(answer):
            await interaction.followup.send(chunk)

    @command_tree.command(name="clear", description="Clear this channel's conversation context")
    async def clear_command(interaction: Any) -> None:
        """Handle the /clear slash command."""
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(str(interaction.channel_id), None)
            DISCORD_CONVERSATION_IDS.pop(str(interaction.channel_id), None)
        await interaction.response.send_message("This channel's conversation context has been cleared.")

    @command_tree.command(name="new", description="Start a new chat and create a new history entry on the web")
    async def new_command(interaction: Any) -> None:
        """Handle the /new slash command."""
        context_key = str(interaction.channel_id)
        channel_title = getattr(interaction.channel, "name", "Discord")
        conversation_id = str(uuid.uuid4())
        with DISCORD_CONTEXT_LOCK:
            DISCORD_CONTEXTS.pop(context_key, None)
            DISCORD_CONVERSATION_IDS[context_key] = conversation_id
        record = save_history({
            "id": conversation_id,
            "title": f"Discord · {channel_title}"[:100],
            "messages": [],
        })
        await interaction.response.send_message(
            f"Started a new chat; the history appears on the web immediately (ID: `{record['id'][:8]}`)"
        )

    async def model_autocomplete(interaction: Any, current_text: str) -> list[Any]:
        """Provide model id autocomplete choices for Discord commands."""
        settings = load_settings()
        selected = getattr(getattr(interaction, "namespace", None), "provider", None)
        # Namespace returns None for an option the user has not filled in yet.
        selected = getattr(selected, "value", selected) or settings.get("provider", "openai")
        selected_provider = normalize_provider(selected)
        try:
            # Answers from memory: a provider fetch would risk Discord's 3s limit.
            names = model_names_for_autocomplete(selected_provider, settings)
        except Exception as exc:
            log_event("discord.models", "Model autocomplete failed", error=str(exc)[:200])
            names = list(FALLBACK_MODELS.get(selected_provider, []))
        query = str(current_text or "").strip().lower()
        return [
            discord.app_commands.Choice(name=name[:100], value=name[:100])
            for name in names
            if not query or query in name.lower()
        ][:25]

    @command_tree.command(name="models", description="Change the AI agent's provider and model")
    @discord.app_commands.autocomplete(model=model_autocomplete)
    @discord.app_commands.choices(provider=[
        discord.app_commands.Choice(name="OpenAI / compatible", value="openai"),
        discord.app_commands.Choice(name="Google Gemini", value="gemini"),
        discord.app_commands.Choice(name="Anthropic Claude", value="anthropic"),
        discord.app_commands.Choice(name="Hugging Face", value="hf"),
        discord.app_commands.Choice(name="OpenRouter", value="or"),
        discord.app_commands.Choice(name="Groq", value="groq"),
    ])
    async def models_command(interaction: Any, provider: discord.app_commands.Choice[str], model: str | None = None) -> None:
        """Handle the /models slash command."""
        selected_provider = normalize_provider(provider.value)
        if model and not await require_server_admin(interaction):
            return
        await interaction.response.defer()
        if not model or not model.strip():
            try:
                current = load_settings()
                available = await asyncio.to_thread(list_models, selected_provider, current)
                remember_model_names(selected_provider, [item["id"] for item in available])
                current_model = current.get("model") if current.get("provider") == selected_provider else ""
                names = [item["id"] for item in available[:25]]
                listing = "\n".join(
                    f"• `{name}`{' ← in use' if name == current_model else ''} · ready"
                    for name in names
                ) or "No models found"
                await interaction.followup.send(
                    f"{PROVIDER_LABELS[selected_provider]} models (checked against the API):\n{listing}"
                )
            except Exception as exc:
                names = FALLBACK_MODELS.get(selected_provider, [])
                listing = "\n".join(f"• `{name}` · unverified" for name in names) or "No fallback list"
                await interaction.followup.send(
                    f"The {PROVIDER_LABELS[selected_provider]} API is unavailable: {str(exc)[:220]}\nFallback list:\n{listing}"
                )
            return
        # Read-modify-write under the same lock as /api/settings and /fallback,
        # so a concurrent settings change is not overwritten.
        with SETTINGS_LOCK:
            current = load_settings()
            # A base URL belongs to one provider; clearing it keeps the new
            # provider's key from being sent to the previous endpoint (the same
            # rule /api/settings applies).
            if normalize_provider(current.get("provider")) != selected_provider:
                current["base_url"] = ""
            current["provider"] = selected_provider
            current["model"] = model.strip()[:200]
            save_settings(current)
        STATUS_CACHE.clear()
        availability = await check_model_availability(selected_provider, current["model"], current)
        state = "ready" if availability.get("ready") else f"not available yet: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Agent changed to `{PROVIDER_LABELS[selected_provider]}` / `{current['model']}` · {state}"
        )

    @command_tree.command(name="ping", description="Check the Discord bot latency")
    async def ping_command(interaction: Any) -> None:
        """Handle the /ping slash command."""
        latency_ms = round(client.latency * 1000)
        await interaction.response.send_message(f"Pong! Discord latency: `{latency_ms} ms`")

    @command_tree.command(name="fallback", description="Set a fallback model for this Discord channel")
    @discord.app_commands.autocomplete(model=model_autocomplete)
    async def fallback_command(interaction: Any, model: str | None = None) -> None:
        """Handle the /fallback slash command for a channel."""
        current = load_settings()
        channel_key = str(interaction.channel_id)
        channel_fallbacks = current.get("discord_fallback_models")
        if not isinstance(channel_fallbacks, dict):
            channel_fallbacks = {}
        if not model or not model.strip():
            await interaction.response.defer()
            selected = channel_fallbacks.get(channel_key) or current.get("fallback_model") or "not set"
            if selected == "not set":
                await interaction.followup.send("Fallback model for this channel: not set")
                return
            availability = await check_model_availability(current.get("provider", "openai"), selected, current)
            state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
            await interaction.followup.send(f"Fallback model for this channel: `{selected}` · {state}")
            return
        if not await require_server_admin(interaction):
            return
        await interaction.response.defer()
        # Reload after the defer and change only this key, so a concurrent
        # /api/settings save (allowlists etc.) is not overwritten by the stale
        # snapshot captured before the awaits.
        with SETTINGS_LOCK:
            latest = load_settings()
            latest_fallbacks = latest.get("discord_fallback_models")
            if not isinstance(latest_fallbacks, dict):
                latest_fallbacks = {}
            if model.strip().lower() in {"off", "none", "disabled"}:
                latest_fallbacks.pop(channel_key, None)
                message = "Fallback is off for this channel (the main fallback is used if one is set)."
            else:
                latest_fallbacks[channel_key] = model.strip()[:200]
                message = f"Fallback model for this channel set to `{latest_fallbacks[channel_key]}`."
            latest["discord_fallback_models"] = latest_fallbacks
            save_settings(latest)
        if channel_key in latest_fallbacks:
            availability = await check_model_availability(latest.get("provider", "openai"), latest_fallbacks[channel_key], latest)
            state = "ready" if availability.get("ready") else f"not available yet: {availability.get('reason', 'check failed')}"
            message += f" · {state}"
        await interaction.followup.send(message)

    @command_tree.command(name="thread", description="Create a thread for a new topic")
    async def thread_command(interaction: Any, name: str) -> None:
        """Handle the /thread slash command."""
        channel = interaction.channel
        if not hasattr(channel, "create_thread"):
            await interaction.response.send_message("This command only works in a server text channel.", ephemeral=True)
            return
        try:
            thread = await channel.create_thread(
                name=name.strip()[:100] or "New topic",
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
            )
            await interaction.response.send_message(f"Created the thread: {thread.mention}")
        except Exception as exc:
            await interaction.response.send_message(f"Could not create the thread: {str(exc)[:300]}", ephemeral=True)

    @command_tree.command(name="status", description="Check the AI agent status")
    async def status_command(interaction: Any) -> None:
        """Handle the /status slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Discord: connected\nProvider: {current.get('provider', 'openai')}\nModel: {current.get('model', 'not selected')}\nAI status: {state}"
        )

    @command_tree.command(name="model", description="Show the provider and model the agent uses")
    async def model_command(interaction: Any) -> None:
        """Handle the /model slash command."""
        await interaction.response.defer()
        current = load_settings()
        availability = await check_model_availability(
            current.get("provider", "openai"), current.get("model", ""), current
        )
        state = "ready" if availability.get("ready") else f"unavailable: {availability.get('reason', 'check failed')}"
        await interaction.followup.send(
            f"Provider: `{current.get('provider', 'openai')}` · Model: `{current.get('model', 'not selected')}` · {state}"
        )

    @command_tree.command(name="invite", description="Create a bot invite link with Administrator permission")
    async def invite_command(interaction: Any) -> None:
        """Handle the /invite slash command."""
        if not await require_server_admin(interaction):
            return
        permissions = discord.Permissions(administrator=True)
        url = discord.utils.oauth_url(
            client.user.id,
            permissions=permissions,
            scopes=("bot", "applications.commands"),
        )
        await interaction.response.send_message(
            "This link invites or adds the bot to a new server with Administrator permission. "
            "Whoever opens the link needs permission to manage that server:\n" + url,
            ephemeral=True,
        )

    @command_tree.command(name="help", description="Show the AI agent commands")
    async def help_command(interaction: Any) -> None:
        """Handle the /help slash command."""
        await interaction.response.send_message(
            "AI agent commands:\n"
            "`/ai prompt` sends a task to or chats with the AI\n"
            "`/new` starts a new chat and creates a history entry on the web\n"
            "`/clear` clears the channel context\n"
            "`/models` changes the provider/model\n"
            "`/ping` checks the bot latency\n"
            "`/thread` creates a thread for a topic\n"
            "`/fallback model` sets a per-channel fallback\n"
            "`/invite` creates an invite link with Administrator permission (admins only)\n"
            "`/status` checks the bot status\n"
            "`/model` shows the current model\n"
            "`/help` shows this list\n\n"
            f"You can also mention the bot or type `{prefix} message`."
        )

    DISCORD_BOT = client
    DISCORD_ACTIVE_TOKEN = token

    def run_client() -> None:
        """Run the Discord client in its own event loop for the bot thread."""
        global DISCORD_LOOP
        import asyncio
        DISCORD_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(DISCORD_LOOP)
        try:
            DISCORD_LOOP.run_until_complete(client.start(token))
        except Exception as exc:
            log_event("discord.error", "Discord bot stopped", error=str(exc))
        finally:
            DISCORD_LOOP.close()

    DISCORD_THREAD = threading.Thread(target=run_client, name="discord-bot", daemon=True)
    DISCORD_THREAD.start()
