# ระบบ AI เรียนรู้จาก Feedback

เวอร์ชันนี้ใช้การเรียนรู้ 2 ชั้นแบบปลอดภัย:

1. **Online Memory ทันที**
   - กด `AI ทายถูก` → จำภาพและชนิดอุปกรณ์ลง SQLite
   - กด `AI ทายผิด` → กรอกคำตอบที่ถูกต้อง → แทนที่ความจำเดิมของภาพนั้น
   - ภาพเดิมที่เคยยืนยันจะถูกจำแบบ exact-image และใช้ผลที่ยืนยันแล้วได้โดยตรง
   - ภาพที่หน้าตาคล้ายกันใช้เป็นเพียง hint ไม่บังคับให้เปลี่ยนคำตอบของ YOLO
   - ถ้า CLIP พร้อม ระบบจะเก็บ image embedding เพื่อค้นหาภาพที่คล้ายได้ดีกว่า dHash

2. **Learning Queue สำหรับพัฒนาโมเดล**
   - ทุก correction ถูกเก็บเป็นตัวอย่างที่ตรวจสอบได้
   - ถ้ามี YOLO detection ที่เชื่อถือได้เพียง 1 กล่อง ระบบจะสร้าง YOLO label จากกล่องจริงนั้น
   - ถ้ามีหลายวัตถุหรือไม่มีกรอบที่ปลอดภัย ระบบจะไม่สร้างกรอบปลอมเต็มภาพ และจะตั้ง `requires_annotation=true` เพื่อให้ตีกรอบก่อนฝึก
   - queue เป็น idempotent ต่อ `analysis_id` จึงไม่สร้างตัวอย่างซ้ำเมื่อส่ง feedback ซ้ำ

3. **ไม่ retrain อัตโนมัติจากการกดครั้งเดียว**
   - ไม่แก้ `best.pt` ทันที เพื่อป้องกันข้อมูลผิดและ catastrophic forgetting
   - ก่อนฝึกจริงควรตรวจตัวอย่าง, แบ่ง train/val, ฝึกโมเดลรุ่นใหม่ และเทียบ validation กับรุ่นเดิมก่อนสลับใช้งาน

## API

- `GET /api/feedback/<analysis_id>`
- `POST /api/feedback/<analysis_id>`
- `GET /api/learning/stats`
- `GET /api/learning/queue?status=pending|reviewed|used|all`
- `POST /api/learning/<id>/status`

ตัวอย่าง correction:

```json
{"is_correct": false, "corrected_label": "Arduino UNO"}
```

ระบบจะตรวจชื่อกับคลาสจริงของ dataset ก่อนบันทึก ไม่รับ label ที่ไม่มีอยู่ในโมเดล
