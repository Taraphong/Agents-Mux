# AI Web on Termux

Self-hosted AI chat that runs on Termux (Android), Linux, or macOS and is used through a browser on the same network. A small Flask server keeps your provider keys and conversation history on your own machine, and the page is available in English and Thai.

- Thai: **[README.th.md](README.th.md)**
- Install guide: **[docs/INSTALL.md](docs/INSTALL.md)** · [docs/INSTALL.th.md](docs/INSTALL.th.md)
- Security policy: **[docs/SECURITY.md](docs/SECURITY.md)** · [docs/SECURITY.th.md](docs/SECURITY.th.md)

## Features

- **Six providers** behind one chat page: OpenAI (or any OpenAI-compatible API), Google Gemini, Anthropic, Hugging Face, OpenRouter, and Groq.
- **Per-message model and thinking level** (`off`, `low`, `medium`, `high`), plus an optional fallback provider/model that is retried once.
- **Attachments**: text and code files up to 1 MB are read in the browser; images and PDFs up to 6 MB travel inline; audio and video work with Gemini.
- **Skills**: folders under `skills/` with a `SKILL.md` (YAML frontmatter plus guidelines, workflow and examples) and optional `scripts/`, `references/` and `assets/`, applied in Settings or for a single message with `/`.
- **Pairing**: the page is protected by single-use Pairing Keys and revocable device sessions.
- **Conversation history** organized by date, with rename, pin, lock/unlock, and delete.
- **Local tools**: the model can list, read, and write files and run shell commands on the server, with one approval per call.
- **Cron-style scheduler**, **system/agent log viewer**, **in-page updater**, and **server start/stop/restart**.
- **Memory consolidation**: nightly Light/REM/Deep phases turn chat history into `MEMORY.md` (and a readable `DREAMS.md`) while the machine is idle, with local scoring and optional model summaries.
- **Gemini extras**: capability report, Decisions API, managed agents, and short-lived Live API tokens.
- **Discord bot** with channel and user allowlists.
- **HTTP/HTTPS switching** from the page, with certificate files or an ad-hoc certificate.
- Responsive layout for phones, Enter to send, Shift+Enter for a newline, Thai/English toggle.

## Requirements

- Python **3.10 or newer**
- `openssl` only when you want the server to terminate HTTPS
- At least one provider API key

## Quick start

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

Set `AI_PROVIDER` and the matching API key in `.env`, then start the server:

```bash
./start_web.sh --start
```

Open `http://127.0.0.1:5000` (or `http://<machine-ip>:5000` from another device). On the first start without a paired device the server prints a Pairing Key; open `/pair` and enter it.

Or set the project up by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## Configuration

`install.sh` creates `.env` from `.env.example`. The file is read when the process starts and provides defaults only.

### Providers

| `AI_PROVIDER` | Provider | API key | Default model variable |
| --- | --- | --- | --- |
| `openai` | OpenAI or an OpenAI-compatible API | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| `anthropic` | Anthropic (Claude) | `ANTHROPIC_API_KEY` | select a Claude model in Settings |
| `hf` | Hugging Face | `HF_API_KEY` | `HF_MODEL` |
| `or` | OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |
| `groq` | Groq | `GROQ_API_KEY` | `GROQ_MODEL` |

- **Anthropic:** the startup model comes from `OPENAI_MODEL`, so after setting `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` open **Settings** and pick a Claude model. The model list is fetched from the API once a key is present.
- **Base URL:** set a custom endpoint in `.env` (`AI_BASE_URL`) or in Settings. A key is only sent over HTTPS; plain HTTP is refused except for loopback addresses (a local OpenAI-compatible server), unless you set `AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP=1`.
- **Reasoning:** `off`, `low`, `medium`, `high`, chosen in Settings or per message from the chat toolbar.
- **Fallback:** enable a fallback provider and model in Settings; a failed first request is retried once with it. `/fallback` shows or changes it.

### Settings versus `.env`

- Values saved in **Settings** are stored in `.app-settings.json` and override `.env`, including provider, model, and API keys.
- If editing `.env` has no effect, change the value in Settings, or use **Reset** at the bottom of Settings (it deletes `.app-settings.json`) and restart.
- API keys and the Discord token are stored server-side in `.app-settings.json`; the page only ever receives a masked placeholder.

### Other environment variables

| Variable | Meaning |
| --- | --- |
| `PORT` | Listen port (default `5000`) |
| `AI_FALLBACK_PROVIDER`, `AI_FALLBACK_MODEL` | Initial fallback values |
| `GEMINI_LIVE_MODEL`, `GEMINI_AGENT`, `GEMINI_DECISION_MODEL` | Initial Gemini feature defaults |
| `DISCORD_BOT_TOKEN`, `DISCORD_BOT_PREFIX` | Discord bot credentials and message prefix |
| `DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_CHANNEL_IDS` | Comma-separated Discord allowlists |
| `AI_WEB_AUTH` | `on` (default) or `off` for device pairing |
| `AI_WEB_AUTH_FILE` | Pairing/session store (default `.app-auth.json`) |
| `AI_WEB_PAIRING_TTL_MINUTES` | Pairing Key lifetime (default `30`) |
| `AI_WEB_SESSION_DAYS` | Paired-device session lifetime (default `30`) |
| `AI_WEB_TRUST_PROXY` | Set to `1` behind a TLS-terminating reverse proxy |
| `AI_WEB_TLS_CERT`, `AI_WEB_TLS_KEY`, `AI_WEB_TLS_ADHOC` | HTTPS mode |
| `AI_WEB_ENABLE_SCHEDULER` | Set to `1` to enable the scheduler under WSGI |
| `AI_WEB_MAX_CONTENT_BYTES` | Request body cap (default 8 MB) |
| `AI_WEB_LOG_MAX_ENTRIES` | In-memory log window (default `1000`) |
| `AI_WEB_LOG_FILE`, `AI_WEB_SETTINGS_FILE`, `AI_WEB_HISTORY_DIR`, `AI_WEB_SKILLS_DIR`, `AI_WEB_SCHEDULE_FILE`, `AI_WEB_WORKSPACE_DIR` | Storage path overrides |
| `AI_WEB_MEMORY_DIR`, `AI_WEB_MEMORY_FILE`, `AI_WEB_DREAMS_FILE`, `AI_WEB_MEMORY_DB`, `AI_WEB_MEMORY_VEC_EXT` | Memory vault, Markdown files, SQLite index and optional `sqlite-vec` library |

## The chat page

- **Provider, model, and thinking level** are chosen in Settings and can be overridden for the next message from the toolbar above the chat box.
- **Command execution mode** sits next to them: `Ask first` (default) stops for approval before every tool call, while `Auto` and `Fast+` let the model use tools within the turn without that prompt when **Machine access** is off. With machine access on, every call asks regardless of the mode.
- **Attachments:** text-like files up to 1 MB are read in the browser and sent as text. Images and PDFs up to 6 MB are sent inline; audio and video work only with Gemini, and PDFs work with Gemini or Anthropic.
- Markdown rendering can be turned off in Settings. Messages can be copied; Enter sends and Shift+Enter adds a newline.

### Slash commands

Type `/` in the chat box to open the command menu.

| Command | Action |
| --- | --- |
| `/help` | List every command and available skill |
| `/new`, `/clear` | Start a fresh conversation context |
| `/model` | Show the active provider and model |
| `/models [provider] [model]` | List models, or switch provider/model |
| `/status` | Show the active provider, model, and readiness |
| `/ping` | Measure the server response time |
| `/fallback [model\|off]` | Show or change the fallback model |
| `/skills` | List available skills |
| `/skill <name> [prompt]` | Apply a skill to the next message, or to the given prompt now |
| `/<skill-name> [prompt]` | Shortcut for `/skill <skill-name> [prompt]` |

A skill invoked with a slash command applies to that request only and does not change the skills selected in Settings.

## Conversation history

Conversations are stored as JSON, grouped by date: `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json`. The `history/` folder is excluded from Git.

- Rename, pin, lock/unlock, and delete conversations from the sidebar.
- A locked conversation rejects message and title changes until it is unlocked.
- The API exposes `/api/history` and `/api/history/<id>` for the page; every request needs a paired session.

## Settings page

The Settings view is grouped into cards:

- **Connection** — provider, API key, Base URL, model list, a connection test, custom API keys that skills or schedules can reference, and the Gemini card.
- **Gemini** — capability report for the stored key (multimodal, Live, Decisions, agents), Decisions runner, managed-agent runner, and a Live API start button that mints a short-lived token in the browser.
- **Agent** — agent name, role, system prompt, memory-review instructions, and the skills selected for every conversation.
- **Response** — response language (`auto`, Thai, English), response style, markdown, clarifying questions, temperature, top-p, max tokens, streaming, thinking level, and the fallback model.
- **Integrations** — machine access and the Discord bot (token, prefix, allowlists).
- **Security** — Pairing Keys and connected devices, with per-device revoke and sign-out.
- **Update** — installed build, a dry-run check, a real update, and the update log.
- **Server** — start, stop, and restart through `start_web.sh`, plus PID and uptime.
- **Web and HTTPS** — HTTP/HTTPS mode, certificate state, and the restart notice with the new address.

## Local tools and approvals

Relative paths given to `list_files`, `read_file`, and `write_file`, and the starting folder of `run_command`, are the `workspace/` folder inside the project (override it with `AI_WEB_WORKSPACE_DIR`). The agent keeps the files it creates there, so they stay together and out of Git.

With **Machine access** on (the default) the model can use these tools anywhere on the machine:

| Tool | Purpose |
| --- | --- |
| `list_files` | List a directory |
| `read_file` | Read up to 200 KB of a file |
| `write_file` | Write up to 200 KB to a file |
| `run_command` | Run a shell command (60-second timeout, 100 KB output cap) |
| `create_skill` | Create a skill folder under `skills/`: `SKILL.md` with a name/description frontmatter and optional `scripts/`, `references/` and `assets/` files |
| `create_schedule`, `update_schedule` | Create or change cron-style jobs |

Every call — reads included — needs a single-use approval in the chat, bound to the exact tool name and arguments and valid for 15 minutes. Known API keys, tokens, and PEM private keys are redacted from tool output.

Turn **Settings → Machine access** off to restrict tools to the project folder and to the `pwd` / `ls` / `git status|diff|log` allowlist (no shell).

> ⚠️ An approved command runs with the privileges of the user running the app — including `sudo` when that user may use it without a password. Read each command before approving it.

## Scheduler

The **Schedule** page stores cron-style jobs (5-field cron) in `scheduled-jobs.json` and runs them while the server is up, using the server's timezone.

- Each job has a name, schedule, prompt, optional model, enable flag, and an optional Discord channel ID for the result.
- Jobs keep their own conversation in the history, with the last run time, status, and error.
- `AI_WEB_ENABLE_SCHEDULER=1` enables the scheduler when the app runs under an external WSGI server.

## Memory consolidation

The **Memory** page runs a background filter that turns conversations into long-term memory. It is not on the chat path: nothing is retrieved into replies yet.

- **Light Sleep** ingests new history, drops exact and near duplicates, writes `memory/YYYY-MM-DD.md` and stages candidates.
- **REM Sleep** looks back 7 days (configurable), groups repeated topics, and labels their themes with the configured model.
- **Deep Sleep** scores every candidate with local code (recency, frequency, model importance, novelty, an explicit "remember this"), promotes the ones above the threshold (default `0.65`) into `MEMORY.md`, and writes the night's summary to `DREAMS.md`.
- The default schedule is `0 3 * * *`. A run starts only after the configured idle time (15 minutes) has passed, and keeps retrying until the catch-up time (`06:00`). A conversation that starts after it is already running does not pause it.
- Storage is two-tier: plain Markdown in `memory/`, `MEMORY.md`, `DREAMS.md` (open or edit them in Obsidian) plus `.app-memory.db`, a SQLite file holding scores, vectors and the FTS5 keyword index. No database server is involved.
- When a `sqlite-vec` `vec0.so` is present at `vendor/sqlite-vec/vec0.so` it backs the vector index; otherwise vectors stay in the same SQLite file and are compared in Python. FTS5 is used when the local SQLite build provides it.
- Turning **Let a model help summarise** off runs the whole filter offline; importance then comes from local heuristics. The summary model can also use its own Base URL, so chat stays on a cloud provider while summaries run on a local llama-server or Ollama. Every promoted entry keeps a hidden marker in `MEMORY.md`, so **Forget** can remove it from both tiers.

## Logs

The **Logs** page shows recent system events and agent/tool activity: provider calls, tool approvals, schedules, and server actions. It never shows API keys or file content.

- The in-memory window keeps the newest 1000 entries; `logs/app-log.jsonl` keeps the persistent log.
- Entries can be downloaded as a file or deleted from the page.

## Update and server control

- **Update** shows the installed build and the last run, and can do a dry run (`update.sh --dry-run --no-restart`) or a real update. It runs `update.sh`, which replaces app files only and never touches `.env`, settings, auth state, certificates, history, logs, schedules, or `.venv`.
- **Server** sends start, stop, or restart to `start_web.sh`, which is the same script the CLI uses. A restart from the page waits two seconds so the response reaches the browser first.

## Discord bot

The app can run a Discord bot beside Flask and answer with the configured provider and model.

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent**, then invite the bot with the `bot` scope and permission to send messages.
3. In Settings, enter the bot token, enable Discord, and save.
4. Mention the bot or send `!ai <message>` (the prefix is configurable).

Slash commands: `/ai` sends work to the agent, `/new` opens a new chat with web history, `/models` changes provider/model, `/model` shows the active model and status, `/status` shows readiness, `/clear` clears the channel context, `/thread` creates a topic thread, `/fallback` sets a channel fallback, `/ping` checks latency, `/invite` builds an Administrator invite link, and `/help` lists everything. Changing the model and setting a fallback require the Discord **Administrator** permission; only a user with server-management rights can open the `/invite` link, because a bot cannot grant permissions to itself.

**Limit who can use the bot.** Settings has two allowlists: *Allowed channels* and *Allowed users*. A blank list means no limit; when filled, messages and slash commands from any other channel or user are ignored, so only the listed people and rooms can spend your API credit. A DM is allowed by its own DM channel ID — enable Discord **Developer Mode** and use *Copy ID*. The `.env` equivalents are `DISCORD_ALLOWED_CHANNEL_IDS` and `DISCORD_ALLOWED_USER_IDS`. Schedules sent to Discord still need Administrator rights.

## Device pairing

The web interface requires a paired device; Pairing Keys are generated only on the server.

- Create a key with `python app.py --pairing-key` (or `./start_web.sh --pair`). The first start with no paired device prints one automatically.
- On the client, open `http://<machine-ip>:5000/pair` and enter the key. A valid key issues an `HttpOnly` session cookie lasting `AI_WEB_SESSION_DAYS` (default 30).
- Keys are single-use and expire after `AI_WEB_PAIRING_TTL_MINUTES` (default 30). Only SHA-256 hashes are stored, in `.app-auth.json`, which is excluded from Git.
- Review, revoke, or add devices in **Settings → Security**. `python app.py --revoke-sessions` revokes every device.
- `AI_WEB_AUTH=off` disables pairing and is meant only for a fully trusted network. Unpaired pages redirect to `/pair`; `/api/auth/status` stays reachable for health checks.
- Behind a TLS-terminating reverse proxy set `AI_WEB_TRUST_PROXY=1` so `X-Forwarded-Proto` is trusted and the session cookie is marked `Secure`.

## HTTPS

The app can terminate HTTPS itself; `openssl` is the only requirement.

- **From the page:** **Settings → Web and HTTPS**, choose HTTP, HTTPS with certificate files, or HTTPS with an ad-hoc certificate, save, and restart. A page cannot follow a restart that changes the protocol, so it shows the new address instead.
- Create a self-signed certificate for the LAN IP: `./start_web.sh --make-cert 192.168.0.50` (on Termux install `openssl` with `pkg install openssl-tool`). It writes `certs/cert.pem` and `certs/key.pem`, which are excluded from Git.
- Set `AI_WEB_TLS_CERT` and `AI_WEB_TLS_KEY` in `.env`, run `./start_web.sh --restart`, then open `https://<machine-ip>:5000`. Session cookies become `Secure` automatically.
- The page's "certificate files" mode prefers `certs/cert.pem` + `certs/key.pem`; without them it keeps a usable pair already set in `.env` instead of refusing the mode the server is running with.
- `AI_WEB_TLS_ADHOC=1` (or the ad-hoc mode in the page) creates a self-signed certificate with `openssl`, covering `localhost`, `127.0.0.1`, the hostname, and the LAN address, and reuses `certs/adhoc-cert.pem` / `certs/adhoc-key.pem` on later starts. No Python `cryptography` package is needed.
- Switching HTTPS → HTTP does not keep the old sign-in: browsers do not send the `Secure` cookie over HTTP, and `ai-web-session-http` is issued only after a new pairing. The separate cookie name is what lets a device pair again over HTTP.
- A self-signed certificate warns the browser once. Use a certificate from a trusted CA, or install your local CA on each device, to avoid it.
- Behind a reverse proxy (Caddy, nginx, `tailscale serve`) leave `AI_WEB_TLS_*` empty and set `AI_WEB_TRUST_PROXY=1`; the proxy must overwrite `X-Forwarded-Proto` on every request.
- `tailscale cert` must run on the node that owns the name. The Tailscale app on Android has no CLI, so a Termux/Android server cannot issue its own Tailscale certificate — run `tailscale serve` on another tailnet node that proxies to it, or use a trusted CA.

## Files and data

| Path | Contents | Committed |
| --- | --- | --- |
| `app.py` | Flask assembly and entrypoint (app, hooks, blueprints, server) | yes |
| `core/` | Settings, storage, providers, tools, TLS and shared helpers | yes |
| `services/` | Cron scheduler and the optional Discord bot | yes |
| `routes/` | HTTP blueprints for the chat page and the pairing page | yes |
| `memory_engine.py` | Background memory consolidation (Light/REM/Deep) | yes |
| `templates/index/` | Chat page HTML, CSS, JS (chat, settings, schedule, logs, about) | yes |
| `templates/pair/` | Pairing page HTML, CSS, JS | yes |
| `skills/` | Skills, one folder per skill: `SKILL.md` plus optional `scripts/`, `references/` and `assets/` | yes (unless you add your own) |
| `install.sh`, `start_web.sh`, `update.sh` | Installer, process control, updater | yes |
| `.env` | Provider keys and runtime configuration | no |
| `.app-settings.json` | Settings saved from the page | no |
| `.app-auth.json` | Pairing Key and session hashes | no |
| `certs/` | TLS certificate, private key, ad-hoc files | no |
| `history/` | Conversation history | no |
| `logs/` | Application and server logs | no |
| `scheduled-jobs.json` | Scheduled jobs | no |
| `memory/`, `MEMORY.md`, `DREAMS.md` | Daily notes and promoted long-term memory | no |
| `.app-memory.db` | SQLite memory index: scores, vectors, FTS5 | no |

Never commit `.env`, `.app-settings.json`, `.app-auth.json`, `certs/` (especially `key.pem`), `history/`, `logs/`, `scheduled-jobs.json`, `memory/`, `MEMORY.md`, `DREAMS.md`, or `.app-memory.db`, and never copy them between machines.
