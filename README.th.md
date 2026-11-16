# AI Web บน Termux

แชต AI แบบ self-hosted รันบน Termux เปิดผ่านเบราว์เซอร์ในเครือข่ายเดียวกัน รองรับ OpenAI, Gemini และ Anthropic

นโยบายความปลอดภัย: **[SECURITY.th.md](SECURITY.th.md)**

## เริ่มใช้งาน

คู่มือติดตั้งแบบละเอียดสำหรับ Termux / Linux / macOS: **[INSTALL.md](INSTALL.md)**

ติดตั้งแบบเร็ว:

<!-- coderabbit-ai-generated:v1 -->

<!-- coderabbit-ai-generated-section:v1:5638803a0b40e97e978d46bdea226d006ea376f2626c2155027c37bb0c3b092f -->

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

แก้ `.env` เพื่อกำหนด `AI_PROVIDER` และ API key ของผู้ให้บริการที่เลือก แล้วเริ่มเซิร์ฟเวอร์:

```bash
./start_web.sh --start
```

<!-- /coderabbit-ai-generated:v1 -->

หรือติดตั้งเองทีละขั้น:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

เปิดเว็บที่ `http://127.0.0.1:5000`

### การตั้งค่า

- กำหนด `AI_PROVIDER` ใน `.env` (`openai`, `gemini`, `anthropic`, `hf`, `or`, `groq`)
- ใส่ API key ให้ตรงกับผู้ให้บริการ: `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `HF_API_KEY`, `OPENROUTER_API_KEY` หรือ `GROQ_API_KEY`
- **Anthropic:** ตั้ง `AI_PROVIDER=anthropic` และ `ANTHROPIC_API_KEY` แล้วเปิดหน้า **Settings** เลือกโมเดล Claude — ค่าเริ่มต้นของ model มาจาก `OPENAI_MODEL` จึงใช้กับ Anthropic ไม่ได้
- ค่าที่บันทึกจากหน้า **Settings** จะถูกเก็บใน `.app-settings.json` และทับค่าใน `.env` (รวม provider, model และ API key) ถ้าแก้ `.env` แล้วไม่เห็นผล ให้แก้ใน Settings แทน
- เลือกตั้งค่าเพิ่มเติมได้ที่เมนู **Settings** ในเว็บ
- ระดับการคิด: `off`, `low`, `medium`, `high`

### การจับคู่อุปกรณ์ (web auth)

หน้าเว็บต้องจับคู่อุปกรณ์ก่อนใช้งาน และ Pairing Key ถูกสร้างจากฝั่ง server เท่านั้น (เบราว์เซอร์สร้างเองไม่ได้)

- สร้างคีย์บนเครื่อง server ด้วย `python app.py --pairing-key` (หรือ `./start_web.sh --pair`) เมื่อเริ่มเซิร์ฟเวอร์ครั้งแรกโดยยังไม่มีอุปกรณ์ที่จับคู่ ระบบจะสร้างคีย์ให้ทันที
- ที่ฝั่ง client เปิด `http://<termux-ip>:5000/pair` แล้วใส่คีย์ ระบบจะออกคุกกี้ session แบบ `HttpOnly` อายุ `AI_WEB_SESSION_DAYS` วัน (ค่าเริ่มต้น 30)
- คีย์ใช้ได้ครั้งเดียวและหมดอายุใน `AI_WEB_PAIRING_TTL_MINUTES` นาที (ค่าเริ่มต้น 30) ระบบเก็บเฉพาะ hash (SHA-256) ของคีย์และ token ใน `.app-auth.json` ซึ่งไม่ถูก commit
- ดูรายการอุปกรณ์ ยกเลิกอุปกรณ์ หรือสร้างคีย์สำหรับอุปกรณ์ใหม่ได้ที่ **Settings → ความปลอดภัยและการจับคู่อุปกรณ์** และใช้ `python app.py --revoke-sessions` เพื่อยกเลิกทุกอุปกรณ์
- `AI_WEB_AUTH=off` ปิดระบบจับคู่ ใช้เฉพาะในเครือข่ายที่เชื่อถือได้ทั้งหมด หน้าเว็บที่ยังไม่จับคู่จะถูกพาไปที่ `/pair` ส่วน `/api/auth/status` ยังเข้าถึงได้เพื่อใช้ตรวจสถานะ
- เมื่อมี reverse proxy ที่ terminate TLS ให้ตั้ง `AI_WEB_TRUST_PROXY=1` เพื่อให้เชื่อถือ `X-Forwarded-Proto` และคุกกี้ session ถูกตั้งเป็น `Secure` (ถ้าใช้ HTTP ในเครื่องให้เว้นว่างไว้)

### HTTPS

แอปเปิด HTTPS ได้เองโดยไม่ต้องติดตั้งแพ็กเกจ Python เพิ่ม เมื่อมีไฟล์ใบรับรองอยู่แล้ว

- สร้างใบรับรอง self-signed สำหรับ IP ใน LAN ของเครื่อง server: `./start_web.sh --make-cert 192.168.2.40` (ต้องมี `openssl` — บน Termux ติดตั้งด้วย `pkg install openssl-tool`) ไฟล์จะถูกสร้างที่ `certs/cert.pem` และ `certs/key.pem` ซึ่งไม่ถูก commit
- ตั้ง `AI_WEB_TLS_CERT` และ `AI_WEB_TLS_KEY` ใน `.env` แล้วรัน `./start_web.sh --restart` เปิด `https://<termux-ip>:5000` คุกกี้ session จะถูกตั้งเป็น `Secure` อัตโนมัติ
- ใบรับรอง self-signed จะทำให้เบราว์เซอร์เตือนครั้งแรก ถ้าไม่ต้องการคำเตือนให้ใช้ใบรับรองจาก CA ที่เชื่อถือได้ หรือติดตั้ง CA ของคุณลงในอุปกรณ์แต่ละเครื่อง
- ถ้าใช้ reverse proxy ที่ terminate TLS (Caddy, nginx, `tailscale serve`) ให้เว้น `AI_WEB_TLS_*` ว่างและตั้ง `AI_WEB_TRUST_PROXY=1` โดย proxy ต้องเขียนทับ `X-Forwarded-Proto` ทุก request
- `AI_WEB_TLS_ADHOC=1` สร้างใบรับรองชั่วคราวตอนสตาร์ต ต้องมีแพ็กเกจ `cryptography` (`pkg install python-cryptography` บน Termux หรือ `pip install cryptography`)

### ประวัติการสนทนา

บันทึกแยกตามวัน/เวลาใน `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json`

- โฟลเดอร์ `history/` ไม่ถูก commit เข้า Git
- สามารถเปลี่ยนชื่อ ปักหมุด ล็อก/ปลดล็อก ได้จากแชต

สำหรับข้อกำหนดและรูปแบบการทำงานที่ละเอียด กรุณาอ่าน **[AGENTS.md](AGENTS.md)**

## เครื่องมือ AI

- Agent เข้าถึงเครื่องได้ทั้งเครื่อง: path เป็น absolute (`/etc/hostname`), ขึ้นต้นด้วย `~` หรืออ้างอิงจากโฟลเดอร์โปรเจกต์ก็ได้
- **ทุกครั้ง** ที่เรียกเครื่องมือจะขออนุมัติในแชตก่อน — รวม `list_files` และ `read_file` โดยแต่ละครั้งใช้ได้ครั้งเดียว ผูกกับชื่อเครื่องมือและ arguments ตรงตัว และหมดอายุใน 15 นาที
- `run_command` รันผ่าน shell จริงด้วยสิทธิ์ของผู้ใช้ที่รันแอป: ใช้ pipe, redirection และ `sudo` ได้ถ้าผู้ใช้มีสิทธิ์โดยไม่ต้องถามรหัสผ่าน คำสั่งมีเวลาจำกัด 60 วินาที ผลลัพธ์สูงสุด 100 KB
- API key, token และ PEM private key ที่ระบบรู้จักจะถูกปิดบังในผลลัพธ์ของเครื่องมือ
- ปิด **Settings → สิทธิ์เข้าถึงเครื่อง** เพื่อกลับไปใช้ path ในโปรเจกต์เท่านั้นและ allowlist `pwd` / `ls` / `git status|diff|log`

> ⚠️ คำสั่งที่อนุมัติแล้วจะรันตามจริงด้วยสิทธิ์ของผู้ใช้ที่รันแอป และเป็นสิทธิ์ root ถ้าแอปรันเป็น root หรือผู้ใช้มี `sudo` แบบไม่ต้องรหัสผ่าน โปรดอ่านคำสั่งก่อนกดอนุมัติทุกครั้ง

> ⚠️ Agent อ่านไฟล์ใดก็ได้ในเครื่อง การอ่านข้อมูลลับที่ได้รับอนุมัติจะถูกปิดบังในแชต แต่ควรถือว่าประวัติบทสนทนาเป็นข้อมูลอ่อนไหว

### คำสั่ง / ในช่องแชตเว็บ

พิมพ์ `/` ในช่องแชตเพื่อเปิดเมนูคำสั่งและเลือกได้ทันที คำสั่งส่วนใหญ่ทำงานในเบราว์เซอร์โดยไม่ส่งไปยัง AI:

- `/help` แสดงคำสั่งทั้งหมดและ Skill ที่ใช้ได้
- `/new` หรือ `/clear` เริ่มบริบทการสนทนาใหม่
- `/model` และ `/status` ดู provider, model และสถานะการเชื่อมต่อ
- `/models [provider] [model]` ดูรายการ model หรือสลับ provider/model
- `/ping` วัดเวลาตอบกลับของเซิร์ฟเวอร์
- `/fallback [model|off]` ดูหรือเปลี่ยน fallback model
- `/skills` แสดงรายการ Skill
- `/skill <ชื่อ> [ข้อความ]` ใช้ Skill กับข้อความถัดไป หรือส่งข้อความที่ระบุทันที
- `/<ชื่อ-skill> [ข้อความ]` เป็นทางลัดของ `/skill <ชื่อ-skill> [ข้อความ]`

Skill ที่เรียกผ่านคำสั่ง `/` จะมีผลเฉพาะคำขอนั้น และไม่เปลี่ยน Skill ที่เลือกไว้ใน Settings

### Terminal

หน้า **Terminal** รันคำสั่ง shell บน Server โดยตรงด้วยสิทธิ์ของผู้ใช้ที่รันแอป เริ่มต้นในโฟลเดอร์โปรเจกต์ และรองรับ `cd` ภายในโปรเจกต์ คำสั่งมีเวลาจำกัด 60 วินาที ผลลัพธ์ถูกจำกัดที่ 100 KB ตัวแปรสภาพแวดล้อมที่ดูเหมือนข้อมูลลับจะถูกตัดออก และ API key/token ที่รู้จักจะถูกปิดบังในผลลัพธ์ ปิดใช้งานได้ใน **Settings**

> ⚠️ Terminal ทำงานด้วยสิทธิ์ของผู้ใช้ที่รันแอป เมื่อเปิดใช้ web auth เฉพาะอุปกรณ์ที่จับคู่แล้วเท่านั้นจึงจะใช้ได้ แต่ถ้าตั้ง `AI_WEB_AUTH=off` ใครที่เปิดหน้าเว็บได้ก็ใช้ Terminal ได้ ควรเปิดให้เข้าถึงเฉพาะในเครือข่ายที่เชื่อถือได้เท่านั้น

### Discord bot

ระบบรองรับการรัน Discord bot ร่วมกับเว็บแชต โดยใช้ provider และ model หลักจาก Settings เดียวกัน

1. สร้าง Application/Bot ใน [Discord Developer Portal](https://discord.com/developers/applications)
2. เปิด **Message Content Intent** ในหน้า Bot และเชิญ bot เข้า server ด้วย scope `bot` และสิทธิ์ส่งข้อความ
3. ไปที่ Settings ในเว็บ ใส่ Bot token เปิดใช้งาน Discord bot แล้วกดบันทึก
4. ใน Discord ให้ mention bot หรือพิมพ์ `!ai ข้อความของคุณ` (เปลี่ยน prefix ได้ใน Settings)

คำสั่ง slash ที่รองรับ: `/ai` ส่งงานให้ agent, `/new` เปิดแชทใหม่พร้อมประวัติบนเว็บทันที, `/models` เปลี่ยน provider/model พร้อมแสดงสถานะ, `/model` ดู model และสถานะ, `/clear` ล้างบริบทห้อง, `/thread` สร้างห้องย่อย, `/fallback` ตั้ง fallback เฉพาะห้องพร้อมแสดงสถานะ, `/ping` ตรวจ server และ `/help` ดูคำสั่งทั้งหมด

คำสั่งเปลี่ยน provider/model และตั้ง fallback ต้องใช้โดยผู้ดูแล server เท่านั้น หากต้องการเชิญ bot ด้วยสิทธิ Administrator ให้ใช้ `/invite` แล้วให้ผู้มีสิทธิ์จัดการ server กดลิงก์ (bot ไม่สามารถเพิ่มสิทธิ์ให้ตัวเองได้)

Token จะถูกเก็บไว้ฝั่งเซิร์ฟเวอร์ใน `.app-settings.json` ซึ่งไม่ถูก commit เข้า Git หรือจะตั้ง `DISCORD_BOT_TOKEN` และ `DISCORD_BOT_PREFIX` ใน `.env` ก็ได้

**จำกัดผู้ที่ใช้งาน bot ได้** ในหน้า Settings มีรายการอนุญาตสองช่อง: *จำกัดเฉพาะช่อง (Channel ID)* และ *จำกัดเฉพาะผู้ใช้ (User ID)* ถ้าเว้นว่างจะไม่จำกัด เมื่อใส่รายการแล้ว ข้อความและ slash command จากช่องหรือผู้ใช้ที่ไม่อยู่ในรายการจะถูกเพิกเฉย ทำให้เฉพาะคนและห้องที่ระบุเท่านั้นใช้เครดิต API ได้ DM จะได้รับอนุญาตตาม Channel ID ของ DM เอง เปิด **Developer Mode** ใน Discord แล้วใช้ *Copy ID* ที่ช่องหรือผู้ใช้เพื่อดูตัวเลข ค่าใน `.env` ที่เทียบเท่าคือ `DISCORD_ALLOWED_CHANNEL_IDS` และ `DISCORD_ALLOWED_USER_IDS` (คั่นด้วยจุลภาค) ส่วนคำสั่ง `/models`, `/fallback`, `/invite` และเครื่องมือสร้างงานตามเวลายังต้องมีสิทธิ์ Administrator เช่นเดิม

### Scheduler

งานตามเวลาจะทำงานเมื่อเซิร์ฟเวอร์เปิดอยู่ ใช้ `AI_WEB_ENABLE_SCHEDULER=1` เพื่อเปิดใช้งาน scheduler สำหรับการ deploy แบบ WSGI
