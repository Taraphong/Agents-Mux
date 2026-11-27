# AI Web Installation Guide

This guide is for running the project on your own machine: Termux on Android, Linux, or macOS. Every command can be copied straight into a terminal.

Thai: **[INSTALL.th.md](INSTALL.th.md)**

> The web interface requires a paired device (Pairing Key). Use it only on a trusted network and do not expose it directly to the internet.

---

## Requirements

- Python **3.10 or newer** (on Termux: `pkg install python`)
- `git` (or download the project as a ZIP)
- At least one API key: OpenAI / OpenRouter / Groq / Gemini / Anthropic / Hugging Face
- `openssl` only if the server should terminate HTTPS (on Termux: `pkg install openssl-tool`)
- Termux, Linux, and macOS are supported; the code uses `fcntl`, so Windows is not supported

---

## Quick start: install with the script

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

`install.sh` does the following:

1. Checks for a supported Python version (or reuses a working `.venv`).
2. Creates a virtual environment in `.venv`.
3. Installs the dependencies from `requirements.txt`.
4. Creates `.env` from `.env.example` with mode `0600` and never overwrites an existing file.
5. Creates the `logs/` and `history/` folders.
6. On Termux it also links the short `startweb` command into `$PREFIX/bin`.

After installation, put your API key in `.env` and start the server (see below).

> If the repository is private, clone it over SSH (`git clone git@github.com:Taraphong/Agents-mux.git`) or download the ZIP, extract it, and run `bash install.sh` inside that folder.

---

## Install on Termux (Android)

```bash
pkg update && pkg upgrade -y
pkg install -y python git
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

Set the API key:

```bash
nano .env
```

Edit the provider and its key, for example:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx
```

Save with `Ctrl+O` → `Enter` → `Ctrl+X`.

Start the server:

```bash
./start_web.sh --start      # or: startweb --start
```

Open `http://127.0.0.1:5000` in a browser, or `http://<device-ip>:5000` from a phone or computer on the same Wi-Fi network.

The first start without a paired device prints a Pairing Key (it is also written to `logs/ai-web.log`). Open `http://<device-ip>:5000/pair`, enter the key, and the device is signed in.

Find the device IP:

```bash
ifconfig 2>/dev/null | grep -A1 wlan0
# or
ip -4 addr show
```

> Run `termux-wake-lock` so Android does not suspend the server, and on Android 12+ disable battery restrictions for Termux.

---

## Install on Linux

Debian / Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv git
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

Fedora:

```bash
sudo dnf install -y python3 git
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

Then edit `.env`, start the server, and open `http://127.0.0.1:5000` as in the Termux steps. On Linux, start the server with `./start_web.sh --start`; the `startweb` shortcut is installed only on Termux.

---

## Install on macOS

If you do not have the Command Line Tools yet, run:

```bash
xcode-select --install
```

Follow the installer and wait for it to finish before running `git clone`.

Install Python **3.10 or newer** with the macOS installer from [python.org](https://www.python.org/downloads/macos/), then open a new terminal (see the [Python on macOS guide](https://docs.python.org/3/using/mac.html)). Check that `python3` on your `PATH` is a supported version before running `install.sh`:

```bash
command -v python3
python3 --version
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'
```

If `python3` is missing or older than 3.10, adjust `PATH` to select the Python you just installed and check again until it passes, then run:

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

---

## Configure `.env`

The values worth knowing:

| Variable | Meaning |
| --- | --- |
| `AI_PROVIDER` | Primary provider: `openai`, `gemini`, `anthropic`, `hf`, `or`, `groq` |
| `OPENAI_API_KEY` | API key for OpenAI or a compatible API |
| `GEMINI_API_KEY` | API key for Google Gemini |
| `ANTHROPIC_API_KEY` | API key for Anthropic (Claude) |
| `OPENROUTER_API_KEY` | API key for OpenRouter |
| `GROQ_API_KEY` | API key for Groq |
| `HF_API_KEY` | API key for Hugging Face |
| `AI_BASE_URL` | Custom Base URL for the active provider (may be empty) |
| `AI_FALLBACK_PROVIDER`, `AI_FALLBACK_MODEL` | Initial fallback provider/model |
| `DISCORD_BOT_TOKEN`, `DISCORD_BOT_PREFIX` | Discord bot token and message prefix |
| `DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_CHANNEL_IDS` | Discord allowlists (comma-separated IDs) |
| `AI_WEB_AUTH` | `on` by default; `off` disables device pairing |
| `AI_WEB_PAIRING_TTL_MINUTES`, `AI_WEB_SESSION_DAYS` | Pairing Key lifetime (30 min) and session lifetime (30 days) |
| `AI_WEB_TRUST_PROXY` | `1` when a reverse proxy terminates TLS |
| `AI_WEB_TLS_CERT`, `AI_WEB_TLS_KEY`, `AI_WEB_TLS_ADHOC` | HTTPS mode |
| `AI_WEB_ENABLE_SCHEDULER` | `1` to enable scheduled jobs under WSGI, `0` to turn them off under `python app.py` |
| `PORT` | Listen port (default `5000`) |

The sample file also lists the storage-path and limit variables (`AI_WEB_LOG_FILE`, `AI_WEB_SETTINGS_FILE`, `AI_WEB_HISTORY_DIR`, `AI_WEB_SKILLS_DIR`, `AI_WEB_MAX_CONTENT_BYTES`, `AI_WEB_LOG_MAX_ENTRIES`, …).

### Using Anthropic (Claude)

Anthropic needs both the key and a matching model.

```dotenv
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

Then open **Settings** in the web interface, select **Anthropic**, and pick a Claude model from the list (the list is fetched from the API once a key is present).

> The startup `model` value comes from `OPENAI_MODEL`, which is an OpenAI model. If you do not select a Claude model in Settings, API calls will fail.

### Precedence: `.env` versus Settings

- `.env` is read when the process starts and is used only as the **default**.
- Every save in **Settings** writes the values to `.app-settings.json`.
- Once `.app-settings.json` exists, the saved values **override `.env`**, including provider, model, and API key.
- If editing `.env` has no effect, change the value in Settings, or press **Reset** at the bottom of Settings (it deletes `.app-settings.json`) and restart the server.
- An API key saved through Settings is always used before a key in `.env`.

Everything else — system prompt, temperature, model, thinking level, Discord bot, allowlists, machine access — is configured in **Settings** and stored only in `.app-settings.json` on your machine.

> `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/`, and `scheduled-jobs.json` are not committed to Git. Do not send them to anyone: they contain API keys, pairing state, and conversation history.

---

## Start / stop / check the server

```bash
./start_web.sh --start     # start (if not already running)
./start_web.sh --check     # show status and the real http:// or https:// address
./start_web.sh --restart   # stop and start again (use after updating app.py or HTML)
./start_web.sh --stop      # stop
./start_web.sh --pair      # create a single-use Pairing Key
./start_web.sh --make-cert [ip]   # create a self-signed HTTPS certificate
```

On Termux, after running `install.sh`, the short command is also available:

```bash
startweb --start
startweb --restart
startweb --check
startweb --stop
```

`.css` and `.js` files are read from disk on every request, so changing them needs only a browser reload. A change to `app.py` or a template `.html` file needs `--restart`.

Server logs are in `logs/ai-web.log` inside the project folder (`logs/` is not committed).

To run with live logs in the terminal instead (the server stops when the terminal closes):

```bash
source .venv/bin/activate
python app.py
```

---

## Access from another device on the network

The server listens on `0.0.0.0` port `5000` by default.

1. Find the IP of the machine running the server (for example `192.168.0.50`).
2. Open a browser on another device on the same network: `http://192.168.0.50:5000`.
3. If it does not load, check that the machine's firewall allows port 5000.

Change the port with `PORT` in `.env` or for one run:

```bash
PORT=8080 ./start_web.sh --restart
```

Use `--restart` (or `--stop` then `--start`) because `--start` does nothing when the server is already running, and a new port takes effect only after the old process stops and a new one starts.

---

## First sign-in (device pairing)

1. Create a Pairing Key on the server: `./start_web.sh --pair`. The first start with no paired device also prints one.
2. On the client, open `http://<device-ip>:5000/pair` and enter the key.
3. The device receives an `HttpOnly` session cookie that lasts `AI_WEB_SESSION_DAYS` (default 30).
4. Manage or revoke devices in **Settings → Security**. `python app.py --revoke-sessions` signs every device out.

Keys are single-use and expire after `AI_WEB_PAIRING_TTL_MINUTES` (default 30). `AI_WEB_AUTH=off` disables pairing and is meant only for a fully trusted network.

---

## HTTPS

The server can terminate HTTPS itself; `openssl` is the only extra requirement (`pkg install openssl-tool` on Termux).

The easiest route is the page: **Settings → Web and HTTPS**, pick a mode, save, then restart. A page cannot follow a restart that changes the protocol, so it shows the new address to open.

From the shell, create a self-signed certificate and enable it:

```bash
./start_web.sh --make-cert 192.168.0.50   # writes certs/cert.pem and certs/key.pem
# set AI_WEB_TLS_CERT=/path/to/certs/cert.pem and AI_WEB_TLS_KEY=/path/to/certs/key.pem in .env
./start_web.sh --restart
./start_web.sh --check                    # prints the real http:// or https:// address
```

- With `AI_WEB_TLS_CERT` + `AI_WEB_TLS_KEY` the server uses those files; the page's "certificate files" mode prefers `certs/cert.pem` + `certs/key.pem` and otherwise keeps a usable pair already set in `.env`.
- With `AI_WEB_TLS_ADHOC=1` the server creates a self-signed certificate with `openssl` on first start (SAN: `localhost`, `127.0.0.1`, hostname, LAN address) and reuses `certs/adhoc-cert.pem` / `certs/adhoc-key.pem` afterwards. No Python `cryptography` package is needed.
- A self-signed certificate warns each browser once; accepting it is enough. For a warning-free setup use a trusted CA, install your local CA on the device, or put a reverse proxy (Caddy, nginx, `tailscale serve`) in front and set `AI_WEB_TRUST_PROXY=1`.
- `tailscale cert` only works on the node that owns the name. The Android Tailscale app has no CLI, so a Termux server cannot issue its own Tailscale certificate; run `tailscale serve` on another node instead.
- Switching HTTPS → HTTP does not keep the old sign-in. The browser will not send the `Secure` cookie over HTTP, so pair the device again over HTTP (the page uses a separate cookie name for that reason).

---

## Update the project

Run the updater on the machine that serves the app:

```bash
cd ~/ai-web
./update.sh
```

`update.sh` downloads the newest app files from GitHub (default `main`), installs dependencies only when `requirements.txt` changed, restarts the server, and checks that it answers. It never touches `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/`, `scheduled-jobs.json`, or `.venv`.

Options:

```bash
./update.sh --branch dev     # another branch
./update.sh --repo owner/repo
./update.sh --dry-run        # show what would change, write nothing
./update.sh --no-restart     # copy files only, no restart or health check
./update.sh --help
```

The same update can be started from **Settings → Update**, which also offers a dry-run check and shows the update log.

If the GitHub repository is private, give the updater a read-only token:

```bash
# Ask for the token without echoing it, then export it for this shell only.
read -rsp "GitHub token: " AI_WEB_UPDATE_TOKEN; echo
export AI_WEB_UPDATE_TOKEN
./update.sh
# or export GITHUB_TOKEN instead (same read prompt)
```

The token is used only for the download and is never written to disk.

With a Git checkout you can still update manually:

```bash
cd ~/ai-web
git pull
bash install.sh            # reinstall dependencies if they changed
./start_web.sh --restart
```

Existing data (`.env`, `.app-settings.json`, `.app-auth.json`, `history/`, `certs/`) is never overwritten.

---

## Common problems

**`command not found: python3`**
Install Python first: `pkg install python` (Termux) or `sudo apt install python3 python3-venv` (Debian/Ubuntu).

**`ensurepip is not available` / creating `.venv` fails**
Debian/Ubuntu: run `sudo apt install python3-venv`, then `bash install.sh` again.

**Installing dependencies fails**
Check the connection and try again, or upgrade pip first:
`./.venv/bin/python -m pip install --upgrade pip`

**The page redirects to `/pair` and I have no key**
Create one on the server with `./start_web.sh --pair` and read it from the terminal or `logs/ai-web.log`.

**Cannot open the site from another device**
Check that you are using an IP on the same network, that the server is running (`./start_web.sh --check`), and that the firewall allows port 5000.

**The page does not change after editing code**
Flask runs with `debug=False`; restart it with `./start_web.sh --restart` (`.css`/`.js` only need a reload).

**The API returns 401 / 403 / 502**
`401` means the device is not paired. `403` usually means the request came from another origin. `502`/`503` come from the provider: check that the API key is valid, that `AI_PROVIDER` matches the key, and that the selected model exists for that provider (this is the usual Anthropic symptom).

**Scheduled jobs do not run**
The scheduler runs only while the server is running. `python app.py` starts it by default; set `AI_WEB_ENABLE_SCHEDULER=0` to turn it off. Under an external WSGI server set `AI_WEB_ENABLE_SCHEDULER=1`.

---

## Uninstall

```bash
./start_web.sh --stop
cd ~
rm -rf ~/ai-web          # removes the whole project, including history and API keys
rm -f "$PREFIX/bin/startweb"   # Termux only: remove the short command
```

> `rm -rf` also deletes `.env` and `history/`. Back up the `history/` folder first if you want to keep your conversations.
