# AI Web บน Termux

แชต AI แบบ self-hosted รันบน Termux เปิดผ่านเบราว์เซอร์ในเครือข่ายเดียวกัน รองรับ OpenAI, Gemini และ Anthropic

## เริ่มใช้งาน

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

เปิดเว็บที่ `http://127.0.0.1:5000`

### การตั้งค่า

- กำหนด `AI_PROVIDER` ใน `.env` (openai, gemini, anthropic)
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
