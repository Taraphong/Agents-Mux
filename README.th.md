# AI Web บน Termux

แชต AI แบบ self-hosted รันบน Termux เปิดผ่านเบราว์เซอร์ในเครือข่ายเดียวกัน รองรับ OpenAI, Gemini และ Anthropic

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

### ประวัติการสนทนา

บันทึกแยกตามวัน/เวลาใน `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json`

- โฟลเดอร์ `history/` ไม่ถูก commit เข้า Git
- สามารถเปลี่ยนชื่อ ปักหมุด ล็อก/ปลดล็อก ได้จากแชต

สำหรับข้อกำหนดและรูปแบบการทำงานที่ละเอียด กรุณาอ่าน **[AGENTS.md](AGENTS.md)**

## เครื่องมือ AI

- AI สามารถอ่านไฟล์ในโปรเจกต์ได้ทันที
- การเขียนไฟล์และรันคำสั่งต้องได้รับการอนุมัติในแชต (มีอายุ 15 นาที และใช้ได้ครั้งเดียว)
- Path ถูกจำกัดในโฟลเดอร์โปรเจกต์ ไม่รวม `.env`, `.app-settings.json`, `history/`, `.venv/`, และ `.git/`
- รันคำสั่งได้เฉพาะ `pwd`, `ls`, `git status|diff|log` และ `python -m py_compile app.py`

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

> ⚠️ ระบบนี้ไม่มีระบบล็อกอิน ใครที่เปิดหน้าเว็บได้ก็ใช้ Terminal ได้ ควรเปิดให้เข้าถึงเฉพาะในเครือข่ายที่เชื่อถือได้เท่านั้น

### Discord bot

ระบบรองรับการรัน Discord bot ร่วมกับเว็บแชต โดยใช้ provider และ model หลักจาก Settings เดียวกัน

1. สร้าง Application/Bot ใน [Discord Developer Portal](https://discord.com/developers/applications)
2. เปิด **Message Content Intent** ในหน้า Bot และเชิญ bot เข้า server ด้วย scope `bot` และสิทธิ์ส่งข้อความ
3. ไปที่ Settings ในเว็บ ใส่ Bot token เปิดใช้งาน Discord bot แล้วกดบันทึก
4. ใน Discord ให้ mention bot หรือพิมพ์ `!ai ข้อความของคุณ` (เปลี่ยน prefix ได้ใน Settings)

คำสั่ง slash ที่รองรับ: `/ai` ส่งงานให้ agent, `/new` เปิดแชทใหม่พร้อมประวัติบนเว็บทันที, `/models` เปลี่ยน provider/model พร้อมแสดงสถานะ, `/model` ดู model และสถานะ, `/clear` ล้างบริบทห้อง, `/thread` สร้างห้องย่อย, `/fallback` ตั้ง fallback เฉพาะห้องพร้อมแสดงสถานะ, `/ping` ตรวจ server และ `/help` ดูคำสั่งทั้งหมด

คำสั่งเปลี่ยน provider/model และตั้ง fallback ต้องใช้โดยผู้ดูแล server เท่านั้น หากต้องการเชิญ bot ด้วยสิทธิ Administrator ให้ใช้ `/invite` แล้วให้ผู้มีสิทธิ์จัดการ server กดลิงก์ (bot ไม่สามารถเพิ่มสิทธิ์ให้ตัวเองได้)

Token จะถูกเก็บไว้ฝั่งเซิร์ฟเวอร์ใน `.app-settings.json` ซึ่งไม่ถูก commit เข้า Git หรือจะตั้ง `DISCORD_BOT_TOKEN` และ `DISCORD_BOT_PREFIX` ใน `.env` ก็ได้

### Scheduler

งานตามเวลาจะทำงานเมื่อเซิร์ฟเวอร์เปิดอยู่ ใช้ `AI_WEB_ENABLE_SCHEDULER=1` เพื่อเปิดใช้งาน scheduler สำหรับการ deploy แบบ WSGI
