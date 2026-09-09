# Railway + Gemini

ระบบลำดับการตรวจจับ:
1. Custom YOLO ถ้ามี `models/best.pt`
2. CLIP/AI สำรองในเครื่อง (ถ้าโมเดลพร้อม)
3. Gemini Vision เมื่อผลก่อนหน้าไม่มั่นใจ

Gemini ใช้ `GEMINI_API_KEY` จาก Environment Variable เท่านั้น ไม่เก็บคีย์ใน Git

Railway Variables:
- `GEMINI_API_KEY` = API key ของ Google AI Studio
- `ELECTRONICS_AI_ENABLE_GEMINI_FALLBACK=1`
- `ELECTRONICS_AI_GEMINI_MODEL=gemini-3.8-flash`

ถ้า ZIP นี้ไม่มี `models/best.pt` ระบบยังสามารถใช้ Gemini ได้ แต่ Custom YOLO จะไม่ทำงานจนกว่าจะใส่ `models/best.pt` ในเครื่อง/Deploy ที่ใช้งานจริง
