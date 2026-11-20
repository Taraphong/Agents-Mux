# Security Policy

AI Web on Termux is a **single-owner, self-hosted** application. It is designed to run on a machine you control, on a network you trust, and it assumes the person operating the server is the person who should have access to it. It is not a multi-tenant service and it has not been audited for exposure to the public internet.

Thai: **[SECURITY.th.md](SECURITY.th.md)**

## Supported versions

This project does not publish versioned releases. Only the **latest commit on the `main` branch** is supported. Security fixes are made on `main`; older commits and forks are not maintained.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub Security Advisories:

<https://github.com/Taraphong/Agents-mux/security/advisories/new>

Include, where you can:

- what the problem is and which component is affected (`app.py`, a template, `start_web.sh`, `install.sh`, `update.sh`, a Skill, …);
- step-by-step reproduction, or a proof-of-concept request/command;
- the affected commit (`git rev-parse HEAD`) and your environment (Termux, Linux, macOS; Python version);
- the impact you believe it has, and any mitigation you already found.

Never attach real API keys, Pairing Keys, session cookies, `.env` or `.app-auth.json` contents, `certs/key.pem`, conversation history, or logs that contain them. Redact them first.

## What to expect

This is a volunteer-maintained personal project, so response is **best effort** and there is no bug bounty. You can expect an acknowledgement, a request for details if needed, and a note when the report is fixed or declined as out of scope. Please give a reasonable amount of time to fix the issue before any public disclosure.

## Scope

**In scope**

- Authentication bypass of the device-pairing gate, or reuse of a consumed/expired Pairing Key.
- Reading secrets (API keys, the Discord token, private keys, session tokens, other users' history) through the web UI, an API response, a tool call, or the app log.
- Path traversal or escape from the project root through file tools, Skills, scheduling, or static asset routes.
- Cross-site request forgery, cross-site scripting, or cookie handling flaws in the web interface.
- Remote code execution or command execution outside the documented tool approval flow.
- Incorrect TLS/proxy handling that causes the session cookie to leak or be sent in the clear.
- Sending a stored provider key to a plain-HTTP endpoint without the explicit `AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP=1` opt-in.

**Out of scope**

- Anything that requires an already paired device, shell access as the user running the app, or filesystem access to the server (see [Known limitations](#known-limitations)).
- The operator configuring a malicious `Base URL`, model, prompt, skill, or schedule — the server sends keys and runs work where the operator tells it to.
- Prompt-injection content produced by a model, and actions the owner approves in the UI.
- Self-signed certificate warnings, or missing hardening in a deliberately insecure configuration (`AI_WEB_AUTH=off`, plain HTTP on an untrusted network).
- Denial of service by a paired device, and cost from API usage by a paired device or a schedule.
- Vulnerabilities in third-party packages that are already publicly known and fixed in a newer release.

## Security model

| Area | How it works |
| --- | --- |
| Network | The server binds `0.0.0.0:5000` by default and gives every paired device the same privileges. There are no per-user accounts or roles. |
| Device pairing | Enabled by default (`AI_WEB_AUTH=on`). Pairing keys are generated **only on the server** (`python app.py --pairing-key`, `./start_web.sh --pair`), are single-use, and expire after `AI_WEB_PAIRING_TTL_MINUTES` (default 30). This is the only way to create a session. |
| Session cookie | The key is exchanged at `POST /api/auth/pair` for a 32-byte random token: `ai-web-session` over HTTPS and `ai-web-session-http` over HTTP, both `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` whenever the request is HTTPS. Two names are needed because browsers refuse to let an insecure origin overwrite a `Secure` cookie of the same name, so switching HTTPS → HTTP would otherwise leave a device unable to pair again. The server accepts either cookie, logs out both, and sessions last `AI_WEB_SESSION_DAYS` (default 30) and can be revoked individually or all at once. |
| Secrets at rest | Only SHA-256 hashes of Pairing Keys and session tokens go into `.app-auth.json`. API keys and the Discord token live in `.env` and `.app-settings.json`. The settings and auth stores are written atomically with `0600` permissions; `install.sh` creates `.env` as `0600` and `start_web.sh` protects `certs/key.pem`. |
| Brute force | Pairing failures are rate-limited per client address (8 failures in 5 minutes, then HTTP 429). Key comparison uses constant-time comparison. |
| Request gate | A `before_request` hook sends unpaired browsers to `/pair` and answers unpaired `/api/*` calls with `401`. Only `/pair`, `/api/auth/pair`, `/api/auth/status`, and page CSS/JS under `/static/` and `/templates/` are public. |
| CSRF | State-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) are rejected with `403` when the browser reports `Sec-Fetch-Site: same-site` or `cross-site`, or when a present `Origin` does not match the request host. `same-site` is refused because cookies are not scoped by port or scheme, so a page on another port or subdomain of the same host could send the session cookie; an architecture with the UI and the API on different ports or subdomains is therefore not supported — serve both from one origin. Requests without `Origin` or `Sec-Fetch-Site` (curl, scripts) are allowed by design. |
| Secret exposure in responses | `GET /api/settings` never returns stored API keys, custom API keys, or the Discord token — only a `••••••••` placeholder plus `has_api_key` / `has_discord_token` flags. Provider errors are redacted before they reach the page or the log. |
| Provider keys in transit | A model request refuses to send the key over plain HTTP, except to a loopback host (a local OpenAI-compatible server) or when the operator sets `AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP=1`, which is logged. |
| Logs and tool output | Log records drop fields named `api_key`, `authorization`, `token`, and `content`; all logged text is scrubbed of configured secrets, `?key=`-style query values, and PEM private-key blocks. Tool output is redacted the same way before it reaches the browser or the log. |
| Local tools | With **Machine access** on (default), `read_file`, `list_files`, `write_file`, `run_command`, `create_skill`, `create_schedule`, and `update_schedule` reach the whole machine, and `run_command` runs through a real shell as the service user (pipes, redirections, and `sudo` when that user may run it without a password). Every tool call — reads included — needs a one-time approval token bound to the exact tool name and arguments (15-minute TTL), and with machine access on no chat command mode can skip it. Known API keys, tokens, and PEM private keys are redacted from tool output. With machine access off, paths return to the project root with `PROTECTED_PARTS` / `PROTECTED_NAMES`, and `run_command` uses the `pwd` / `ls` / `git` allowlist without a shell. Reads and writes are capped at 200 KB. |
| Skills | Skill names are validated, content is loaded only from `<skills>/<name>/SKILL.md`, and `create_skill` writes only inside the `skills/` folder. A skill is plain instruction text for the model; it grants no new tools. |
| Scheduler | Jobs are validated 5-field cron expressions, stored in `scheduled-jobs.json` (`0600`, ignored by Git, written under a file lock), and run only while the server is up. A job prompt runs with the saved provider/model and the same tool approval rules; an optional Discord channel receives the result. |
| Update and server control | `POST /api/update/run` and `POST /api/server/action` accept only fixed modes and actions, run the project scripts detached with a quoted argument list (no shell interpolation of user input), require a paired device and a same-origin request, and never receive secrets in their body. `update.sh` never writes `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/`, `scheduled-jobs.json`, or `.venv`. |
| Uploads and attachments | Requests are capped by `MAX_CONTENT_LENGTH` (default 8 MB, `AI_WEB_MAX_CONTENT_BYTES`). Attachments are size-checked in the browser (1 MB text, 6 MB binary) and again on the server (6 MB per inline part) before they are forwarded to a provider. |
| Gemini Live tokens | The browser never receives the Gemini API key. `POST /api/gemini/live-token` mints a single-use, short-lived token (30-minute expiry, one session) and returns the WebSocket URL; the token is the only credential the page sees. |
| TLS | The app can terminate HTTPS itself with certificate files or an ad-hoc certificate (both generated with `openssl`; ad-hoc files live in `certs/adhoc-*.pem` and are reused), or sit behind a TLS-terminating reverse proxy. `ProxyFix` is enabled only when `AI_WEB_TRUST_PROXY=1`, and that must be set only when the proxy overwrites `X-Forwarded-Proto` / `X-Forwarded-Host` on every request. |
| Discord bot | Optional and off by default. It never exposes filesystem or command tools; only `create_schedule` / `update_schedule` are auto-approved, and only for guild members with the Discord **Administrator** permission. By default any Discord user who can DM the bot or mention it in a guild can chat with the configured model and spend API credit; set **Allowed channels** / **Allowed users** in Settings (or `DISCORD_ALLOWED_CHANNEL_IDS` / `DISCORD_ALLOWED_USER_IDS`) to ignore everyone else. |

## Hardening checklist

- Keep `AI_WEB_AUTH=on`. Set it to `off` only on a fully trusted network, and remember that anyone who can reach the page then gets the tools and API keys.
- Serve HTTPS. If you accept a self-signed certificate warning on a hostile network, traffic can be intercepted. Use a certificate from a trusted CA, or install your local CA on each device.
- Behind a reverse proxy set `AI_WEB_TRUST_PROXY=1` **only** if the proxy strips and overwrites `X-Forwarded-*` headers. Otherwise clients can spoof them.
- Run the server as an **unprivileged user**, never as root. The tools run with the server's privileges; the path checks are best-effort, not a sandbox.
- Do not expose the port to the internet. Use a VPN or a reverse proxy with authentication, and keep it on a trusted LAN/VPN.
- Keep `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/`, and `scheduled-jobs.json` readable only by the service user (mode `0600` / `0700`). They are in `.gitignore` — keep it that way.
- Review **Settings → Security** regularly, revoke devices you no longer use, and rotate provider keys if one was ever pasted into a chat, a log, or a commit.
- Treat `history/` and `logs/` as sensitive: conversations can contain personal data, attachments, and text from files the agent read.
- Keep dependencies current. Dependabot proposes updates; review and merge them, then restart the server.
- Restrict the Discord bot (private guild, limited DMs) if you enable it, and remember its answers are billed to your provider key. The **Allowed channels** / **Allowed users** lists are the supported way to enforce that inside the app.
- Review scheduled jobs you did not create: a job runs its prompt without supervision while the server is up.
- Back up `.env` and `.app-auth.json` securely if you want pairing to survive a rebuild, and never copy them between machines.

## Protecting secrets when contributing

- Never commit `.env`, `.app-settings.json`, `.app-auth.json`, `certs/` (especially `key.pem`), `history/`, `logs/`, `scheduled-jobs.json`, `.venv/`, or `__pycache__/`.
- Never paste a real API key, Pairing Key, or session token into an issue, pull request, commit message, test fixture, or screenshot.
- If a secret is committed, treat it as compromised: revoke/rotate it at the provider, run `python app.py --revoke-sessions`, remove the secret from Git history, and restart the server.
- If you add a new machine-specific data file, add it to `.gitignore`, to `PROTECTED_PARTS` / `PROTECTED_NAMES` in `app.py`, and to the rsync exclude list in `AGENTS.md`.

## Known limitations

- **No encryption at rest.** `.env`, `.app-settings.json`, `history/`, `scheduled-jobs.json`, `memory/`, `MEMORY.md`, `DREAMS.md`, and `.app-memory.db` are plaintext. Anyone with read access to the server's filesystem can read the API keys, every conversation, and every promoted memory.
- **Memory runs unattended.** The nightly consolidation sends candidate texts to the configured model for a theme and importance rating unless **Let a model help summarise** is off. The model gets no tools, known credentials are redacted first, and forgetting an entry removes it from `MEMORY.md` and the index - but nothing is encrypted or backed up automatically.
- **The tools are not a sandbox.** They run as the service user. Run on a dedicated, unprivileged account and do not co-locate unrelated secrets on the same machine.
- **Machine access is a boundary, not a sandbox.** With it on, an approved call can read or change anything the service user can reach, and `sudo` reaches root when the service user has passwordless sudo or the app runs as root. Read each approval prompt before clicking it; turn Machine access off to return to project-only paths and the command allowlist.
- **The operator can redirect keys.** `Base URL` is configurable, so whoever can edit Settings can point a provider request at another endpoint (HTTPS, unless loopback or the insecure-HTTP opt-in applies). Paired devices are fully trusted.
- **Prompt injection is possible.** Model output is not trusted input. Tool use requires approval, but an approved command runs as-is.
- **Attachments leave the machine.** Anything you attach is sent to the selected provider. With Gemini, audio and video are sent inline; with Gemini or Anthropic, PDFs are.
- **Update and server control run local scripts.** A paired device can start `update.sh`, which replaces app files from GitHub, and can restart or stop the server. Keep pairing limited to devices you trust.
- **Schedules run unattended.** A job spends API credit and runs tools under the same rules as a chat message, without anyone watching the output.
- **No chat rate limit.** Pairing attempts are limited, but a paired device can send as many prompts as it likes, at your API cost.
- **The Discord bot trusts DMs unless restricted.** Anyone who can message the bot gets model access (but not filesystem or command tools). Set **Allowed users** and/or **Allowed channels** so the bot ignores everyone else.
- **Self-signed TLS warns.** Browsers warn on first visit; accepting the warning on an untrusted network exposes the session cookie to interception.
- **No security audit.** This project has not been pen-tested or audited. Review the code before exposing it to anyone else.
