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

### Scheduler

Scheduled jobs run while the server is running. Set `AI_WEB_ENABLE_SCHEDULER=1` to enable the scheduler for WSGI deployments.
