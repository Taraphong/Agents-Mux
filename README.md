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

สำหรับข้อกำหนดและรูปแบบการทำงานที่ละเอียด กรอ่ **[AGENTS.md](AGENTS.md)**

## เครื่องมือ AI

- AI สามารถอ่านไฟล์ในโปรเจกต์ได้ทันที
- การเขียนไฟล์และร้องคำสั่งต้องได้รับการอนุมัติในแชต (อายุ 15 นาที ใช้ครั้งเดียว)
- Path ถูกจำกัดในโฟลเดอร์โปรJECT ไม่รวม `.env`, `.app-settings.json`, `history/`, `.venv/`, `.git/`
- รันคำสั่งได้เฉพาะ `pwd`, `ls`, `git status|diff|log`, `python -m py_compile app.py`

### Scheduler

งานตามเวลาทำงานเมื่อเซิร์ฟเวอร์เปิด ใช้ `AI_WEB_ENABLE_SCHEDULER=1` สำหรับ WSGI