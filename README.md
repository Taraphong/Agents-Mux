# AI Web บน Termux

สำหรับ Agents ที่เข้ามาทำงานร่วมกัน โปรดอ่าน [AGENTS.md](AGENTS.md) ก่อนแก้ไขโปรเจกต์

เว็บแชต AI สำหรับ Termux พร้อม Control Center สำหรับตั้งค่า provider, model, endpoint, API key, system prompt และพารามิเตอร์การตอบ รองรับ OpenAI-compatible, Google Gemini และ Anthropic

## เริ่มใช้งาน

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

เปิดเว็บที่ `http://127.0.0.1:5000`

ตั้งค่า API key ในไฟล์ `.env` และเลือก `AI_PROVIDER=openai` หรือ `AI_PROVIDER=gemini`

หรือเปิดเมนู `Settings` ในเว็บเพื่อบันทึกค่าลงไฟล์ `.app-settings.json` ซึ่งถูกกันออกจาก Git แล้ว

เมนู Settings มีระดับการคิด `ปิด`, `ต่ำ`, `กลาง`, `สูง` โดย OpenAI reasoning models จะใช้ `reasoning_effort` และ Gemini จะใช้ `thinkingConfig` ตามรุ่นที่รองรับ

ประวัติการสนทนาจะถูกบันทึกแยกตามวันและเวลาในรูปแบบ `history/YYYY-MM-DD/HH-MM-SS_<conversation-id>.json` และโฟลเดอร์ `history/` จะไม่ถูก commit เข้า Git

แต่ละประวัติสามารถเปลี่ยนชื่อ ปักหมุด ล็อก/ปลดล็อก และลบได้จากแถบด้านซ้าย โดยประวัติที่ปักหมุดจะแสดงด้านบน และประวัติที่ล็อกจะลบหรือเปลี่ยนชื่อไม่ได้จนกว่าจะปลดล็อก

## เครื่องมือของ AI

AI สามารถขอลิสต์และอ่านไฟล์ภายในโปรเจกต์ได้ทันที ส่วนการเขียนไฟล์ (`write_file`) และการรันคำสั่ง (`run_command`) ต้องให้ผู้ใช้กดอนุมัติในหน้าแชต คำขออนุมัติมีอายุ 15 นาทีและใช้ได้ครั้งเดียว

- ทุก path ถูกจำกัดอยู่ในโฟลเดอร์โปรเจกต์ และไม่รวม `.env`, `.app-settings.json`, `history/`, `.venv/`, `.git/`
- `run_command` รับเฉพาะ `pwd`, `ls`, `git status|diff|log` และ `python -m py_compile app.py` โดยไม่เรียกผ่าน shell

## งานตามเวลา (Cron jobs)

งานตามเวลาจะทำงานเมื่อเซิร์ฟเวอร์เปิดอยู่ และ scheduler จะรันได้ครั้งละหนึ่งโปรเซสโดยใช้ไฟล์ `scheduled-jobs.json.lock` เมื่อรันด้วย `python app.py` scheduler จะเริ่มอัตโนมัติ หากรันผ่าน WSGI ให้ตั้ง `AI_WEB_ENABLE_SCHEDULER=1`
