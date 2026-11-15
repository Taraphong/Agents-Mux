# Security Policy / นโยบายความปลอดภัย

AI Web on Termux is a **single-owner, self-hosted** application. It is designed to run on a machine you control, on a network you trust, and it assumes the person operating the server is the person who should have access to it. It is not a multi-tenant service and it has not been audited for exposure to the public internet.

AI Web on Termux เป็นแอปแบบ **self-hosted สำหรับเจ้าของคนเดียว** ออกแบบมาให้รันบนเครื่องที่คุณควบคุมเองในเครือข่ายที่คุณเชื่อใจ และถือว่าผู้ที่ดูแลเซิร์ฟเวอร์คือผู้ที่มีสิทธิ์เข้าถึงระบบทั้งหมด ไม่ใช่ระบบ multi-tenant และยังไม่ผ่านการตรวจสอบสำหรับการเปิดสู่อินเทอร์เน็ตสาธารณะ

- English: [Security policy](#english)
- ภาษาไทย: [นโยบายความปลอดภัย](#ภาษาไทย)

---

## English

### Supported versions

This project does not publish versioned releases. Only the **latest commit on the `main` branch** is supported. Security fixes are made on `main`; older commits and forks are not maintained.

### Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub Security Advisories:

<https://github.com/Taraphong/Agents-mux/security/advisories/new>

Include, where you can:

- what the problem is and which component is affected (`app.py`, a template, `start_web.sh`, `install.sh`, a Skill, …);
- step-by-step reproduction, or a proof-of-concept request/command;
- the affected commit (`git rev-parse HEAD`) and your environment (Termux, Linux, macOS; Python version);
- the impact you believe it has, and any mitigation you already found.

Never attach real API keys, Pairing Keys, session cookies, `.env` or `.app-auth.json` contents, `certs/key.pem`, conversation history, or logs that contain them. Redact them first.

### What to expect

This is a volunteer-maintained personal project, so response is **best effort** and there is no bug bounty. You can expect an acknowledgement, a request for details if needed, and a note when the report is fixed or declined as out of scope. Please give a reasonable amount of time to fix the issue before any public disclosure.

### Scope

**In scope**

- Authentication bypass of the device-pairing gate, or reuse of a consumed/expired Pairing Key.
- Reading secrets (API keys, Discord token, private keys, session tokens, other users' history) through the web UI, an API response, the web terminal, a tool call, or the app log.
- Path traversal or escape from the project root through file tools, the terminal, Skills, scheduling, or static asset routes.
- Cross-site request forgery, cross-site scripting, or cookie handling flaws in the web interface.
- Remote code execution or command execution outside the documented tool/terminal approval flow.
- Incorrect TLS/proxy handling that causes the session cookie to leak or be sent in the clear.

**Out of scope**

- Anything that requires an already paired device, shell access as the user running the app, or filesystem access to the server (see [Known limitations](#known-limitations)).
- The operator configuring a malicious `Base URL`, model, or prompt — the server sends keys where the operator tells it to.
- Prompt-injection content produced by a model, and actions the owner approves in the UI.
- Self-signed certificate warnings, or missing hardening in a deliberately insecure configuration (`AI_WEB_AUTH=off`, plain HTTP on an untrusted network).
- Denial of service by a paired device, and cost from API usage by a paired device.
- Vulnerabilities in third-party packages that are already publicly known and fixed in a newer release.

### Security model

| Area | How it works |
| --- | --- |
| Network | The server binds `0.0.0.0:5000` by default and serves every paired device the same privileges. There are no per-user accounts or roles. |
| Device pairing | Enabled by default (`AI_WEB_AUTH=on`). Pairing keys are generated **only on the server** (`python app.py --pairing-key`, `./start_web.sh --pair`), are single-use, and expire after `AI_WEB_PAIRING_TTL_MINUTES` (default 30). This is the only way to create a session. |
| Session cookie | The key is exchanged at `POST /api/auth/pair` for a 32-byte random token in the `ai-web-session` cookie: `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` whenever the request is HTTPS. Sessions last `AI_WEB_SESSION_DAYS` (default 30) and can be revoked individually or all at once. |
| Secrets at rest | Only SHA-256 hashes of Pairing Keys and session tokens go into `.app-auth.json`. API keys and the Discord token live in `.env` and `.app-settings.json`. The settings and auth stores are written atomically with `0600` permissions; `install.sh` creates `.env` as `0600` and `start_web.sh` protects `certs/key.pem`. |
| Brute force | Pairing failures are rate-limited per client address (8 failures in 5 minutes, then HTTP 429). Key comparison uses constant-time comparison. |
| Request gate | A `before_request` hook sends unpaired browsers to `/pair` and answers unpaired `/api/*` calls with `401`. Only `/pair`, `/api/auth/pair`, `/api/auth/status`, and page CSS/JS under `/static/` and `/templates/` are public. |
| CSRF | State-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) that carry an `Origin` header are rejected with `403` unless the origin matches the request host. Requests without `Origin` (curl, scripts) are allowed by design. |
| Secret exposure in responses | `GET /api/settings` never returns stored API keys or the Discord token — only a `••••••••` placeholder plus `has_api_key` / `has_discord_token` flags. |
| Logs and terminal output | Log records drop fields named `api_key`, `authorization`, `token`, and `content`; all logged text is scrubbed of configured secrets, `?key=`-style query values, and PEM private-key blocks. The web terminal output is redacted the same way before it reaches the browser or the log. |
| Local tools | `read_file`, `list_files`, `write_file`, `run_command` (alias `execute_command`), and `create_skill` resolve paths inside the project root and refuse `PROTECTED_PARTS` / `PROTECTED_NAMES`. `write_file`, `run_command`, and Skill/schedule changes require a one-time approval token bound to the exact tool name and arguments (15-minute TTL); `run_command` parses an allowlist and never invokes a shell. Reads and writes are capped at 200 KB. |
| Web terminal | Real shell, project-root confined (best-effort path guard), 60-second timeout, 100 KB output cap, and sensitive environment variables (names containing `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`) are stripped before the process starts. |
| Uploads | Requests are capped by `MAX_CONTENT_LENGTH` (default 8 MB, `AI_WEB_MAX_CONTENT_BYTES`). |
| TLS | The app can terminate HTTPS itself with certificate files or an ad-hoc certificate, or sit behind a TLS-terminating reverse proxy. `ProxyFix` is enabled only when `AI_WEB_TRUST_PROXY=1`, and that must be set only when the proxy overwrites `X-Forwarded-Proto` / `X-Forwarded-Host` on every request. |
| Discord bot | Optional and off by default. It never exposes filesystem or command tools; only `create_schedule` / `update_schedule` are auto-approved, and only for guild members with the Discord **Administrator** permission. Any Discord user who can DM the bot or mention it in a guild can chat with the configured model and spend API credit. |

### Hardening checklist

- Keep `AI_WEB_AUTH=on`. Set it to `off` only on a fully trusted network, and remember that anyone who can reach the page then gets the terminal and API keys.
- Serve HTTPS. If you accept a self-signed certificate warning on a hostile network, traffic can be intercepted. Use a certificate from a trusted CA, or install your local CA on each device.
- Behind a reverse proxy set `AI_WEB_TRUST_PROXY=1` **only** if the proxy strips and overwrites `X-Forwarded-*` headers. Otherwise clients can spoof them.
- Run the server as an **unprivileged user**, never as root. The terminal and tools run with the server's privileges; the path checks are best-effort, not a sandbox.
- Do not expose the port to the internet. Use a VPN or a reverse proxy with authentication, and keep it on a trusted LAN/VPN.
- Keep `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, and `logs/` readable only by the service user (mode `0600` / `0700`). They are in `.gitignore` — keep it that way.
- Review **Settings → Security and device pairing** regularly, revoke devices you no longer use, and rotate provider keys if one was ever pasted into a chat, a log, or a commit.
- Treat `history/` and `logs/` as sensitive: conversations can contain personal data and text from files the agent read.
- Keep dependencies current. Dependabot proposes updates; review and merge them, then restart the server.
- Restrict the Discord bot (private guild, limited DMs) if you enable it, and remember its answers are billed to your provider key.
- Back up `.env` and `.app-auth.json` securely if you want pairing to survive a rebuild, and never copy them between machines.

### Protecting secrets when contributing

- Never commit `.env`, `.app-settings.json`, `.app-auth.json`, `certs/` (especially `key.pem`), `history/`, `logs/`, `scheduled-jobs.json`, `.venv/`, or `__pycache__/`.
- Never paste a real API key, Pairing Key, or session token into an issue, pull request, commit message, test fixture, or screenshot.
- If a secret is committed, treat it as compromised: revoke/rotate it at the provider, run `python app.py --revoke-sessions`, remove the secret from Git history, and restart the server.
- If you add a new machine-specific data file, add it to `.gitignore`, to `PROTECTED_PARTS` / `PROTECTED_NAMES` in `app.py`, and to the rsync exclude list in `AGENTS.md`.

### Known limitations

- **No encryption at rest.** `.env`, `.app-settings.json`, and `history/` are plaintext. Anyone with read access to the server's filesystem can read the API keys and every conversation.
- **The terminal and tools are not a sandbox.** They run as the service user. Run on a dedicated, unprivileged account and do not co-locate unrelated secrets on the same machine.
- **The path guards are best-effort.** A path assembled at runtime by a shell command can slip past the token scan, which is why the OS user is the real boundary.
- **The operator can redirect keys.** `Base URL` is configurable, so whoever can edit Settings can send the stored provider key to another endpoint. Paired devices are fully trusted.
- **Prompt injection is possible.** Model output is not trusted input. Tool use requires approval, but an approved command runs as-is.
- **No chat rate limit.** Pairing attempts are limited, but a paired device can send as many prompts as it likes, at your API cost.
- **The Discord bot trusts DMs.** Anyone who can message the bot gets model access (but not filesystem or command tools), unless you restrict who can reach it.
- **Self-signed TLS warns.** Browsers warn on first visit; accepting the warning on an untrusted network exposes the session cookie to interception.
- **No security audit.** This project has not been pen-tested or audited. Review the code before exposing it to anyone else.

---

## ภาษาไทย

### เวอร์ชันที่รองรับ

โปรเจกต์นี้ไม่มีการออกรีลีสแบบมีเลขเวอร์ชัน รองรับเฉพาะ **commit ล่าสุดบน branch `main`** เท่านั้น การแก้ไขด้านความปลอดภัยทำบน `main` ส่วน commit เก่าและ fork ไม่ได้รับการดูแล

### การรายงานช่องโหว่

**ห้ามเปิด issue สาธารณะ** สำหรับปัญหาความปลอดภัย ให้แจ้งแบบส่วนตัวผ่าน GitHub Security Advisories:

<https://github.com/Taraphong/Agents-mux/security/advisories/new>

แนบข้อมูลเท่าที่ทำได้:

- ปัญหาคืออะไรและกระทบส่วนใด (`app.py`, template, `start_web.sh`, `install.sh`, Skill, …)
- ขั้นตอนทำซ้ำหรือหลักฐานคำขอ/คำสั่ง (proof of concept)
- commit ที่กระทบ (`git rev-parse HEAD`) และสภาพแวดล้อม (Termux, Linux, macOS; เวอร์ชัน Python)
- ผลกระทบที่คุณคิดว่าเกิดขึ้น และวิธีบรรเทาที่คุณพบแล้ว

ห้ามแนบ API key จริง, Pairing Key, session cookie, เนื้อหา `.env` หรือ `.app-auth.json`, `certs/key.pem`, ประวัติสนทนา หรือ log ที่มีข้อมูลเหล่านี้ — ปิดข้อมูลก่อนส่งทุกครั้ง

### สิ่งที่คาดหวังได้

โปรเจกต์นี้ดูแลโดยเจ้าของคนเดียวแบบสมัครใจ จึงตอบกลับแบบ **best effort** และไม่มี bug bounty โดยปกติจะได้รับการยืนยันว่าอ่านแล้ว อาจมีการขอข้อมูลเพิ่ม และจะแจ้งเมื่อแก้ไขเสร็จหรือแจ้งว่าไม่อยู่ในขอบเขต โปรดให้เวลาที่เหมาะสมก่อนเปิดเผยต่อสาธารณะ

### ขอบเขต

**อยู่ในขอบเขต**

- การข้ามการจับคู่อุปกรณ์ (auth bypass) หรือใช้ Pairing Key ที่ใช้แล้ว/หมดอายุซ้ำ
- การอ่านข้อมูลลับ (API key, Discord token, private key, session token, ประวัติของผู้อื่น) ผ่านหน้าเว็บ, API, Terminal, tool call หรือ log ของแอป
- Path traversal หรือหลุดออกจากโฟลเดอร์โปรเจกต์ผ่านเครื่องมือไฟล์, Terminal, Skill, งานตามเวลา หรือ route ของ static asset
- CSRF, XSS หรือข้อบกพร่องในการจัดการคุกกี้ของหน้าเว็บ
- Remote code execution หรือรันคำสั่งนอกขั้นตอนอนุมัติของ tool/Terminal ที่ระบุไว้
- การจัดการ TLS/proxy ที่ผิดจนคุกกี้ session รั่วหรือถูกส่งแบบไม่เข้ารหัส

**ไม่อยู่ในขอบเขต**

- สิ่งที่ต้องมีอุปกรณ์ที่จับคู่แล้ว, shell ในนามผู้ใช้ที่รันแอป หรือสิทธิ์เข้าถึงไฟล์บนเซิร์ฟเวอร์อยู่แล้ว (ดู [ข้อจำกัดที่ทราบ](#ข้อจำกัดที่ทราบ))
- ผู้ดูแลตั้ง `Base URL`, model หรือ prompt ที่เป็นอันตรายเอง — เซิร์ฟเวอร์ส่ง key ไปยังปลายทางที่ผู้ดูแลกำหนด
- เนื้อหาจาก prompt injection ที่โมเดลสร้างขึ้น และการกระทำที่เจ้าของกดอนุมัติในหน้าเว็บ
- คำเตือนใบรับรอง self-signed หรือการตั้งค่าที่ตั้งใจไม่ปลอดภัย (`AI_WEB_AUTH=off`, HTTP บนเครือข่ายที่ไม่น่าเชื่อถือ)
- การทำ denial of service โดยอุปกรณ์ที่จับคู่แล้ว และค่าใช้จ่ายจาก API ของอุปกรณ์ที่จับคู่แล้ว
- ช่องโหว่ของแพ็กเกจบุคคลที่สามที่เปิดเผยต่อสาธารณะและแก้แล้วในรุ่นใหม่กว่า

### รูปแบบความปลอดภัย

| ส่วน | การทำงาน |
| --- | --- |
| เครือข่าย | เซิร์ฟเวอร์ผูก `0.0.0.0:5000` ตามค่าเริ่มต้น และให้สิทธิ์เท่ากันกับทุกอุปกรณ์ที่จับคู่แล้ว ไม่มีบัญชีผู้ใช้หรือบทบาทแยก |
| การจับคู่อุปกรณ์ | เปิดตามค่าเริ่มต้น (`AI_WEB_AUTH=on`) Pairing Key สร้าง **ฝั่งเซิร์ฟเวอร์เท่านั้น** (`python app.py --pairing-key`, `./start_web.sh --pair`) ใช้ได้ครั้งเดียวและหมดอายุตาม `AI_WEB_PAIRING_TTL_MINUTES` (ค่าเริ่มต้น 30 นาที) เป็นวิธีเดียวในการสร้าง session |
| คุกกี้ session | แลก key ที่ `POST /api/auth/pair` เป็น token สุ่ม 32 ไบต์ในคุกกี้ `ai-web-session` แบบ `HttpOnly`, `SameSite=Lax`, `Path=/` และ `Secure` ทุกครั้งที่เป็น HTTPS อายุ session ตาม `AI_WEB_SESSION_DAYS` (ค่าเริ่มต้น 30 วัน) ยกเลิกทีละอุปกรณ์หรือทั้งหมดได้ |
| ข้อมูลลับบนดิสก์ | เก็บเฉพาะ SHA-256 hash ของ Pairing Key และ session token ใน `.app-auth.json` ส่วน API key และ Discord token อยู่ใน `.env` และ `.app-settings.json` ไฟล์ settings และ auth store เขียนแบบ atomic ด้วยสิทธิ์ `0600` ขณะที่ `install.sh` สร้าง `.env` เป็น `0600` และ `start_web.sh` ป้องกัน `certs/key.pem` |
| การเดา key | จำกัดการลองจับคู่ที่ผิดต่อ IP (8 ครั้งใน 5 นาที แล้วตอบ 429) และเทียบ key ด้วย constant-time comparison |
| การตรวจทุกคำขอ | `before_request` พาเบราว์เซอร์ที่ยังไม่จับคู่ไป `/pair` และตอบ `/api/*` ที่ยังไม่จับคู่ด้วย `401` เฉพาะ `/pair`, `/api/auth/pair`, `/api/auth/status` และ CSS/JS ของหน้าภายใต้ `/static/` และ `/templates/` เท่านั้นที่เข้าถึงได้โดยไม่ต้องจับคู่ |
| CSRF | คำขอที่เปลี่ยนสถานะ (`POST`, `PUT`, `PATCH`, `DELETE`) และมี header `Origin` จะถูกปฏิเสธด้วย `403` ถ้า origin ไม่ตรงกับ host ของคำขอ ส่วนคำขอที่ไม่มี `Origin` (curl, สคริปต์) อนุญาตตามการออกแบบ |
| การปกปิดข้อมูลลับใน response | `GET /api/settings` ไม่คืน API key หรือ Discord token ที่เก็บไว้ จะคืนเฉพาะค่าแทน `••••••••` พร้อม flag `has_api_key` / `has_discord_token` |
| Log และผลลัพธ์ Terminal | log ตัดฟิลด์ `api_key`, `authorization`, `token`, `content` และล้างข้อความทั้งหมดจากข้อมูลลับที่ตั้งไว้, ค่าใน query แบบ `?key=` และบล็อก PEM private key ส่วนผลลัพธ์ Terminal ถูกปิดข้อมูลแบบเดียวกันก่อนถึงเบราว์เซอร์และ log |
| เครื่องมือภายใน | `read_file`, `list_files`, `write_file`, `run_command` (ชื่อเดิม `execute_command`) และ `create_skill` จำกัด path ภายในโฟลเดอร์โปรเจกต์และปฏิเสธ `PROTECTED_PARTS` / `PROTECTED_NAMES` โดย `write_file`, `run_command` และการแก้ Skill/งานตามเวลา ต้องมี approval token ใช้ครั้งเดียว ผูกกับชื่อและ arguments ตรงตัว (อายุ 15 นาที) ขณะที่ `run_command` ใช้ allowlist และไม่เรียก shell เลย การอ่าน/เขียนจำกัด 200 KB |
| Terminal หน้าเว็บ | ใช้ shell จริง จำกัดอยู่ในโฟลเดอร์โปรเจกต์ (best-effort), timeout 60 วินาที, เก็บผลลัพธ์สูงสุด 100 KB และตัดตัวแปรสภาพแวดล้อมที่ชื่อมี `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL` ก่อนเริ่ม process |
| ขนาดคำขอ | จำกัดด้วย `MAX_CONTENT_LENGTH` (ค่าเริ่มต้น 8 MB, `AI_WEB_MAX_CONTENT_BYTES`) |
| TLS | แอป terminate HTTPS เองได้ด้วยไฟล์ใบรับรองหรือใบรับรองชั่วคราว หรืออยู่หลัง reverse proxy ที่ terminate TLS โดยเปิด `ProxyFix` เฉพาะเมื่อ `AI_WEB_TRUST_PROXY=1` และต้องตั้งค่านี้เฉพาะเมื่อ proxy เขียนทับ `X-Forwarded-Proto` / `X-Forwarded-Host` ทุกคำขอ |
| Discord bot | เป็นตัวเลือกและปิดตามค่าเริ่มต้น ไม่เปิดเครื่องมือไฟล์หรือคำสั่งใด ๆ มีเพียง `create_schedule` / `update_schedule` ที่อนุมัติอัตโนมัติ และเฉพาะสมาชิก guild ที่มีสิทธิ์ **Administrator** ใน Discord เท่านั้น ผู้ใช้ Discord ที่ DM bot หรือ mention bot ได้จะคุยกับโมเดลที่ตั้งไว้และใช้เครดิต API ได้ |

### รายการตรวจความปลอดภัย

- คง `AI_WEB_AUTH=on` ไว้ ตั้ง `off` เฉพาะเครือข่ายที่เชื่อถือได้เต็มที่ และจำไว้ว่าผู้ที่เข้าถึงหน้าเว็บได้จะได้ Terminal และ API key ไปด้วย
- ให้บริการผ่าน HTTPS ถ้ายอมรับคำเตือนใบรับรอง self-signed บนเครือข่ายที่ไม่น่าเชื่อถือ การรับส่งอาจถูกดักได้ ใช้ใบรับรองจาก CA ที่เชื่อถือได้หรือติดตั้ง CA ท้องถิ่นในทุกอุปกรณ์
- ถ้าอยู่หลัง reverse proxy ให้ตั้ง `AI_WEB_TRUST_PROXY=1` **เฉพาะ** เมื่อ proxy ลบและเขียนทับ header `X-Forwarded-*` เอง ไม่เช่นนั้น client จะปลอม header ได้
- รันเซิร์ฟเวอร์ด้วย **ผู้ใช้ที่ไม่มีสิทธิ์พิเศษ** ห้ามรันเป็น root เพราะ Terminal และเครื่องมือทำงานด้วยสิทธิ์ของเซิร์ฟเวอร์ และการตรวจ path เป็น best-effort ไม่ใช่ sandbox
- ห้ามเปิดพอร์ตสู่อินเทอร์เน็ต ใช้ VPN หรือ reverse proxy ที่มีการยืนยันตัวตน และจำกัดให้อยู่ใน LAN/VPN ที่เชื่อถือได้
- จำกัดสิทธิ์ `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/` และ `logs/` ให้อ่านได้เฉพาะผู้ใช้บริการ (โหมด `0600` / `0700`) ไฟล์เหล่านี้อยู่ใน `.gitignore` แล้ว — อย่าเอาออก
- ตรวจ **Settings → ความปลอดภัยและการจับคู่อุปกรณ์** เป็นประจำ ยกเลิกอุปกรณ์ที่ไม่ใช้แล้ว และเปลี่ยน provider key ถ้าเคยถูกวางในแชต, log หรือ commit
- ถือว่า `history/` และ `logs/` เป็นข้อมูลอ่อนไหว เพราะบทสนทนาอาจมีข้อมูลส่วนบุคคลและข้อความจากไฟล์ที่ agent อ่าน
- อัปเดต dependency สม่ำเสมอ Dependabot จะเสนอ PR มา ให้ตรวจและ merge แล้ว restart เซิร์ฟเวอร์
- จำกัด Discord bot (guild ส่วนตัว, จำกัด DM) ถ้าเปิดใช้ และจำว่าคำตอบถูกคิดเงินกับ provider key ของคุณ
- สำรอง `.env` และ `.app-auth.json` อย่างปลอดภัยถ้าต้องการให้การจับคู่คงอยู่หลังติดตั้งใหม่ และห้ามคัดลอกข้ามเครื่อง

### การปกป้องข้อมูลลับเมื่อร่วมพัฒนา

- ห้าม commit `.env`, `.app-settings.json`, `.app-auth.json`, `certs/` (โดยเฉพาะ `key.pem`), `history/`, `logs/`, `scheduled-jobs.json`, `.venv/` และ `__pycache__/`
- ห้ามวาง API key, Pairing Key หรือ session token จริงลงใน issue, pull request, commit message, ไฟล์ทดสอบ หรือภาพหน้าจอ
- ถ้าข้อมูลลับถูก commit ให้ถือว่าถูกเปิดเผยแล้ว: เพิกถอน/เปลี่ยน key ที่ผู้ให้บริการ, รัน `python app.py --revoke-sessions`, ลบข้อมูลลับออกจากประวัติ Git และ restart เซิร์ฟเวอร์
- ถ้าเพิ่มไฟล์ข้อมูลเฉพาะเครื่องใหม่ ต้องเพิ่มใน `.gitignore`, ใน `PROTECTED_PARTS` / `PROTECTED_NAMES` ของ `app.py` และในรายการ exclude ของ rsync ใน `AGENTS.md`

### ข้อจำกัดที่ทราบ

- **ไม่มี encryption at rest** `.env`, `.app-settings.json` และ `history/` เป็นข้อความธรรมดา ใครก็ตามที่อ่านไฟล์บนเซิร์ฟเวอร์ได้จะเห็น API key และบทสนทนาทั้งหมด
- **Terminal และเครื่องมือไม่ใช่ sandbox** ทำงานด้วยสิทธิ์ของผู้ใช้บริการ ให้รันด้วยบัญชีเฉพาะที่ไม่มีสิทธิ์พิเศษ และไม่ควรวางข้อมูลลับอื่นไว้บนเครื่องเดียวกัน
- **การตรวจ path เป็น best-effort** path ที่ประกอบขึ้นขณะรันใน shell อาจหลุดการตรวจ token ได้ สิทธิ์ของ OS user จึงเป็นขอบเขตจริง
- **ผู้ดูแลเปลี่ยนปลายทางของ key ได้** `Base URL` ตั้งค่าได้ ใครก็ตามที่แก้ Settings ได้สามารถส่ง provider key ที่เก็บไว้ไปยังปลายทางอื่น อุปกรณ์ที่จับคู่แล้วถือว่าเชื่อถือได้ทั้งหมด
- **Prompt injection เกิดขึ้นได้** ข้อความจากโมเดลไม่ใช่ข้อมูลที่เชื่อถือได้ แม้การใช้ tool ต้องอนุมัติ แต่คำสั่งที่อนุมัติแล้วจะรันตามจริง
- **ไม่มี rate limit ของแชต** จำกัดเฉพาะการลองจับคู่ แต่อุปกรณ์ที่จับคู่แล้วส่ง prompt ได้ไม่จำกัดตามค่าใช้จ่าย API ของคุณ
- **Discord bot เชื่อถือ DM** ใครก็ตามที่ส่งข้อความหา bot ได้จะใช้งานโมเดลได้ (แต่ไม่ได้เครื่องมือไฟล์หรือคำสั่ง) เว้นแต่จำกัดผู้ที่เข้าถึง
- **TLS self-signed มีคำเตือน** เบราว์เซอร์จะเตือนครั้งแรก และการยอมรับคำเตือนบนเครือข่ายที่ไม่น่าเชื่อถือทำให้คุกกี้ session เสี่ยงถูกดัก
- **ยังไม่มีการตรวจสอบความปลอดภัยจากภายนอก** โปรเจกต์นี้ยังไม่ผ่านการ pen-test หรือ audit ควรอ่านโค้ดก่อนเปิดให้ผู้อื่นเข้าถึง
