"""
undo_build_dataset.py
ย้อนกลับสิ่งที่ build_dataset.py ทำไป — ลบเฉพาะไฟล์รูป/label ที่ถูกเพิ่มเข้าไป
(ระบุจากชื่อไฟล์ใน custom_dataset_manifest.json เท่านั้น) โดยไม่แตะไฟล์ชุดข้อมูลเดิมที่มีอยู่ก่อน
(เช่น 18650_Lithium_Battery__051.jpg, 555_Timer_IC__060.jpg ฯลฯ)

วิธีใช้:
    python undo_build_dataset.py --dry-run   # ดูก่อนว่าจะลบอะไรบ้าง
    python undo_build_dataset.py             # ลบจริง
"""
import argparse
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MANIFEST_FILE = BASE_DIR / "custom_dataset_manifest.json"
DATASET_ROOT = BASE_DIR / "custom_dataset"


def main():
    ap = argparse.ArgumentParser(description="ลบไฟล์ที่ build_dataset.py เพิ่มเข้าไป (ตาม manifest)")
    ap.add_argument("--dry-run", action="store_true", help="แสดงรายการที่จะลบ โดยยังไม่ลบจริง")
    args = ap.parse_args()

    if not MANIFEST_FILE.exists():
        raise FileNotFoundError(f"ไม่พบ {MANIFEST_FILE}")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))

    deleted, not_found = [], []

    for entry in manifest:
        source_name = entry["source_name"]
        split = entry["split"]
        img_path = DATASET_ROOT / "images" / split / source_name
        lbl_path = DATASET_ROOT / "labels" / split / (Path(source_name).stem + ".txt")

        for p in (img_path, lbl_path):
            if p.exists():
                if args.dry_run:
                    deleted.append(f"[DRY-RUN] จะลบ: {p.relative_to(BASE_DIR)}")
                else:
                    p.unlink()
                    deleted.append(f"ลบแล้ว: {p.relative_to(BASE_DIR)}")
            else:
                not_found.append(str(p.relative_to(BASE_DIR)))

    print(f"ไฟล์ที่ลบ: {len(deleted)}")
    for d in deleted:
        print("  -", d)
    print(f"\nไม่พบไฟล์ (อาจถูกลบไปแล้ว หรือไม่เคยถูกสร้าง): {len(not_found)}")

    if args.dry_run:
        print("\n(โหมด dry-run: ยังไม่มีไฟล์ใดถูกลบจริง รันใหม่โดยไม่ใส่ --dry-run เพื่อลบจริง)")
    else:
        print("\nเสร็จแล้ว ลบไฟล์ที่ build_dataset.py เพิ่มไว้ทั้งหมดเรียบร้อย")
        print("ชุดข้อมูลเดิม (ที่เคยเทรนสำเร็จแล้ว) ไม่ถูกแตะต้อง")


if __name__ == "__main__":
    main()
