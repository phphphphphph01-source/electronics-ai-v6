# Electronics AI – Professional Upgrade

## สิ่งที่พัฒนาจากโปรเจกต์เดิม
- รักษา Flask, SQLite, YOLO, CLIP, Dataset และ History เดิม
- เพิ่ม Hybrid AI: YOLO ตรวจจับหลายวัตถุ → crop → CLIP verification เมื่อ CLIP พร้อม
- ไม่ relabel YOLO ด้วย CLIP แบบฝืน ๆ; CLIP เป็น verification signal
- เพิ่ม Offline-first สำหรับ CLIP: ค่าเริ่มต้นไม่ดาวน์โหลดโมเดลอัตโนมัติ (`ELECTRONICS_AI_ALLOW_MODEL_DOWNLOAD=0`)
- เพิ่ม Image pixel safety limit และ migration database แบบไม่ลบข้อมูล
- เพิ่ม `object_count`, `processing_time_ms`, `model_version`, `dataset_version`
- เพิ่ม index สำหรับ level และ engine
- เพิ่ม `/api/health` และ `/api/models`
- เพิ่ม API error object ที่มี `code`/`message` พร้อม compatibility สำหรับ frontend เดิม
- เพิ่มปุ่มกล้องมือถือ (`capture="environment"`)
- เพิ่ม processing state สำหรับ Quality → Detection → Verification → Finalizing
- ปรับ frontend error parsing ให้รองรับ API ใหม่

## AI Pipeline
Image → validation → quality check → YOLO multi-object detection → crop each object → CLIP verification (if locally available) → confidence/result validation → history/database.

## Dataset
ไม่ได้แก้ label โดยเดาเอง ควรใช้ `tools_dataset_audit.py` ก่อน train ทุกครั้ง.

## Run Windows
1. เปิด CMD ในโฟลเดอร์โปรเจกต์
2. activate virtual environment ของคุณ
3. `pip install -r requirements.txt`
4. `python app.py`
5. เปิด `http://127.0.0.1:5000`

## Train
`train_windows.bat`

## Test ที่ตรวจสอบใน environment นี้
- `python -m py_compile app.py` ผ่าน
- ไม่สามารถ run Flask integration test ได้ เพราะ environment ที่ใช้ build ไม่มี Flask ติดตั้ง (`ModuleNotFoundError: flask`)

## ข้อจำกัดที่ยังมี
- ความแม่นยำขึ้นกับจำนวนและคุณภาพ dataset
- CLIP verification จะทำงานเมื่อโมเดล CLIP มีอยู่ใน local cache; ระบบไม่ควร crash หากไม่มี
- Circuit analysis เป็น rule-based estimate จากสิ่งที่พบในภาพ ไม่ใช่การตรวจสอบ topology หรือไฟฟ้าจริง
