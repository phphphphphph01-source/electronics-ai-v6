# Electronics AI — Gemini + YOLO + Railway

รุ่นนี้ถูกเตรียมสำหรับ GitHub + Railway โดยไม่ต้องฝึกโมเดลใหม่

## ลำดับการตรวจจับ

1. Custom YOLO (`models/best.pt`)
2. YOLO-World แบบ local เมื่อ YOLO ตัวแรกไม่มั่นใจ
3. Gemini Vision แบบ cloud เมื่อยังไม่มั่นใจ

Gemini จะไม่ถูกเรียกทุกภาพที่ YOLO ตรวจได้สำเร็จ เพื่อลด latency และการใช้ API

## ก่อนขึ้น Railway

ใน Railway > Variables ให้ตั้งอย่างน้อย:

- `GEMINI_API_KEY` = API key ของ Gemini
- `ELECTRONICS_AI_ENABLE_GEMINI_FALLBACK` = `1`
- `ELECTRONICS_AI_GEMINI_MODEL` = `gemini-3.7-flash`
- `ELECTRONICS_AI_ENABLE_WORLD_FALLBACK` = `1`
- `ELECTRONICS_AI_MODEL_PATH` = `models/best.pt`

ห้ามใส่ API key จริงลงใน Git หรือไฟล์ `.env` ที่ commit ขึ้น GitHub

## GitHub

```powershell
git init
git add .
git commit -m "Add Gemini vision fallback and Railway deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

ไฟล์โมเดลที่ใช้จริงมีขนาดต่ำกว่า GitHub hard limit 100 MB จึงไม่จำเป็นต้องใช้ Git LFS สำหรับสองไฟล์นี้

## Railway

เลือก `Deploy from GitHub repo` แล้วเลือก repository นี้

Start command ที่ใช้ได้:

```text
gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 app:app
```

Railway จะอ่าน `Procfile` ให้โดยอัตโนมัติในกรณีนี้

หลัง deploy ให้ Generate Domain แล้วทดสอบ:

- `/`
- `/api/status`
- `/api/health`

ถ้า Gemini ขึ้น `configured: true` ใน `/api/status` แปลว่าแอปมองเห็น `GEMINI_API_KEY` แล้ว
