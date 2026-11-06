# AI Web on Termux

Self-hosted AI chat running on Termux and accessible through a browser on the same network. Supports OpenAI, Gemini, and Anthropic.

ภาษาไทย: **[README.th.md](README.th.md)**

## Getting Started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000` in a browser.

### Configuration

- Set `AI_PROVIDER` in `.env` (`openai`, `gemini`, or `anthropic`).
- Configure additional options from the **Settings** menu in the web interface.
- Available reasoning levels: `off`, `low`, `medium`, and `high`.

### Conversation History

Conversations are stored by date and time in `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json`.

- The `history/` directory is excluded from Git.
- Conversations can be renamed, pinned, locked, and unlocked from the chat interface.

For detailed requirements and development guidelines, read **[AGENTS.md](AGENTS.md)**.

## AI Tools

- AI agents can read project files immediately.
- Writing files and running commands require approval in the chat (valid for 15 minutes and usable once).
- Paths are restricted to the project directory, excluding `.env`, `.app-settings.json`, `history/`, `.venv/`, and `.git/`.
- Allowed commands are limited to `pwd`, `ls`, `git status|diff|log`, and `python -m py_compile app.py`.

### Discord bot

The app can run a Discord bot beside Flask and use the configured provider/model to answer messages.

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent**, then invite the bot with the `bot` scope and permission to send messages.
3. In the web Settings page, enter the bot token, enable Discord, and save.
4. Mention the bot or send `!ai your message` in Discord. The prefix can be changed in Settings.

Supported slash commands: `/ai` to send work to the agent, `/new` to create a new chat and web history immediately, `/models` to change provider/model and show availability, `/model` to show the active model and status, `/clear` to clear channel context, `/thread` to create a topic thread, `/fallback` to set a channel-specific fallback and show its status, `/ping` to check server latency, and `/help` to list commands.

Changing the provider/model and setting a fallback require server administrator permission. Use `/invite` to generate an invite link with Administrator permission; a user with server management permission must open it because a bot cannot grant permissions to itself.

The token is stored server-side in `.app-settings.json`, which is ignored by Git. Alternatively, set `DISCORD_BOT_TOKEN` and `DISCORD_BOT_PREFIX` in `.env`.

### Scheduler

Scheduled jobs run while the server is running. Set `AI_WEB_ENABLE_SCHEDULER=1` to enable the scheduler for WSGI deployments.
