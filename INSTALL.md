# คู่มือติดตั้ง AI Web สำหรับผู้ใช้ทั่วไป

คู่มือนี้สำหรับผู้ที่ต้องการนำโปรเจกต์ไปรันเองบนเครื่องของตน (Termux บน Android, Linux หรือ macOS)
ทุกคำสั่งคัดลอกไปวางใน terminal ได้ทันที

> ระบบนี้ไม่มีหน้า login — ใช้เฉพาะในเครือข่ายที่เชื่อถือได้ และไม่ควรเปิดสู่อินเทอร์เน็ตโดยตรง

---

## สิ่งที่ต้องมี

- Python **3.10 ขึ้นไป** (Termux ติดตั้งผ่าน `pkg install python`)
- `git` (หรือดาวน์โหลดโปรเจกต์เป็น ZIP)
- API key อย่างน้อยหนึ่งรายการ: OpenAI / OpenRouter / Groq / Gemini / Anthropic / Hugging Face
- รองรับเฉพาะ Termux, Linux และ macOS (โค้ดใช้ `fcntl` จึงยังไม่รองรับ Windows)

---

## ทางลัด: ติดตั้งด้วยสคริปต์

```bash
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

สคริปต์ `install.sh` จะทำให้ทั้งหมดนี้:

1. ตรวจสอบว่า Python อยู่ในเวอร์ชันที่รองรับ
2. สร้าง virtual environment ที่ `.venv`
3. ติดตั้ง dependencies จาก `requirements.txt`
4. สร้าง `.env` จาก `.env.example` (ไม่เขียนทับไฟล์เดิม)
5. สร้างโฟลเดอร์ `logs/` และ `history/`
6. บน Termux จะติดตั้งคำสั่งสั้น `startweb` ให้อัตโนมัติ

หลังติดตั้งเสร็จ ให้ใส่ API key ใน `.env` แล้วเริ่มเซิร์ฟเวอร์ได้เลย (ดูหัวข้อถัดไป)

> หาก repository เป็นแบบส่วนตัว ให้ใช้ SSH (`git clone git@github.com:Taraphong/Agents-mux.git`) หรือดาวน์โหลด ZIP แล้วแตกไฟล์ จากนั้นรัน `bash install.sh` ในโฟลเดอร์นั้น

---

## ติดตั้งบน Termux (Android)

```bash
pkg update && pkg upgrade -y
pkg install -y python git
git clone https://github.com/Taraphong/Agents-mux.git ~/ai-web
cd ~/ai-web
bash install.sh
```

ตั้งค่า API key:

```bash
nano .env
```

แก้บรรทัดของผู้ให้บริการที่ต้องการ เช่น

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx
```

บันทึกด้วย `Ctrl+O` → `Enter` → `Ctrl+X`

เริ่มเซิร์ฟเวอร์:

```bash
./start_web.sh --start      # หรือ startweb --start
```

เปิดเบราว์เซอร์ที่ `http://127.0.0.1:5000`
และเปิดจากมือถือ/คอมเครื่องอื่นในวง Wi-Fi เดียวกันที่ `http://<IP-ของเครื่อง Termux>:5000`

หา IP ของเครื่อง:

```bash
ifconfig 2>/dev/null | grep -A1 wlan0
# หรือ
ip -4 addr show
```

> แนะนำให้รัน `termux-wake-lock` ไว้ เพื่อไม่ให้ Android พักการทำงานของเซิร์ฟเวอร์
> และถ้าใช้ Android 12+ ควรปิดการจำกัดแบตเตอรี่ให้ Termux

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

จากนั้นแก้ `.env`, เริ่มเซิร์ฟเวอร์ และเปิด `http://127.0.0.1:5000` เหมือนขั้นตอนบน Termux

---

## ติดตั้งบน macOS

```bash
xcode-select --install     # ถ้ายังไม่มี command line tools
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
| `OPENROUTER_API_KEY` | API key ของ OpenRouter |
| `GROQ_API_KEY` | API key ของ Groq |
| `HF_API_KEY` | API key ของ Hugging Face |
| `AI_BASE_URL` | ใช้เมื่อต้องชี้ไปยัง Base URL เฉพาะ (เว้นว่างได้) |
| `AI_WEB_ENABLE_SCHEDULER` | ตั้ง `1` เมื่อรันผ่าน WSGI เพื่อเปิด scheduler |

ค่าอื่น ๆ (system prompt, temperature, model, Discord bot ฯลฯ) ตั้งได้จากหน้า **Settings** ในเว็บ
และจะถูกเก็บไว้ใน `.app-settings.json` บนเครื่องผู้ใช้เท่านั้น

> `.env`, `.app-settings.json`, `history/` และ `.venv/` ไม่ถูก commit เข้า Git
> อย่าส่งไฟล์เหล่านี้ให้ผู้อื่น เพราะมี API key และประวัติสนทนาอยู่

---

## เริ่ม / หยุด / ตรวจสอบเซิร์ฟเวอร์

```bash
./start_web.sh --start     # เริ่ม (ถ้ายังไม่ทำงาน)
./start_web.sh --check     # ดูสถานะ
./start_web.sh --restart   # หยุดแล้วเริ่มใหม่ (ใช้หลังอัปเดตโค้ด)
./start_web.sh --stop      # หยุด
```

บน Termux หลังรัน `install.sh` สามารถใช้คำสั่งสั้นได้:

```bash
startweb --start
startweb --restart
startweb --check
startweb --stop
```

log ของเซิร์ฟเวอร์อยู่ที่ `debug-ai-web.log` ในโฟลเดอร์โปรเจกต์

หรือจะรันแบบเห็น log สด ๆ ใน terminal (ปิด terminal แล้วเซิร์ฟเวอร์จะหยุด):

```bash
source .venv/bin/activate
python app.py
```

---

## เปิดใช้งานจากเครื่องอื่นในเครือข่าย

เซิร์ฟเวอร์ฟังที่ `0.0.0.0` พอร์ต `5000` อยู่แล้ว

1. หา IP ของเครื่องที่รันเซิร์ฟเวอร์ (เช่น `192.168.1.50`)
2. เปิดเบราว์เซอร์จากเครื่องอื่นใน Wi-Fi เดียวกัน: `http://192.168.1.50:5000`
3. ถ้าเปิดไม่ได้ ให้ตรวจสอบว่าไฟร์วอลล์ของเครื่องนั้นเปิดพอร์ต 5000

เปลี่ยนพอร์ตได้ด้วย:

```bash
PORT=8080 ./start_web.sh --start
```

---

## อัปเดตโปรเจกต์

```bash
cd ~/ai-web
git pull
bash install.sh            # ติดตั้ง dependencies ใหม่ถ้ามีการเปลี่ยนแปลง
./start_web.sh --restart
```

ข้อมูลเดิม (`.env`, `.app-settings.json`, `history/`) จะไม่ถูกเขียนทับ

---

## แก้ปัญหาที่พบบ่อย

**`command not found: python3`**
ติดตั้ง Python ก่อน: `pkg install python` (Termux) หรือ `sudo apt install python3 python3-venv` (Debian/Ubuntu)

**`ensurepip is not available` / สร้าง `.venv` ไม่สำเร็จ**
Debian/Ubuntu: `sudo apt install python3-venv` แล้วรัน `bash install.sh` ใหม่

**ติดตั้ง dependencies ไม่สำเร็จ**
ตรวจสอบอินเทอร์เน็ต แล้วลองใหม่ หรืออัปเกรด pip ก่อน:
`./.venv/bin/python -m pip install --upgrade pip`

**เปิดเว็บจากเครื่องอื่นไม่ได้**
ตรวจว่าใช้ IP ในวงเดียวกัน, เซิร์ฟเวอร์ทำงานอยู่ (`./start_web.sh --check`) และไฟร์วอลล์เปิดพอร์ต 5000

**แก้โค้ด/อัปเดตแล้วหน้าเว็บไม่เปลี่ยน**
Flask รันแบบ `debug=False` ต้องรีสตาร์ต: `./start_web.sh --restart`

**API ตอบ error 401 / 403**
API key ใน `.env` ไม่ถูกต้องหรือหมดอายุ หรือยังไม่ได้เลือก `AI_PROVIDER` ให้ตรงกับ key ที่มี

---

## ถอนการติดตั้ง

```bash
./start_web.sh --stop
cd ~
rm -rf ~/ai-web          # ลบทั้งโปรเจกต์ รวมประวัติและ API key
rm -f "$PREFIX/bin/startweb"   # เฉพาะ Termux: ลบคำสั่งสั้น
```

> `rm -rf` จะลบ `.env` และ `history/` ไปด้วย หากต้องการเก็บประวัติให้สำรองโฟลเดอร์ `history/` ก่อน
