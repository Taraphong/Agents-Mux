# AI Web บน Termux

เว็บแชต AI แบบเรียบง่าย รองรับ OpenAI และ Google Gemini

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
