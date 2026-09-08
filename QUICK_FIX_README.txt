QUICK FIX - Electronics AI

ไฟล์ที่แก้:
1) app.py - เพิ่ม YOLO-World zero-shot fallback และเปลี่ยน flow ให้ fallback เมื่อ custom YOLO confidence ต่ำ แทนการยอมรับผลที่ไม่มั่นใจทันที
2) train.py - rare classes จะเป็น warning ไม่หยุดการ train ทั้งหมด แต่ missing/invalid/overlap ยังเป็น hard error

Dataset ที่ตรวจจากโปรเจกต์นี้:
- custom_dataset/train: 84 images / 84 labels
- custom_dataset/val: 27 images / 27 labels
- 62 classes
- train objects: 84
- 59/62 classes มี train objects น้อยกว่า 3
- 64 train boxes เป็น full-image

วิธีใช้:
- สำรอง app.py และ train.py เดิมก่อน
- แตกไฟล์นี้ทับในโฟลเดอร์โปรเจกต์
- รันเว็บตาม run_windows.bat เดิม
- ไม่จำเป็นต้องลบ dataset เดิม
- ถ้าจะ train ใหม่ ให้รัน train_windows.bat หลังตรวจ dataset

หมายเหตุ: quick fix นี้ไม่ได้สร้าง label ปลอมให้รูปที่ไม่มี label เพราะจะทำให้โมเดลเรียนข้อมูลผิด
