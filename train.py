from pathlib import Path
import json
from collections import Counter
import hashlib
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
MODEL = BASE_DIR / "yolo11n.pt"
DATA = BASE_DIR / "dataset.yaml"
PROJECT = BASE_DIR / "runs"
NAME = "electronics"


def dataset_audit(fail_on_missing=True):
    """Strict YOLO dataset preflight.

    The training set must contain a matching .txt label for every image that
    contains a target object. This audit does not invent labels: it reports
    missing/orphan/invalid labels and stops training when the dataset is unsafe.
    """
    import yaml

    cfg = yaml.safe_load(DATA.read_text(encoding="utf-8")) or {}
    configured_root = Path(str(cfg.get("path", "custom_dataset")))
    root = (BASE_DIR / configured_root).resolve() if not configured_root.is_absolute() else configured_root.resolve()

    train = (root / cfg["train"]).resolve()
    val = (root / cfg["val"]).resolve()
    train_labels = (root / "labels" / "train").resolve()
    val_labels = (root / "labels" / "val").resolve()
    names = {int(k): str(v) for k, v in (cfg.get("names", {}) or {}).items()}

    report = {
        "dataset_root": str(root),
        "train_images": 0,
        "val_images": 0,
        "train_labeled_images": 0,
        "val_labeled_images": 0,
        "classes": len(names),
        "issues": [],
        "missing_labels": {"train": [], "val": []},
        "orphan_labels": {"train": [], "val": []},
        "empty_labels": {"train": [], "val": []},
        "bad_labels": [],
        "class_counts": {},
        "train_val_overlap": [],
        "full_image_boxes": 0,
        "full_image_box_files": [],
        "corrupt_images": {"train": [], "val": []},
        "duplicate_images": [],
    }

    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".jfif"}

    def scan(image_folder, label_folder, split):
        counts = Counter()
        images = sorted(p for p in image_folder.glob("*") if p.suffix.lower() in image_exts) if image_folder.exists() else []
        labels = sorted(label_folder.glob("*.txt")) if label_folder.exists() else []
        image_stems = {p.stem.lower() for p in images}
        label_stems = {p.stem.lower() for p in labels}

        for p in images:
            try:
                with p.open("rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                report.setdefault("_image_hashes", {}).setdefault(digest, []).append({
                    "split": split, "file": p.name
                })
                from PIL import Image
                with Image.open(p) as im:
                    im.verify()
            except Exception as exc:
                report["corrupt_images"][split].append({"file": p.name, "reason": str(exc)})
                continue

            lp = label_folder / f"{p.stem}.txt"
            if not lp.exists():
                report["missing_labels"][split].append(p.name)
                continue

            lines = [line.strip() for line in lp.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
            if not lines:
                report["empty_labels"][split].append(lp.name)
                continue

            valid_for_image = True
            for line_no, line in enumerate(lines, 1):
                try:
                    parts = line.split()
                    if len(parts) != 5:
                        raise ValueError("expected 5 fields")
                    class_id = int(parts[0])
                    values = [float(x) for x in parts[1:]]
                    if class_id not in names:
                        raise ValueError(f"class id {class_id} out of range")
                    if any(v < 0 or v > 1 for v in values):
                        raise ValueError("bbox values out of range")
                    if values[2] <= 0 or values[3] <= 0:
                        raise ValueError("bbox width/height must be > 0")
                    x, y, w, h = values
                    if x - w / 2 < 0 or x + w / 2 > 1 or y - h / 2 < 0 or y + h / 2 > 1:
                        raise ValueError("bbox extends outside image bounds")
                    counts[class_id] += 1
                    if values[2] >= 0.98 and values[3] >= 0.98:
                        report["full_image_boxes"] += 1
                        report["full_image_box_files"].append(lp.name)
                except Exception as exc:
                    valid_for_image = False
                    report["bad_labels"].append({
                        "split": split,
                        "file": lp.name,
                        "line": line_no,
                        "reason": str(exc),
                    })
            if valid_for_image:
                report[f"{split}_labeled_images"] += 1

        for lp in labels:
            if lp.stem.lower() not in image_stems:
                report["orphan_labels"][split].append(lp.name)

        return images, counts

    train_files, train_counts = scan(train, train_labels, "train")
    val_files, val_counts = scan(val, val_labels, "val")

    report["train_images"] = len(train_files)
    report["val_images"] = len(val_files)

    image_hashes = report.pop("_image_hashes", {})
    report["duplicate_images"] = [
        entries for entries in image_hashes.values() if len(entries) > 1
    ]
    train_keys = {p.stem.lower() for p in train_files}
    val_keys = {p.stem.lower() for p in val_files}
    report["train_val_overlap"] = sorted(train_keys & val_keys)

    for class_id, name in names.items():
        report["class_counts"][name] = {
            "class_id": class_id,
            "train_objects": train_counts.get(class_id, 0),
            "val_objects": val_counts.get(class_id, 0),
        }

    if not root.exists():
        report["issues"].append(f"dataset root not found: {root}")
        alt = BASE_DIR / "dataset"
        if alt.exists():
            report["issues"].append(f"A separate dataset directory exists at {alt}; verify dataset.yaml points to the intended dataset before training.")
    if not train.exists():
        report["issues"].append(f"train image directory not found: {train}")
    if not val.exists():
        report["issues"].append(f"val image directory not found: {val}")

    if report["missing_labels"]["train"] or report["missing_labels"]["val"]:
        report["issues"].append(
            f"Missing labels: train={len(report['missing_labels']['train'])}, val={len(report['missing_labels']['val'])}"
        )
    if report["orphan_labels"]["train"] or report["orphan_labels"]["val"]:
        report["issues"].append(
            f"Orphan labels: train={len(report['orphan_labels']['train'])}, val={len(report['orphan_labels']['val'])}"
        )
    if report["empty_labels"]["train"] or report["empty_labels"]["val"]:
        report["issues"].append(
            f"Empty labels: train={len(report['empty_labels']['train'])}, val={len(report['empty_labels']['val'])}"
        )
    if report["bad_labels"]:
        report["issues"].append(f"Invalid label lines: {len(report['bad_labels'])}")
    if report["train_val_overlap"]:
        report["issues"].append(f"train/val overlap: {len(report['train_val_overlap'])} filename stem(s)")
    if len(train_files) < len(names) * 3:
        report["issues"].append("Dataset is very small for the number of classes; add more varied images before expecting strong generalization.")
    if len(val_files) < len(names):
        report["issues"].append("Validation set is smaller than the number of classes; metrics may be unstable.")

    rare = [names[i] for i in names if train_counts.get(i, 0) < 3]
    if rare:
        report["rare_classes"] = rare
        report["issues"].append(f"Classes with fewer than 3 training objects: {len(rare)}")
    if report["full_image_boxes"]:
        report["issues"].append(
            f"Full-image bounding boxes detected: {report['full_image_boxes']}; use tight boxes around the actual object when possible."
        )

    audit_path = BASE_DIR / "data" / "dataset_audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    hard_errors = (
        not root.exists()
        or not train.exists()
        or not val.exists()
        or bool(report["missing_labels"]["train"])
        or bool(report["bad_labels"])
        or bool(report["train_val_overlap"])
    )
    if fail_on_missing and hard_errors:
        raise RuntimeError(
            "Dataset audit failed. Fix the reported image/label problems before training. "
            f"Full report: {audit_path}"
        )
    return report


def main():
    print("Project:", BASE_DIR)
    if not MODEL.exists(): raise FileNotFoundError(f"ไม่พบโมเดล: {MODEL}")
    if not DATA.exists(): raise FileNotFoundError(f"ไม่พบ dataset.yaml: {DATA}")
    dataset_audit()
    model = YOLO(str(MODEL))
    model.train(
        data=str(DATA), epochs=200, imgsz=768, batch=4, workers=0,
        project=str(PROJECT), name=NAME, exist_ok=True, pretrained=True,
        patience=30, plots=True, cache=False, device=None,
        degrees=8, translate=0.08, scale=0.35, shear=1.0, perspective=0.0002,
        fliplr=0.2, mosaic=0.65, mixup=0.02, hsv_h=0.012, hsv_s=0.45, hsv_v=0.30,
        close_mosaic=15, optimizer="auto", cos_lr=True, seed=42, deterministic=True,
    )
    best = PROJECT / NAME / "weights" / "best.pt"
    print("\nTraining เสร็จแล้ว")
    print("Custom model:", best)
    if best.exists():
        print("Validation จะถูกเก็บไว้ใน:", PROJECT / NAME)
        try:
            best_model = YOLO(str(best))
            metrics = best_model.val(data=str(DATA), imgsz=768, batch=4, split="val", plots=True)
            print("mAP50:", getattr(metrics.box, "map50", None))
            print("mAP50-95:", getattr(metrics.box, "map", None))
        except Exception as exc:
            print("Validation หลัง train ไม่สำเร็จ:", exc)

if __name__ == "__main__": main()
