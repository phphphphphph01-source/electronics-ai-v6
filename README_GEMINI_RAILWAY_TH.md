# Electronics AI — Gemini + Railway

ลำดับการตรวจจับของระบบ:

1. Custom YOLO ถ้ามีและมั่นใจพอ
2. Gemini Vision เมื่อ YOLO ไม่มั่นใจ/ไม่พบ
3. CLIP เป็น fallback ขั้นถัดไปเมื่อ Gemini ใช้งานไม่ได้หรือไม่มั่นใจ

## ติดตั้งใน Windows

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY="ใส่คีย์ของนายในเครื่องตัวเอง"
python app.py
```

ตรวจสถานะที่ `/api/status` และ `/api/models` จะเห็นสถานะ Gemini

## Railway

ตั้ง Variables:

- `GEMINI_API_KEY`
- `ELECTRONICS_AI_ENABLE_GEMINI_FALLBACK=1`
- `ELECTRONICS_AI_GEMINI_MODEL=gemini-3.8-flash`

อย่าใส่ API key จริงใน GitHub หรือไฟล์ `.env` ที่ commit
