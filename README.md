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
