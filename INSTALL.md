# AI Web Installation Guide

This guide is for anyone who wants to run the project on their own machine (Termux on Android, Linux, or macOS). Every command can be copied straight into a terminal.

> The web interface requires a paired device (Pairing Key). Use it only on a trusted network and do not expose it directly to the internet.

---

## Requirements

- Python **3.10 or newer** (on Termux install it with `pkg install python`)
- `git` (or download the project as a ZIP)
- At least one API key: OpenAI / OpenRouter / Groq / Gemini / Anthropic / Hugging Face
- Only Termux, Linux, and macOS are supported (the code uses `fcntl`, so Windows is not supported yet)

---

## Quick start: install with the script

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

The `install.sh` script does all of this:

1. Checks that Python is a supported version.
2. Creates a virtual environment in `.venv`.
3. Installs dependencies from `requirements.txt`.
4. Creates `.env` from `.env.example` (it never overwrites an existing file).
5. Creates the `logs/` and `history/` directories.
6. On Termux it also installs the short `startweb` command.

After installation, put your API key in `.env` and start the server (see the next section).

> If the repository is private, clone it over SSH (`git clone git@github.com:Taraphong/Agents-mux.git`) or download the ZIP and extract it, then run `bash install.sh` inside that folder.

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

Edit the line for the provider you want, for example:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx
```

Save with `Ctrl+O` → `Enter` → `Ctrl+X`.

Start the server:

```bash
./start_web.sh --start      # or startweb --start
```

Open `http://127.0.0.1:5000` in a browser, or open `http://<Termux-device-IP>:5000` from a phone or computer on the same Wi-Fi network.

Find the device IP:

```bash
ifconfig 2>/dev/null | grep -A1 wlan0
# or
ip -4 addr show
```

> Run `termux-wake-lock` to stop Android from suspending the server, and on Android 12+ disable battery restrictions for Termux.

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

Then edit `.env`, start the server, and open `http://127.0.0.1:5000` as in the Termux steps.

---

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:db2c7623a534bf3be76397b2dbe85d910b20128e1cd5b711eb1d2618b9be800c -->

## Install on macOS

If you do not have the Command Line Tools yet, run:

```bash
xcode-select --install
```

Follow the Command Line Tools installer and wait for it to finish before running `git clone`.

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

<!-- /coderabbit-ai-generated:v1 -->

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
| `AI_BASE_URL` | Use this to point at a custom Base URL (may be left empty) |
| `AI_WEB_ENABLE_SCHEDULER` | Set to `1` when running under WSGI to enable the scheduler |

### Using Anthropic (Claude)

Anthropic needs two settings to match: the API key and the model.

```dotenv
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

Then open **Settings** in the web interface, select the **Anthropic** provider, and pick a Claude model from the list (the model list is fetched from the API once a key is present).

> The app's default `model` comes from `OPENAI_MODEL`, which is an OpenAI model. If you do not select a Claude model in Settings, API calls will fail.

### Precedence: `.env` versus Settings

- `.env` is read when the process starts and is used only as the **default**.
- Every time you save in **Settings**, the values are written to `.app-settings.json`.
- Once `.app-settings.json` exists, the saved values **override `.env`**, including provider, model, and API key.
- If editing `.env` has no effect, change the value in Settings instead, or stop the server, edit/delete `.app-settings.json`, and start it again.
- An API key saved through Settings is always used before a key in `.env`.

Other values (system prompt, temperature, model, Discord bot, etc.) are configured in **Settings** in the web interface and are stored only in `.app-settings.json` on your machine.

> `.env`, `.app-settings.json`, `history/`, and `.venv/` are not committed to Git. Do not send these files to anyone, because they contain API keys and conversation history.

---

## Start / stop / check the server

```bash
./start_web.sh --start     # start (if not already running)
./start_web.sh --check     # show status
./start_web.sh --restart   # stop and start again (use after updating code)
./start_web.sh --stop      # stop
```

On Termux, after running `install.sh`, you can use the short command:

```bash
startweb --start
startweb --restart
startweb --check
startweb --stop
```

Server logs are in `logs/ai-web.log` inside the project folder (the `logs/` folder is not committed).

Alternatively, run it with live logs in the terminal (the server stops when you close the terminal):

```bash
source .venv/bin/activate
python app.py
```

---

## Access from another device on the network

The server already listens on `0.0.0.0` port `5000`.

1. Find the IP of the machine running the server (for example `192.168.1.50`).
2. Open a browser on another device on the same Wi-Fi network: `http://192.168.1.50:5000`.
3. If it does not load, check that the machine's firewall allows port 5000.

Change the port with:

```bash
PORT=8080 ./start_web.sh --restart
```

You must use `--restart` (or `--stop` and then `--start`) because `--start` does nothing when the server is already running, and a new port takes effect only after the old process has stopped and a new one has started.

---

## Update the project

If the project folder has this script, run it on the machine that serves the app:

```bash
cd ~/ai-web
./update.sh
```

`update.sh` downloads the newest app files from GitHub (default `main`), installs
dependencies only when `requirements.txt` changed, restarts the server, and
checks that it answers. It never touches `.env`, `.app-settings.json`,
`.app-auth.json`, `certs/`, `history/`, `logs/`, or `.venv`. Use
`./update.sh --branch <name>` for another branch and `--dry-run` to preview the
change.

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

Existing data (`.env`, `.app-settings.json`, `history/`) is never overwritten.

---

## Common problems

**`command not found: python3`**
Install Python first: `pkg install python` (Termux) or `sudo apt install python3 python3-venv` (Debian/Ubuntu).

**`ensurepip is not available` / creating `.venv` fails**
Debian/Ubuntu: run `sudo apt install python3-venv` and then run `bash install.sh` again.

**Installing dependencies fails**
Check your internet connection and try again, or upgrade pip first:
`./.venv/bin/python -m pip install --upgrade pip`

**Cannot open the site from another device**
Check that you are using an IP on the same network, that the server is running (`./start_web.sh --check`), and that the firewall allows port 5000.

**The page does not change after editing code or updating**
Flask runs with `debug=False`, so restart it: `./start_web.sh --restart`

**The API returns 401 / 403**
The API key in `.env` is invalid or expired, or `AI_PROVIDER` is not set to match the key you have.

---

## Uninstall

```bash
./start_web.sh --stop
cd ~
rm -rf ~/ai-web          # removes the whole project, including history and API keys
rm -f "$PREFIX/bin/startweb"   # Termux only: remove the short command
```

> `rm -rf` also deletes `.env` and `history/`. If you want to keep your conversations, back up the `history/` folder first.
