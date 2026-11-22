# คู่มือติดตั้ง AI Web

คู่มือนี้สำหรับผู้ที่ต้องการรันโปรเจกต์บนเครื่องของตัวเอง: Termux บน Android, Linux หรือ macOS ทุกคำสั่งคัดลอกไปวางใน terminal ได้เลย

> หน้าเว็บต้องจับคู่อุปกรณ์ก่อนใช้งาน (Pairing Key) ใช้เฉพาะในเครือข่ายที่เชื่อถือได้ และอย่าเปิดให้เข้าถึงจากอินเทอร์เน็ตโดยตรง

---

## สิ่งที่ต้องมี

- Python **3.10 ขึ้นไป** (บน Termux: `pkg install python`)
- `git` (หรือดาวน์โหลดโปรเจกต์เป็น ZIP)
- API key อย่างน้อยหนึ่งราย: OpenAI / OpenRouter / Groq / Gemini / Anthropic / Hugging Face
- `openssl` เฉพาะเมื่อต้องการให้เซิร์ฟเวอร์ทำ HTTPS เอง (บน Termux: `pkg install openssl-tool`)
- รองรับ Termux, Linux และ macOS เท่านั้น เพราะโค้ดใช้ `fcntl` จึงยังไม่รองรับ Windows

---

## ติดตั้งแบบเร็วด้วยสคริปต์

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

`install.sh` ทำสิ่งต่อไปนี้:

1. ตรวจว่ามี Python เวอร์ชันที่รองรับ (หรือใช้ `.venv` เดิมที่ยังใช้งานได้)
2. สร้าง virtual environment ใน `.venv`
3. ติดตั้ง dependencies จาก `requirements.txt`
4. สร้าง `.env` จาก `.env.example` ด้วยสิทธิ์ `0600` และไม่เขียนทับไฟล์ที่มีอยู่
5. สร้างโฟลเดอร์ `logs/` และ `history/`
6. บน Termux จะสร้างลิงก์คำสั่งสั้น `startweb` ไว้ใน `$PREFIX/bin` ด้วย

หลังติดตั้ง ให้ใส่ API key ใน `.env` แล้วเริ่มเซิร์ฟเวอร์ (ดูหัวข้อถัดไป)

> ถ้า repository เป็นแบบ private ให้ clone ผ่าน SSH (`git clone git@github.com:Taraphong/Agents-mux.git`) หรือดาวน์โหลด ZIP มาแตก แล้วรัน `bash install.sh` ในโฟลเดอร์นั้น

---

## ติดตั้งบน Termux (Android)

```bash
pkg update && pkg upgrade -y
pkg install -y python git
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

ตั้ง API key:

```bash
nano .env
```

แก้ผู้ให้บริการและ key เช่น:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx
```

บันทึกด้วย `Ctrl+O` → `Enter` → `Ctrl+X`

เริ่มเซิร์ฟเวอร์:

```bash
./start_web.sh --start      # หรือ: startweb --start
```

เปิด `http://127.0.0.1:5000` ในเบราว์เซอร์ หรือ `http://<ip-ของเครื่อง>:5000` จากมือถือหรือคอมพิวเตอร์ที่อยู่ใน Wi-Fi เดียวกัน

การเริ่มครั้งแรกที่ยังไม่มีอุปกรณ์จับคู่จะแสดง Pairing Key (และเขียนลง `logs/ai-web.log` ด้วย) เปิด `http://<ip-ของเครื่อง>:5000/pair` ใส่คีย์นั้น อุปกรณ์จะลงชื่อเข้าใช้ทันที

ดู IP ของเครื่อง:

```bash
ifconfig 2>/dev/null | grep -A1 wlan0
# หรือ
ip -4 addr show
```

> รัน `termux-wake-lock` เพื่อไม่ให้ Android พักเซิร์ฟเวอร์ และบน Android 12+ ให้ปิดการจำกัดแบตเตอรี่ของ Termux

---

## ติดตั้งบน Linux

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

จากนั้นแก้ `.env`, เริ่มเซิร์ฟเวอร์ และเปิด `http://127.0.0.1:5000` ตามขั้นตอนของ Termux บน Linux ให้เริ่มด้วย `./start_web.sh --start` เพราะคำสั่งสั้น `startweb` ติดตั้งเฉพาะบน Termux

---

## ติดตั้งบน macOS

ถ้ายังไม่มี Command Line Tools ให้รัน:

```bash
xcode-select --install
```

ทำตามตัวติดตั้งให้เสร็จก่อนรัน `git clone`

ติดตั้ง Python **3.10 ขึ้นไป** ด้วยตัวติดตั้งของ macOS จาก [python.org](https://www.python.org/downloads/macos/) แล้วเปิด terminal ใหม่ (ดู [คู่มือ Python บน macOS](https://docs.python.org/3/using/mac.html)) ตรวจว่า `python3` บน `PATH` เป็นเวอร์ชันที่รองรับก่อนรัน `install.sh`:

```bash
command -v python3
python3 --version
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'
```

ถ้าไม่มี `python3` หรือเวอร์ชันเก่ากว่า 3.10 ให้ปรับ `PATH` ให้ชี้ไปยัง Python ที่เพิ่งติดตั้ง แล้วตรวจซ้ำจนผ่าน จากนั้นรัน:

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

---

## ตั้งค่า `.env`

ค่าที่ควรรู้:

| ตัวแปร | ความหมาย |
| --- | --- |
| `AI_PROVIDER` | ผู้ให้บริการหลัก: `openai`, `gemini`, `anthropic`, `hf`, `or`, `groq` |
| `OPENAI_API_KEY` | API key ของ OpenAI หรือ API ที่เข้ากันได้ |
| `GEMINI_API_KEY` | API key ของ Google Gemini |
| `ANTHROPIC_API_KEY` | API key ของ Anthropic (Claude) |
| `OPENROUTER_API_KEY` | API key ของ OpenRouter |
| `GROQ_API_KEY` | API key ของ Groq |
| `HF_API_KEY` | API key ของ Hugging Face |
| `AI_BASE_URL` | Base URL ที่กำหนดเองสำหรับผู้ให้บริการที่ใช้อยู่ (เว้นว่างได้) |
| `AI_FALLBACK_PROVIDER`, `AI_FALLBACK_MODEL` | ค่า fallback provider/model เริ่มต้น |
| `DISCORD_BOT_TOKEN`, `DISCORD_BOT_PREFIX` | token ของ Discord bot และ prefix ของข้อความ |
| `DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_CHANNEL_IDS` | allowlist ของ Discord (ID คั่นด้วยจุลภาค) |
| `AI_WEB_AUTH` | `on` เป็นค่าเริ่มต้น; `off` เพื่อปิดการจับคู่อุปกรณ์ |
| `AI_WEB_PAIRING_TTL_MINUTES`, `AI_WEB_SESSION_DAYS` | อายุ Pairing Key (30 นาที) และอายุ session (30 วัน) |
| `AI_WEB_TRUST_PROXY` | `1` เมื่อมี reverse proxy ที่ terminate TLS |
| `AI_WEB_TLS_CERT`, `AI_WEB_TLS_KEY`, `AI_WEB_TLS_ADHOC` | โหมด HTTPS |
| `AI_WEB_ENABLE_SCHEDULER` | `1` เพื่อเปิดงานตามเวลาเมื่อรันใต้ WSGI |
| `PORT` | พอร์ตที่รับฟัง (ค่าเริ่มต้น `5000`) |

ไฟล์ตัวอย่างยังมีตัวแปรเรื่องที่เก็บข้อมูลและขีดจำกัดด้วย (`AI_WEB_LOG_FILE`, `AI_WEB_SETTINGS_FILE`, `AI_WEB_HISTORY_DIR`, `AI_WEB_SKILLS_DIR`, `AI_WEB_MAX_CONTENT_BYTES`, `AI_WEB_LOG_MAX_ENTRIES`, …)

### ใช้งาน Anthropic (Claude)

Anthropic ต้องตั้งทั้ง key และ model ให้ตรงกัน

```dotenv
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
```

แล้วเปิด **Settings** ในหน้าเว็บ เลือก **Anthropic** และเลือก model ของ Claude จากรายการ (รายการจะถูกดึงจาก API เมื่อมี key แล้ว)

> model ตอนเริ่มระบบมาจาก `OPENAI_MODEL` ซึ่งเป็น model ของ OpenAI ถ้าไม่เลือก model ของ Claude ใน Settings การเรียก API จะล้มเหลว

### ลำดับความสำคัญ: `.env` กับ Settings

- `.env` ถูกอ่านตอนเริ่มโปรเซส และเป็นเพียง **ค่าเริ่มต้น**
- ทุกครั้งที่บันทึกใน **Settings** ค่าจะถูกเขียนลง `.app-settings.json`
- เมื่อมี `.app-settings.json` แล้ว ค่าที่บันทึกไว้จะ **ทับ `.env`** รวมถึง provider, model และ API key
- ถ้าแก้ `.env` แล้วไม่เห็นผล ให้แก้ใน Settings แทน หรือกด **Reset** ที่ด้านล่างของ Settings (ลบ `.app-settings.json`) แล้วรีสตาร์ตเซิร์ฟเวอร์
- API key ที่บันทึกผ่าน Settings จะถูกใช้ก่อน key ใน `.env` เสมอ

ค่าอื่น ๆ — system prompt, temperature, model, ระดับการคิด, Discord bot, allowlist, สิทธิ์เข้าถึงเครื่อง — ตั้งใน **Settings** และเก็บเฉพาะใน `.app-settings.json` บนเครื่องของคุณ

> `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/` และ `scheduled-jobs.json` ไม่ถูก commit เข้า Git ห้ามส่งไฟล์เหล่านี้ให้ใคร เพราะมี API key, สถานะการจับคู่ และประวัติการสนทนา

---

## เริ่ม / หยุด / ตรวจสอบเซิร์ฟเวอร์

```bash
./start_web.sh --start     # เริ่ม (ถ้ายังไม่ทำงาน)
./start_web.sh --check     # แสดงสถานะและที่อยู่ http:// หรือ https:// จริง
./start_web.sh --restart   # หยุดแล้วเริ่มใหม่ (ใช้หลังแก้ app.py หรือ HTML)
./start_web.sh --stop      # หยุด
./start_web.sh --pair      # สร้าง Pairing Key ใช้ครั้งเดียว
./start_web.sh --make-cert [ip]   # สร้างใบรับรอง HTTPS แบบ self-signed
```

บน Termux หลังรัน `install.sh` จะใช้คำสั่งสั้นได้ด้วย:

```bash
startweb --start
startweb --restart
startweb --check
startweb --stop
```

ไฟล์ `.css` และ `.js` ถูกอ่านจากดิสก์ทุก request ดังนั้นแก้แล้วเพียงรีเฟรชเบราว์เซอร์ แต่ถ้าแก้ `app.py` หรือไฟล์ `.html` ใน `templates/` ต้อง `--restart`

log ของเซิร์ฟเวอร์อยู่ที่ `logs/ai-web.log` ในโฟลเดอร์โปรเจกต์ (`logs/` ไม่ถูก commit)

ถ้าต้องการดู log สดใน terminal แทน (เซิร์ฟเวอร์จะหยุดเมื่อปิด terminal):

```bash
source .venv/bin/activate
python app.py
```

---

## เข้าถึงจากอุปกรณ์อื่นในเครือข่าย

เซิร์ฟเวอร์รับฟังบน `0.0.0.0` พอร์ต `5000` เป็นค่าเริ่มต้น

1. หา IP ของเครื่องที่รันเซิร์ฟเวอร์ (เช่น `192.168.0.50`)
2. เปิดเบราว์เซอร์บนอุปกรณ์อื่นในเครือข่ายเดียวกัน: `http://192.168.0.50:5000`
3. ถ้าเปิดไม่ได้ ให้ตรวจว่า firewall ของเครื่องอนุญาตพอร์ต 5000

เปลี่ยนพอร์ตได้ด้วย `PORT` ใน `.env` หรือสำหรับการรันครั้งเดียว:

```bash
PORT=8080 ./start_web.sh --restart
```

ต้องใช้ `--restart` (หรือ `--stop` แล้ว `--start`) เพราะ `--start` จะไม่ทำอะไรเมื่อเซิร์ฟเวอร์ทำงานอยู่ และพอร์ตใหม่จะมีผลหลังโปรเซสเดิมหยุดและตัวใหม่เริ่มแล้วเท่านั้น

---

## ลงชื่อเข้าใช้ครั้งแรก (การจับคู่อุปกรณ์)

1. สร้าง Pairing Key บนเซิร์ฟเวอร์: `./start_web.sh --pair` การเริ่มครั้งแรกที่ยังไม่มีอุปกรณ์จับคู่ก็จะแสดงให้เช่นกัน
2. ที่ฝั่ง client เปิด `http://<ip-ของเครื่อง>:5000/pair` แล้วใส่คีย์
3. อุปกรณ์จะได้คุกกี้ session แบบ `HttpOnly` อายุ `AI_WEB_SESSION_DAYS` (ค่าเริ่มต้น 30 วัน)
4. จัดการหรือยกเลิกอุปกรณ์ได้ที่ **Settings → ความปลอดภัย** และใช้ `python app.py --revoke-sessions` เพื่อออกจากระบบทุกอุปกรณ์

คีย์ใช้ได้ครั้งเดียวและหมดอายุใน `AI_WEB_PAIRING_TTL_MINUTES` (ค่าเริ่มต้น 30 นาที) `AI_WEB_AUTH=off` ปิดการจับคู่ และใช้เฉพาะในเครือข่ายที่เชื่อถือได้ทั้งหมด

---

## HTTPS

เซิร์ฟเวอร์ทำ HTTPS เองได้ โดยต้องมี `openssl` เพิ่มอย่างเดียว (`pkg install openssl-tool` บน Termux)

วิธีง่ายที่สุดคือจากหน้าเว็บ: **Settings → เว็บและ HTTPS** เลือกโหมด บันทึก แล้วรีสตาร์ต หน้าเว็บไม่สามารถตามการรีสตาร์ตที่เปลี่ยนโปรโตคอลได้ จึงจะแสดงที่อยู่ใหม่ให้เปิด

จาก shell ให้สร้างใบรับรอง self-signed และเปิดใช้งาน:

```bash
./start_web.sh --make-cert 192.168.0.50   # สร้าง certs/cert.pem และ certs/key.pem
# ตั้ง AI_WEB_TLS_CERT=/path/to/certs/cert.pem และ AI_WEB_TLS_KEY=/path/to/certs/key.pem ใน .env
./start_web.sh --restart
./start_web.sh --check                    # แสดงที่อยู่ http:// หรือ https:// จริง
```

- เมื่อมี `AI_WEB_TLS_CERT` + `AI_WEB_TLS_KEY` เซิร์ฟเวอร์จะใช้ไฟล์เหล่านั้น โหมด "HTTPS ด้วยไฟล์ใบรับรอง" ในหน้าเว็บจะใช้ `certs/cert.pem` + `certs/key.pem` ก่อน และถ้าไม่มีจะใช้คู่ไฟล์ที่ตั้งไว้ใน `.env`
- เมื่อตั้ง `AI_WEB_TLS_ADHOC=1` เซิร์ฟเวอร์จะสร้างใบรับรอง self-signed ด้วย `openssl` ในการเริ่มครั้งแรก (SAN: `localhost`, `127.0.0.1`, ชื่อเครื่อง, IP ใน LAN) แล้วใช้ `certs/adhoc-cert.pem` / `certs/adhoc-key.pem` ต่อในครั้งถัดไป ไม่ต้องใช้แพ็กเกจ `cryptography` ของ Python
- ใบรับรอง self-signed ทำให้เบราว์เซอร์เตือนครั้งเดียว ยอมรับก็ใช้ได้ ถ้าไม่ต้องการคำเตือนให้ใช้ใบรับรองจาก CA ที่เชื่อถือได้ ติดตั้ง CA ของคุณในอุปกรณ์ หรือวาง reverse proxy (Caddy, nginx, `tailscale serve`) ไว้ข้างหน้าและตั้ง `AI_WEB_TRUST_PROXY=1`
- `tailscale cert` ใช้ได้เฉพาะบนเครื่องที่เป็นเจ้าของชื่อนั้น แอป Tailscale บน Android ไม่มี CLI เครื่อง Termux จึงออกใบรับรอง Tailscale ของตัวเองไม่ได้ ให้รัน `tailscale serve` บนเครื่องอื่นแทน
- การสลับ HTTPS → HTTP ไม่รักษาการลงชื่อเข้าใช้เดิม เบราว์เซอร์จะไม่ส่งคุกกี้ `Secure` ผ่าน HTTP จึงต้องจับคู่อุปกรณ์ใหม่บน HTTP (หน้าเว็บใช้ชื่อคุกกี้แยกกันด้วยเหตุนี้)

---

## อัปเดตโปรเจกต์

รันตัวอัปเดตบนเครื่องที่ให้บริการแอป:

```bash
cd ~/ai-web
./update.sh
```

`update.sh` ดาวน์โหลดไฟล์แอปล่าสุดจาก GitHub (branch `main` เป็นค่าเริ่มต้น) ติดตั้ง dependencies เฉพาะเมื่อ `requirements.txt` เปลี่ยน รีสตาร์ตเซิร์ฟเวอร์ และตรวจว่าเซิร์ฟเวอร์ตอบกลับ ไม่แตะ `.env`, `.app-settings.json`, `.app-auth.json`, `certs/`, `history/`, `logs/`, `scheduled-jobs.json` หรือ `.venv`

ตัวเลือก:

```bash
./update.sh --branch dev     # ใช้ branch อื่น
./update.sh --repo owner/repo
./update.sh --dry-run        # แสดงสิ่งที่จะเปลี่ยน โดยไม่เขียนไฟล์
./update.sh --no-restart     # คัดลอกไฟล์เท่านั้น ไม่รีสตาร์ตหรือตรวจสถานะ
./update.sh --help
```

สั่งอัปเดตจาก **Settings → อัปเดต** ได้เช่นกัน ซึ่งมีการตรวจแบบ dry run และแสดง log ของการอัปเดต

ถ้า repository บน GitHub เป็นแบบ private ให้มอบ token แบบอ่านอย่างเดียวให้ตัวอัปเดต:

```bash
# ขอ token โดยไม่แสดงบนหน้าจอ แล้ว export เฉพาะ shell นี้
read -rsp "GitHub token: " AI_WEB_UPDATE_TOKEN; echo
export AI_WEB_UPDATE_TOKEN
./update.sh
# หรือ export GITHUB_TOKEN แทน (ถามแบบเดียวกัน)
```

token ถูกใช้เฉพาะการดาวน์โหลด และไม่ถูกเขียนลงดิสก์

ถ้าใช้ Git checkout ก็อัปเดตเองได้:

```bash
cd ~/ai-web
git pull
bash install.sh            # ติดตั้ง dependencies ใหม่ถ้าเปลี่ยน
./start_web.sh --restart
```

ข้อมูลเดิม (`.env`, `.app-settings.json`, `.app-auth.json`, `history/`, `certs/`) จะไม่ถูกเขียนทับ

---

## ปัญหาที่พบบ่อย

**`command not found: python3`**
ติดตั้ง Python ก่อน: `pkg install python` (Termux) หรือ `sudo apt install python3 python3-venv` (Debian/Ubuntu)

**`ensurepip is not available` / สร้าง `.venv` ไม่ได้**
Debian/Ubuntu: รัน `sudo apt install python3-venv` แล้ว `bash install.sh` อีกครั้ง

**ติดตั้ง dependencies ไม่สำเร็จ**
ตรวจการเชื่อมต่อแล้วลองใหม่ หรืออัปเกรด pip ก่อน:
`./.venv/bin/python -m pip install --upgrade pip`

**หน้าเว็บพาไป `/pair` แต่ไม่มีคีย์**
สร้างคีย์บนเซิร์ฟเวอร์ด้วย `./start_web.sh --pair` แล้วอ่านจาก terminal หรือ `logs/ai-web.log`

**เปิดเว็บจากอุปกรณ์อื่นไม่ได้**
ตรวจว่าใช้ IP ในเครือข่ายเดียวกัน เซิร์ฟเวอร์ทำงานอยู่ (`./start_web.sh --check`) และ firewall อนุญาตพอร์ต 5000

**แก้โค้ดแล้วหน้าเว็บไม่เปลี่ยน**
Flask รันด้วย `debug=False` ให้รีสตาร์ตด้วย `./start_web.sh --restart` (`.css`/`.js` แค่รีเฟรช)

**API ตอบ 401 / 403 / 502**
`401` หมายถึงอุปกรณ์ยังไม่จับคู่ `403` มักมาจากคำขอที่มาจาก origin อื่น `502`/`503` มาจากผู้ให้บริการ: ตรวจว่า API key ถูกต้อง `AI_PROVIDER` ตรงกับ key และ model ที่เลือกมีอยู่จริงสำหรับผู้ให้บริการนั้น (นี่คืออาการปกติของ Anthropic)

**งานตามเวลาไม่รัน**
Scheduler ทำงานเฉพาะขณะเซิร์ฟเวอร์ทำงาน ถ้ารันใต้ WSGI ภายนอกให้ตั้ง `AI_WEB_ENABLE_SCHEDULER=1`

---

## ถอนการติดตั้ง

```bash
./start_web.sh --stop
cd ~
rm -rf ~/ai-web          # ลบทั้งโปรเจกต์ รวมประวัติและ API key
rm -f "$PREFIX/bin/startweb"   # เฉพาะ Termux: ลบคำสั่งสั้น
```

> `rm -rf` ลบ `.env` และ `history/` ด้วย ถ้าต้องการเก็บบทสนทนา ให้สำรองโฟลเดอร์ `history/` ก่อน
