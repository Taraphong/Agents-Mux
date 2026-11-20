# AI Web บน Termux

เว็บแชต AI แบบ self-hosted ที่รันบน Termux (Android), Linux หรือ macOS และใช้งานผ่านเบราว์เซอร์ในเครือข่ายเดียวกัน เซิร์ฟเวอร์ Flask ขนาดเล็กเก็บ API key และประวัติการสนทนาไว้บนเครื่องของคุณเอง และหน้าเว็บใช้ได้ทั้งภาษาอังกฤษและภาษาไทย

- คู่มือติดตั้ง: **[INSTALL.th.md](INSTALL.th.md)** · [INSTALL.md](INSTALL.md)
- นโยบายความปลอดภัย: **[SECURITY.th.md](SECURITY.th.md)** · [SECURITY.md](SECURITY.md)

## ฟีเจอร์

- **ผู้ให้บริการ 6 ราย** ผ่านหน้าแชตเดียว: OpenAI (หรือ API ที่เข้ากันได้กับ OpenAI), Google Gemini, Anthropic, Hugging Face, OpenRouter และ Groq
- **เลือก model และระดับการคิดต่อข้อความ** (`off`, `low`, `medium`, `high`) พร้อม fallback provider/model ที่ลองซ้ำให้หนึ่งครั้ง
- **ไฟล์แนบ**: ไฟล์ข้อความและโค้ดขนาดไม่เกิน 1 MB อ่านในเบราว์เซอร์ ส่วนรูปภาพและ PDF ขนาดไม่เกิน 6 MB ส่งแบบ inline และไฟล์เสียง/วิดีโอใช้ได้กับ Gemini
- **Skill**: ไฟล์คำสั่งใน `skills/` ที่เลือกใช้ใน Settings หรือใช้กับข้อความเดียวด้วย `/`
- **การจับคู่อุปกรณ์**: หน้าเว็บป้องกันด้วย Pairing Key ที่ใช้ได้ครั้งเดียว และ session ของอุปกรณ์ที่ยกเลิกได้
- **ประวัติการสนทนา** แยกตามวัน/เวลา เปลี่ยนชื่อ ปักหมุด ล็อก/ปลดล็อก และลบได้
- **เครื่องมือบนเครื่อง**: โมเดลสามารถ list/read/write ไฟล์ และรันคำสั่ง shell บนเซิร์ฟเวอร์ โดยต้องอนุมัติทุกครั้ง
- **Scheduler แบบ cron**, **หน้า Log ระบบ/Agent**, **อัปเดตจากหน้าเว็บ** และ **สั่ง start/stop/restart เซิร์ฟเวอร์**
- **ฟีเจอร์เสริมของ Gemini**: รายงาน capabilities, Decisions API, managed agents และ Live API token อายุสั้น
- **Discord bot** พร้อม allowlist ของช่องและผู้ใช้
- **สลับ HTTP/HTTPS จากหน้าเว็บ** ด้วยไฟล์ใบรับรองหรือใบรับรองชั่วคราว
- เลย์เอาต์รองรับมือถือ, Enter เพื่อส่ง, Shift+Enter ขึ้นบรรทัดใหม่ และปุ่มสลับภาษาไทย/อังกฤษ

## สิ่งที่ต้องมี

- Python **3.10 ขึ้นไป**
- `openssl` เฉพาะเมื่อต้องการให้เซิร์ฟเวอร์ทำ HTTPS เอง
- API key ของผู้ให้บริการอย่างน้อยหนึ่งราย

## เริ่มใช้งานแบบเร็ว

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

ตั้ง `AI_PROVIDER` และ API key ที่ตรงกันใน `.env` แล้วเริ่มเซิร์ฟเวอร์:

```bash
./start_web.sh --start
```

เปิด `http://127.0.0.1:5000` (หรือ `http://<ip-ของเครื่อง>:5000` จากอุปกรณ์อื่น) การเริ่มครั้งแรกที่ยังไม่มีอุปกรณ์จับคู่ เซิร์ฟเวอร์จะแสดง Pairing Key ให้ เปิด `/pair` แล้วใส่คีย์นั้น

หรือติดตั้งเองทีละขั้น:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## การตั้งค่า

`install.sh` สร้าง `.env` จาก `.env.example` ไฟล์นี้ถูกอ่านตอนเริ่มโปรเซส และเป็นเพียงค่าเริ่มต้นเท่านั้น

### ผู้ให้บริการ

| `AI_PROVIDER` | ผู้ให้บริการ | API key | ตัวแปร model เริ่มต้น |
| --- | --- | --- | --- |
| `openai` | OpenAI หรือ API ที่เข้ากันได้ | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| `anthropic` | Anthropic (Claude) | `ANTHROPIC_API_KEY` | เลือก model ของ Claude ใน Settings |
| `hf` | Hugging Face | `HF_API_KEY` | `HF_MODEL` |
| `or` | OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |
| `groq` | Groq | `GROQ_API_KEY` | `GROQ_MODEL` |

- **Anthropic:** model ตอนเริ่มระบบมาจาก `OPENAI_MODEL` ดังนั้นหลังตั้ง `AI_PROVIDER=anthropic` และ `ANTHROPIC_API_KEY` แล้ว ให้เปิด **Settings** และเลือก model ของ Claude รายการ model จะถูกดึงจาก API เมื่อมี key แล้ว
- **Base URL:** ตั้ง endpoint เองได้ใน `.env` (`AI_BASE_URL`) หรือใน Settings ระบบจะส่ง API key ผ่าน HTTPS เท่านั้น และปฏิเสธ HTTP ปกติยกเว้น loopback (เซิร์ฟเวอร์ OpenAI-compatible ในเครื่อง) เว้นแต่ตั้ง `AI_WEB_ALLOW_INSECURE_PROVIDER_HTTP=1`
- **ระดับการคิด:** `off`, `low`, `medium`, `high` เลือกใน Settings หรือต่อข้อความจากแถบเครื่องมือในหน้าแชต
- **Fallback:** เปิด fallback provider และ model ใน Settings คำขอแรกที่ล้มเหลวจะถูกลองใหม่หนึ่งครั้งด้วยค่านั้น `/fallback` ใช้ดูหรือเปลี่ยนค่า

### Settings กับ `.env`

- ค่าที่บันทึกใน **Settings** ถูกเก็บใน `.app-settings.json` และทับค่าใน `.env` รวมถึง provider, model และ API key
- ถ้าแก้ `.env` แล้วไม่เห็นผล ให้แก้ใน Settings แทน หรือกด **Reset** ที่ด้านล่างของ Settings (ลบ `.app-settings.json`) แล้วรีสตาร์ต
- API key และ Discord token ถูกเก็บฝั่งเซิร์ฟเวอร์ใน `.app-settings.json` หน้าเว็บได้รับเพียงค่าที่ปิดบังไว้เท่านั้น

### ตัวแปรสภาพแวดล้อมอื่น ๆ

| ตัวแปร | ความหมาย |
| --- | --- |
| `PORT` | พอร์ตที่รับฟัง (ค่าเริ่มต้น `5000`) |
| `AI_FALLBACK_PROVIDER`, `AI_FALLBACK_MODEL` | ค่า fallback เริ่มต้น |
| `GEMINI_LIVE_MODEL`, `GEMINI_AGENT`, `GEMINI_DECISION_MODEL` | ค่าเริ่มต้นของฟีเจอร์ Gemini |
| `DISCORD_BOT_TOKEN`, `DISCORD_BOT_PREFIX` | ข้อมูล Discord bot และ prefix ของข้อความ |
| `DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_CHANNEL_IDS` | allowlist ของ Discord (คั่นด้วยจุลภาค) |
| `AI_WEB_AUTH` | `on` (ค่าเริ่มต้น) หรือ `off` เพื่อปิดการจับคู่อุปกรณ์ |
| `AI_WEB_AUTH_FILE` | ไฟล์เก็บ Pairing Key และ session (ค่าเริ่มต้น `.app-auth.json`) |
| `AI_WEB_PAIRING_TTL_MINUTES` | อายุของ Pairing Key (ค่าเริ่มต้น `30` นาที) |
| `AI_WEB_SESSION_DAYS` | อายุ session ของอุปกรณ์ (ค่าเริ่มต้น `30` วัน) |
| `AI_WEB_TRUST_PROXY` | ตั้งเป็น `1` เมื่อมี reverse proxy ที่ terminate TLS |
| `AI_WEB_TLS_CERT`, `AI_WEB_TLS_KEY`, `AI_WEB_TLS_ADHOC` | โหมด HTTPS |
| `AI_WEB_ENABLE_SCHEDULER` | ตั้งเป็น `1` เพื่อเปิด Scheduler เมื่อรันใต้ WSGI |
| `AI_WEB_MAX_CONTENT_BYTES` | ขนาดสูงสุดของ request body (ค่าเริ่มต้น 8 MB) |
| `AI_WEB_LOG_MAX_ENTRIES` | จำนวนรายการ log ในหน่วยความจำ (ค่าเริ่มต้น `1000`) |
| `AI_WEB_LOG_FILE`, `AI_WEB_SETTINGS_FILE`, `AI_WEB_HISTORY_DIR`, `AI_WEB_SKILLS_DIR`, `AI_WEB_SCHEDULE_FILE`, `AI_WEB_WORKSPACE_DIR` | เปลี่ยนที่เก็บข้อมูล |

## หน้าแชต

- **Provider, model และระดับการคิด** เลือกได้ใน Settings และเปลี่ยนเฉพาะข้อความถัดไปได้จากแถบเครื่องมือเหนือช่องแชต
- **โหมดการรันคำสั่ง** อยู่ข้างกัน: `ถามก่อน` (ค่าเริ่มต้น) จะหยุดขออนุมัติก่อนเรียกเครื่องมือทุกครั้ง ส่วน `อัตโนมัติ` และ `Fast+` ให้โมเดลใช้เครื่องมือในเทิร์นนั้นได้โดยไม่ถาม เมื่อ **สิทธิ์เข้าถึงเครื่อง** ปิดอยู่ — ถ้าเปิดสิทธิ์เข้าถึงเครื่อง ทุกครั้งยังต้องอนุมัติเสมอ
- **ไฟล์แนบ:** ไฟล์ข้อความไม่เกิน 1 MB อ่านในเบราว์เซอร์และส่งเป็นข้อความ รูปภาพและ PDF ไม่เกิน 6 MB ส่งแบบ inline ส่วนเสียงและวิดีโอใช้ได้เฉพาะ Gemini และ PDF ใช้ได้กับ Gemini หรือ Anthropic
- ปิดการแสดง Markdown ได้ใน Settings คัดลอกข้อความได้ และ Enter เพื่อส่ง / Shift+Enter เพื่อขึ้นบรรทัดใหม่

### คำสั่ง /

พิมพ์ `/` ในช่องแชตเพื่อเปิดเมนูคำสั่ง

| คำสั่ง | การทำงาน |
| --- | --- |
| `/help` | แสดงคำสั่งทั้งหมดและ Skill ที่ใช้ได้ |
| `/new`, `/clear` | เริ่มบริบทการสนทนาใหม่ |
| `/model` | แสดง provider และ model ที่ใช้งาน |
| `/models [provider] [model]` | ดูรายการ model หรือสลับ provider/model |
| `/status` | แสดง provider, model และสถานะความพร้อม |
| `/ping` | วัดเวลาตอบกลับของเซิร์ฟเวอร์ |
| `/fallback [model\|off]` | ดูหรือเปลี่ยน fallback model |
| `/skills` | แสดงรายการ Skill |
| `/skill <ชื่อ> [ข้อความ]` | ใช้ Skill กับข้อความถัดไป หรือกับข้อความที่ระบุทันที |
| `/<ชื่อ-skill> [ข้อความ]` | ทางลัดของ `/skill <ชื่อ-skill> [ข้อความ]` |

Skill ที่เรียกผ่านคำสั่ง `/` มีผลเฉพาะคำขอนั้น และไม่เปลี่ยน Skill ที่เลือกไว้ใน Settings

## ประวัติการสนทนา

การสนทนาถูกเก็บเป็น JSON แยกตามวัน: `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json` โฟลเดอร์ `history/` ไม่ถูก commit เข้า Git

- เปลี่ยนชื่อ ปักหมุด ล็อก/ปลดล็อก และลบการสนทนาได้จากแถบด้านข้าง
- การสนทนาที่ล็อกไว้จะปฏิเสธการแก้ข้อความและชื่อ จนกว่าจะปลดล็อก
- API เปิด `/api/history` และ `/api/history/<id>` ให้หน้าเว็บใช้ โดยทุกคำขอต้องมี session ที่จับคู่แล้ว

## หน้า Settings

หน้า Settings แบ่งเป็นการ์ดต่าง ๆ:

- **การเชื่อมต่อ** — provider, API key, Base URL, รายการ model, ทดสอบการเชื่อมต่อ, Custom API key ที่ Skill หรือ Scheduler เรียกใช้ได้ และการ์ด Gemini
- **Gemini** — รายงาน capabilities ของ key ที่เก็บไว้ (multimodal, Live, Decisions, agents), ตัวรัน Decisions, ตัวรัน managed agent และปุ่มเริ่ม Live API ที่สร้าง token อายุสั้นให้เบราว์เซอร์
- **Agent** — ชื่อและบทบาทของ agent, system prompt, คำสั่งทบทวนความจำ และ Skill ที่ใช้กับการสนทนาทุกครั้ง
- **การตอบ** — ภาษาคำตอบ (`auto`, ไทย, อังกฤษ), สไตล์คำตอบ, Markdown, คำถามเพื่อความชัดเจน, temperature, top-p, max tokens, streaming, ระดับการคิด และ fallback model
- **การเชื่อมต่อภายนอก** — สิทธิ์เข้าถึงเครื่อง และ Discord bot (token, prefix, allowlist)
- **ความปลอดภัย** — Pairing Key และอุปกรณ์ที่เชื่อมต่อ พร้อมยกเลิกทีละเครื่องหรือออกจากระบบทั้งหมด
- **อัปเดต** — เวอร์ชันที่ติดตั้ง, ตรวจสอบแบบ dry run, อัปเดตจริง และ log ของการอัปเดต
- **เซิร์ฟเวอร์** — start, stop, restart ผ่าน `start_web.sh` พร้อม PID และเวลาทำงาน
- **เว็บและ HTTPS** — โหมด HTTP/HTTPS, สถานะใบรับรอง และข้อความแจ้งรีสตาร์ตพร้อมที่อยู่ใหม่

## เครื่องมือบนเครื่องและการอนุมัติ

path แบบ relative ที่ส่งให้ `list_files`, `read_file`, `write_file` และโฟลเดอร์เริ่มต้นของ `run_command` คือโฟลเดอร์ `workspace/` ในโปรเจกต์ (เปลี่ยนได้ด้วย `AI_WEB_WORKSPACE_DIR`) ไฟล์ที่ agent สร้างจึงอยู่รวมกันที่นั่นและไม่ถูก commit

เมื่อ **สิทธิ์เข้าถึงเครื่อง** เปิดอยู่ (ค่าเริ่มต้น) โมเดลใช้เครื่องมือเหล่านี้ได้ทั่วทั้งเครื่อง:

| เครื่องมือ | หน้าที่ |
| --- | --- |
| `list_files` | แสดงรายการในโฟลเดอร์ |
| `read_file` | อ่านไฟล์ได้สูงสุด 200 KB |
| `write_file` | เขียนไฟล์ได้สูงสุด 200 KB |
| `run_command` | รันคำสั่ง shell (จำกัด 60 วินาที ผลลัพธ์ 100 KB) |
| `create_skill` | สร้าง Skill ใน `skills/` |
| `create_schedule`, `update_schedule` | สร้างหรือแก้งานตามเวลาแบบ cron |

ทุกครั้งที่เรียก — รวมถึงการอ่านไฟล์ — ต้องอนุมัติในแชต การอนุมัติใช้ได้ครั้งเดียว ผูกกับชื่อเครื่องมือและ arguments ตรงตัว และมีอายุ 15 นาที API key, token และ PEM private key ที่ระบบรู้จักจะถูกปิดบังในผลลัพธ์

ปิด **Settings → สิทธิ์เข้าถึงเครื่อง** เพื่อจำกัดเครื่องมือให้อยู่ในโฟลเดอร์โปรเจกต์ และใช้ allowlist `pwd` / `ls` / `git status|diff|log` (ไม่มี shell)

> ⚠️ คำสั่งที่อนุมัติแล้วจะรันด้วยสิทธิ์ของผู้ใช้ที่รันแอป รวมถึง `sudo` เมื่อผู้ใช้นั้นใช้ได้โดยไม่ต้องรหัสผ่าน โปรดอ่านคำสั่งก่อนอนุมัติทุกครั้ง

## Scheduler

หน้า **Schedule** เก็บงานแบบ cron (5 ช่อง) ไว้ใน `scheduled-jobs.json` และรันขณะเซิร์ฟเวอร์ทำงาน โดยใช้ timezone ของเซิร์ฟเวอร์

- แต่ละงานมีชื่อ, ตารางเวลา, prompt, model (ไม่บังคับ), สถานะเปิด/ปิด และ Discord Channel ID (ไม่บังคับ) สำหรับส่งผลลัพธ์
- งานแต่ละงานมีบทสนทนาของตัวเองในประวัติ พร้อมเวลาและสถานะการรันครั้งล่าสุดและข้อผิดพลาด
- `AI_WEB_ENABLE_SCHEDULER=1` เปิด Scheduler เมื่อแอปรันใต้ WSGI ภายนอก

## Log

หน้า **Logs** แสดงเหตุการณ์ของระบบและกิจกรรมของ agent/เครื่องมือล่าสุด: การเรียกผู้ให้บริการ, การอนุมัติเครื่องมือ, งานตามเวลา และการสั่งเซิร์ฟเวอร์ โดยไม่แสดง API key หรือเนื้อหาไฟล์

- หน่วยความจำเก็บรายการล่าสุด 1000 รายการ และไฟล์ `logs/app-log.jsonl` เก็บ log แบบถาวร
- ดาวน์โหลดเป็นไฟล์หรือลบรายการได้จากหน้าเว็บ

## การอัปเดตและการควบคุมเซิร์ฟเวอร์

- **อัปเดต** แสดงเวอร์ชันที่ติดตั้งและผลการรันครั้งล่าสุด และสั่ง dry run (`update.sh --dry-run --no-restart`) หรืออัปเดตจริงได้ ระบบจะรัน `update.sh` ซึ่งแทนที่เฉพาะไฟล์แอป และไม่แตะ `.env`, settings, สถานะการจับคู่, ใบรับรอง, ประวัติ, log, งานตามเวลา หรือ `.venv`
- **เซิร์ฟเวอร์** ส่ง start, stop หรือ restart ให้ `start_web.sh` ซึ่งเป็นสคริปต์เดียวกับที่ใช้บน CLI การรีสตาร์ตจากหน้าเว็บจะรอ 2 วินาทีเพื่อให้คำตอบถึงเบราว์เซอร์ก่อน

## Discord bot

แอปรัน Discord bot คู่กับ Flask ได้ และตอบด้วย provider/model ที่ตั้งไว้

1. สร้าง bot ใน [Discord Developer Portal](https://discord.com/developers/applications)
2. เปิด **Message Content Intent** แล้วเชิญ bot ด้วย scope `bot` และสิทธิ์ส่งข้อความ
3. ใน Settings ใส่ bot token เปิดใช้งาน Discord แล้วบันทึก
4. ใน Discord ให้ mention bot หรือพิมพ์ `!ai <ข้อความ>` (เปลี่ยน prefix ได้)

คำสั่ง slash: `/ai` ส่งงานให้ agent, `/new` เปิดแชทใหม่พร้อมประวัติบนเว็บ, `/models` เปลี่ยน provider/model, `/model` ดู model และสถานะ, `/status` ดูความพร้อม, `/clear` ล้างบริบทของห้อง, `/thread` สร้างห้องย่อย, `/fallback` ตั้ง fallback ของห้อง, `/ping` ตรวจความหน่วง, `/invite` สร้างลิงก์เชิญแบบ Administrator และ `/help` แสดงคำสั่งทั้งหมด การเปลี่ยน model และการตั้ง fallback ต้องมีสิทธิ์ **Administrator** ใน Discord ส่วนลิงก์ `/invite` ต้องให้ผู้มีสิทธิ์จัดการ server เป็นคนเปิด เพราะ bot ไม่สามารถให้สิทธิ์ตัวเองได้

**จำกัดผู้ที่ใช้งาน bot ได้** ใน Settings มี allowlist สองช่อง: *จำกัดเฉพาะช่อง* และ *จำกัดเฉพาะผู้ใช้* ถ้าเว้นว่างจะไม่จำกัด เมื่อใส่รายการแล้ว ข้อความและ slash command จากช่องหรือผู้ใช้อื่นจะถูกเพิกเฉย ทำให้เฉพาะคนและห้องที่ระบุเท่านั้นใช้เครดิต API ได้ DM จะได้รับอนุญาตตาม Channel ID ของ DM เอง — เปิด **Developer Mode** ใน Discord แล้วใช้ *Copy ID* ค่าใน `.env` ที่เทียบเท่าคือ `DISCORD_ALLOWED_CHANNEL_IDS` และ `DISCORD_ALLOWED_USER_IDS` งานตามเวลาที่ส่งเข้า Discord ยังต้องมีสิทธิ์ Administrator

## การจับคู่อุปกรณ์

หน้าเว็บต้องจับคู่อุปกรณ์ก่อนใช้งาน และ Pairing Key ถูกสร้างจากฝั่งเซิร์ฟเวอร์เท่านั้น

- สร้างคีย์ด้วย `python app.py --pairing-key` (หรือ `./start_web.sh --pair`) การเริ่มครั้งแรกที่ยังไม่มีอุปกรณ์จับคู่จะสร้างให้อัตโนมัติ
- ที่ฝั่ง client เปิด `http://<ip-ของเครื่อง>:5000/pair` แล้วใส่คีย์ ระบบจะออกคุกกี้ session แบบ `HttpOnly` อายุ `AI_WEB_SESSION_DAYS` (ค่าเริ่มต้น 30 วัน)
- คีย์ใช้ได้ครั้งเดียวและหมดอายุใน `AI_WEB_PAIRING_TTL_MINUTES` (ค่าเริ่มต้น 30 นาที) ระบบเก็บเฉพาะ hash SHA-256 ใน `.app-auth.json` ซึ่งไม่ถูก commit
- ดู ยกเลิก หรือเพิ่มอุปกรณ์ได้ที่ **Settings → ความปลอดภัย** และใช้ `python app.py --revoke-sessions` เพื่อยกเลิกทุกอุปกรณ์
- `AI_WEB_AUTH=off` ปิดการจับคู่ ใช้เฉพาะในเครือข่ายที่เชื่อถือได้ทั้งหมด หน้าเว็บที่ยังไม่จับคู่จะถูกพาไป `/pair` ส่วน `/api/auth/status` ยังเข้าถึงได้เพื่อตรวจสถานะ
- เมื่อมี reverse proxy ที่ terminate TLS ให้ตั้ง `AI_WEB_TRUST_PROXY=1` เพื่อให้เชื่อถือ `X-Forwarded-Proto` และคุกกี้ session ถูกตั้งเป็น `Secure`

## HTTPS

แอปทำ HTTPS เองได้ โดยต้องมี `openssl` อย่างเดียว

- **จากหน้าเว็บ:** **Settings → เว็บและ HTTPS** เลือก HTTP, HTTPS ด้วยไฟล์ใบรับรอง หรือ HTTPS ด้วยใบรับรองชั่วคราว แล้วบันทึกและรีสตาร์ต หน้าเว็บไม่สามารถตามการรีสตาร์ตที่เปลี่ยนโปรโตคอลได้ จึงแสดงที่อยู่ใหม่ให้เปิดแทน
- สร้างใบรับรอง self-signed สำหรับ IP ใน LAN: `./start_web.sh --make-cert 192.168.0.50` (บน Termux ติดตั้ง `openssl` ด้วย `pkg install openssl-tool`) ไฟล์จะอยู่ที่ `certs/cert.pem` และ `certs/key.pem` ซึ่งไม่ถูก commit
- ตั้ง `AI_WEB_TLS_CERT` และ `AI_WEB_TLS_KEY` ใน `.env` แล้วรัน `./start_web.sh --restart` เปิด `https://<ip-ของเครื่อง>:5000` คุกกี้ session จะถูกตั้งเป็น `Secure` อัตโนมัติ
- โหมด "HTTPS ด้วยไฟล์ใบรับรอง" ในหน้าเว็บใช้ `certs/cert.pem` + `certs/key.pem` ก่อน ถ้าไม่มีไฟล์จะใช้คู่ไฟล์ที่ตั้งไว้ใน `.env` อยู่แล้ว แทนการปฏิเสธโหมดที่เซิร์ฟเวอร์กำลังรันอยู่
- `AI_WEB_TLS_ADHOC=1` (หรือโหมดใบรับรองชั่วคราวในหน้าเว็บ) สร้างใบรับรอง self-signed ด้วย `openssl` ครอบคลุม `localhost`, `127.0.0.1`, ชื่อเครื่อง และ IP ใน LAN แล้วใช้ไฟล์เดิม `certs/adhoc-cert.pem` / `certs/adhoc-key.pem` ทุกครั้งที่สตาร์ต ไม่ต้องใช้แพ็กเกจ `cryptography`
- การสลับ HTTPS → HTTP ไม่รักษาการลงชื่อเข้าใช้เดิม: เบราว์เซอร์ไม่ส่งคุกกี้ `Secure` ผ่าน HTTP และ `ai-web-session-http` จะถูกสร้างหลังจับคู่ใหม่เท่านั้น ชื่อคุกกี้ที่แยกกันคือสิ่งที่ทำให้อุปกรณ์จับคู่ใหม่บน HTTP ได้
- ใบรับรอง self-signed ทำให้เบราว์เซอร์เตือนครั้งแรก ใช้ใบรับรองจาก CA ที่เชื่อถือได้ หรือติดตั้ง CA ของคุณในอุปกรณ์แต่ละเครื่อง เพื่อไม่ให้มีคำเตือน
- ถ้าใช้ reverse proxy (Caddy, nginx, `tailscale serve`) ให้เว้น `AI_WEB_TLS_*` ว่างและตั้ง `AI_WEB_TRUST_PROXY=1` โดย proxy ต้องเขียนทับ `X-Forwarded-Proto` ทุก request
- `tailscale cert` ต้องรันบนเครื่องที่เป็นเจ้าของชื่อนั้น แอป Tailscale บน Android ไม่มี CLI เครื่อง Termux/Android จึงออกใบรับรอง Tailscale ของตัวเองไม่ได้ ให้รัน `tailscale serve` บนเครื่องอื่นใน tailnet ที่ proxy มาที่นี่ หรือใช้ใบรับรองจาก CA ที่เชื่อถือได้

## ไฟล์และข้อมูล

| Path | เนื้อหา | commit ไว้ |
| --- | --- | --- |
| `app.py` | เซิร์ฟเวอร์ Flask, API, เครื่องมือ, Scheduler, Discord bot | ใช่ |
| `templates/index/` | HTML, CSS, JS ของหน้าแชต (chat, settings, schedule, logs, about) | ใช่ |
| `templates/pair/` | HTML, CSS, JS ของหน้าจับคู่ | ใช่ |
| `skills/` | Skill หนึ่งไฟล์ `<name>/SKILL.md` ต่อหนึ่ง Skill | ใช่ (ยกเว้น Skill ที่คุณเพิ่มเอง) |
| `install.sh`, `start_web.sh`, `update.sh` | ตัวติดตั้ง ตัวควบคุมโปรเซส และตัวอัปเดต | ใช่ |
| `.env` | API key และการตั้งค่าตอนรัน | ไม่ |
| `.app-settings.json` | ค่าที่บันทึกจากหน้าเว็บ | ไม่ |
| `.app-auth.json` | hash ของ Pairing Key และ session | ไม่ |
| `certs/` | ใบรับรอง TLS, private key และไฟล์ ad-hoc | ไม่ |
| `history/` | ประวัติการสนทนา | ไม่ |
| `logs/` | log ของแอปและเซิร์ฟเวอร์ | ไม่ |
| `scheduled-jobs.json` | งานตามเวลา | ไม่ |

ห้าม commit `.env`, `.app-settings.json`, `.app-auth.json`, `certs/` (โดยเฉพาะ `key.pem`), `history/`, `logs/` หรือ `scheduled-jobs.json` และห้ามคัดลอกไฟล์เหล่านี้ข้ามเครื่อง
