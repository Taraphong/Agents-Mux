# AI Web on Termux

Self-hosted AI chat running on Termux and accessible through a browser on the same network. Supports OpenAI, Gemini, and Anthropic.

ภาษาไทย: **[README.th.md](README.th.md)**

## Getting Started

Detailed install guide for Termux / Linux / macOS: **[INSTALL.md](INSTALL.md)**

Quick install:

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:fab8f7793def8862ab6a37ae370ebdd61a8c182285c59cd7f65aa58ea4174870 -->

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

Edit `.env` to set `AI_PROVIDER` and the matching API key, then start the server:

```bash
./start_web.sh --start
```

<!-- /coderabbit-ai-generated:v1 -->

Or set up manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open `http://127.0.0.1:5000` in a browser.

### Configuration

- Set `AI_PROVIDER` in `.env` (`openai`, `gemini`, `anthropic`, `hf`, `or`, or `groq`).
- Set the API key that matches the provider: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `HF_API_KEY`, `OPENROUTER_API_KEY`, or `GROQ_API_KEY`.
- **Anthropic:** set `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`, then open **Settings** in the web interface and select a Claude model. The startup default comes from `OPENAI_MODEL`, so an OpenAI model will not work with Anthropic.
- Values saved from **Settings** are stored in `.app-settings.json` and override `.env`, including provider, model, and API keys. Change them in Settings (or remove the saved settings file) if editing `.env` has no effect.
- Configure additional options from the **Settings** menu in the web interface.
- Available reasoning levels: `off`, `low`, `medium`, and `high`.

### Device pairing (web auth)

The web interface requires a paired device. Pairing keys are always generated on the server; the browser never creates one.

- On the server, create a key with `python app.py --pairing-key` (or `./start_web.sh --pair`). The first start with no paired device prints a key automatically.
- On the client, open `http://<termux-ip>:5000/pair` and enter the key. A valid key issues an `HttpOnly` session cookie, valid for `AI_WEB_SESSION_DAYS` (default 30).
- Keys are single-use and expire after `AI_WEB_PAIRING_TTL_MINUTES` (default 30). Only SHA-256 hashes of keys and session tokens are stored, in `.app-auth.json`, which is excluded from Git.
- Review, revoke, or create a key for another device in **Settings → Security and device pairing**. `python app.py --revoke-sessions` revokes every device.
- `AI_WEB_AUTH=off` disables pairing and is meant only for a fully trusted network. Unpaired pages redirect to `/pair`; `/api/auth/status` stays reachable for health checks.
- When TLS terminates at a reverse proxy, set `AI_WEB_TRUST_PROXY=1` so `X-Forwarded-Proto` is trusted and the session cookie is marked `Secure`. Leave it unset for plain local HTTP.

### Conversation History

Conversations are stored by date and time in `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json`.

- The `history/` directory is excluded from Git.
- Conversations can be renamed, pinned, locked, and unlocked from the chat interface.

## AI Tools

- AI agents can read project files immediately.
- Writing files and running commands require approval in the chat (valid for 15 minutes and usable once).
- Paths are restricted to the project directory, excluding `.env`, `.app-settings.json`, `history/`, `.venv/`, and `.git/`.
- Allowed commands are limited to `pwd`, `ls`, `git status|diff|log`, and `python -m py_compile app.py`.

### Web chat slash commands

Type `/` in the chat box to open an autocomplete menu. Commands run locally unless noted:

- `/help` lists every command and available skill.
- `/new` or `/clear` starts a fresh conversation context.
- `/model` and `/status` show the active provider, model, and readiness.
- `/models [provider] [model]` lists models or switches provider/model.
- `/ping` measures the server response time.
- `/fallback [model|off]` shows or changes the fallback model.
- `/skills` lists available skills.
- `/skill <name> [prompt]` applies a skill to the next message, or to the given prompt immediately.
- `/<skill-name> [prompt]` is a shortcut for `/skill <skill-name> [prompt]`.

A skill used through a slash command applies only to that request and does not change the skills selected in Settings.

### Terminal

The **Terminal** page runs shell commands directly on the server as the user running the app, starting in the project folder and supporting `cd` within the project. Commands time out after 60 seconds, output is capped at 100 KB, credential-like environment variables are removed, and known API keys/tokens are redacted from the output. The page can be disabled in **Settings**.

> ⚠️ The Terminal runs with the privileges of the user running the app. With web auth enabled, only paired devices can open it; with `AI_WEB_AUTH=off` anyone who can reach the page can use the terminal, so only expose it on a trusted network.

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
