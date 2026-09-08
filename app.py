import json
import os
import re
import sqlite3
import threading
import traceback
import hashlib
import logging
import shutil
import struct
from datetime import datetime, timezone, timedelta
from pathlib import Path

import torch
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageStat
import yaml

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
DETAILS = BASE / "details.json"
UPLOAD_DIR = Path(os.getenv("ELECTRONICS_AI_UPLOAD_DIR", str(BASE / "uploads"))).expanduser()
DATA_DIR = Path(os.getenv("ELECTRONICS_AI_DATA_DIR", str(BASE / "data"))).expanduser()
DB_FILE = DATA_DIR / "electronics_ai.sqlite3"

# Railway/local deployment:
# The canonical production model is models/best.pt. The runs/... paths are
# retained as compatibility fallbacks for the existing project structure.
CUSTOM_MODEL_ENV = os.getenv("ELECTRONICS_AI_MODEL_PATH", "").strip()
CUSTOM_MODEL = BASE / "models" / "best.pt"
CUSTOM_MODEL_ALT = BASE / "runs" / "electronics" / "weights" / "best.pt"
CUSTOM_MODEL_ALT2 = BASE / "runs" / "detect" / "runs" / "electronics" / "weights" / "best.pt"

# CLIP is optional. It is NOT downloaded or loaded unless explicitly enabled.
PRIMARY_MODEL = os.getenv("ELECTRONICS_AI_MODEL", "openai/clip-vit-large-patch14")
FALLBACK_MODEL = os.getenv("ELECTRONICS_AI_FALLBACK", "openai/clip-vit-base-patch32")
ENABLE_CLIP_FALLBACK = os.getenv("ELECTRONICS_AI_ENABLE_CLIP_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
ALLOW_CLIP_DOWNLOAD = os.getenv("ELECTRONICS_AI_ALLOW_MODEL_DOWNLOAD", "0").strip().lower() in {"1", "true", "yes", "on"}

logger = logging.getLogger("electronics-ai")
if not logger.handlers:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = int(os.getenv("ELECTRONICS_AI_MAX_PIXELS", "40000000"))
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
TOP_K = max(3, min(10, int(os.getenv("ELECTRONICS_AI_TOP_K", "7"))))
YOLO_CONF = float(os.getenv("ELECTRONICS_AI_YOLO_CONF", "0.25"))
YOLO_MIN_ACCEPT = float(os.getenv("ELECTRONICS_AI_YOLO_MIN_ACCEPT", "0.45"))
YOLO_IMGSZ = int(os.getenv("ELECTRONICS_AI_YOLO_IMGSZ", "768"))
CLIP_MIN_SIM = float(os.getenv("ELECTRONICS_AI_CLIP_MIN_SIM", "0.20"))
CLIP_MIN_MARGIN = float(os.getenv("ELECTRONICS_AI_CLIP_MIN_MARGIN", "0.012"))
CLIP_TEMPERATURE = float(os.getenv("ELECTRONICS_AI_CLIP_TEMPERATURE", "0.03"))
CLIP_VERIFY_MIN_SIM = float(os.getenv("ELECTRONICS_AI_CLIP_VERIFY_MIN_SIM", "0.18"))
CLIP_VERIFY_MARGIN = float(os.getenv("ELECTRONICS_AI_CLIP_VERIFY_MARGIN", "0.010"))
MAX_DETECTIONS = max(1, min(50, int(os.getenv("ELECTRONICS_AI_MAX_DETECTIONS", "20"))))
DEDUP_IOU = float(os.getenv("ELECTRONICS_AI_DEDUP_IOU", "0.92"))
MEMORY_SIMILARITY = float(os.getenv("ELECTRONICS_AI_MEMORY_SIMILARITY", "0.95"))
MEMORY_MAX_RESULTS = max(1, min(20, int(os.getenv("ELECTRONICS_AI_MEMORY_MAX_RESULTS", "5"))))
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "bmp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATASET_YAML = BASE / "dataset.yaml"
LEARNING_DIR = DATA_DIR / "learning_queue"
LEARNING_IMAGE_DIR = LEARNING_DIR / "images"
LEARNING_LABEL_DIR = LEARNING_DIR / "labels"
LEARNING_MANIFEST = LEARNING_DIR / "manifest.jsonl"
LEARNING_META_DIR = LEARNING_DIR / "meta"
LEARNING_META_DIR.mkdir(parents=True, exist_ok=True)
LEARNING_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
LEARNING_LABEL_DIR.mkdir(parents=True, exist_ok=True)


def load_dataset_classes():
    """Load the exact class vocabulary used by the trained custom YOLO model."""
    if not DATASET_YAML.exists():
        return []
    try:
        cfg = yaml.safe_load(DATASET_YAML.read_text(encoding="utf-8")) or {}
        names = cfg.get("names", {}) or {}
        if isinstance(names, list):
            return [str(x) for x in names]
        return [str(names[k]) for k in sorted(names, key=lambda x: int(x))]
    except Exception:
        return []


CLASSES = load_dataset_classes()
if not CLASSES:
    raise RuntimeError(f"Cannot load class names from {DATASET_YAML}")


PROMPTS = {
    "Arduino UNO": ["Arduino UNO R3 development board", "Arduino UNO microcontroller board", "Arduino UNO board"],
    "Arduino Nano": ["Arduino Nano development board", "Arduino Nano microcontroller board", "Arduino Nano"],
    "Arduino Mega": ["Arduino Mega 2560 development board", "Arduino Mega microcontroller board", "Arduino Mega"],
    "ESP32 development board": ["ESP32 development board", "ESP32 WiFi Bluetooth microcontroller board", "ESP32 board"],
    "ESP8266 development board": ["ESP8266 NodeMCU development board", "ESP8266 WiFi microcontroller board", "ESP8266 board"],
    "Raspberry Pi single board computer": ["Raspberry Pi single board computer", "Raspberry Pi board", "Raspberry Pi computer"],
    "breadboard": ["solderless breadboard", "electronic prototyping breadboard", "white solderless breadboard"],
    "breadboard power supply module": ["breadboard power supply module", "MB102 breadboard power supply", "breadboard 5V 3.3V power module"],
    "resistor": ["electronic resistor component", "resistor with colored bands", "through hole resistor"],
    "potentiometer": ["potentiometer variable resistor", "rotary potentiometer", "variable resistor knob"],
    "thermistor": ["thermistor electronic component", "temperature dependent resistor", "thermistor"],
    "photoresistor LDR": ["LDR photoresistor", "light dependent resistor", "photoresistor component"],
    "capacitor": ["electronic capacitor component", "non polarized capacitor", "capacitor component"],
    "electrolytic capacitor": ["electrolytic capacitor", "polarized capacitor", "aluminum electrolytic capacitor"],
    "ceramic capacitor": ["ceramic capacitor", "ceramic disc capacitor", "ceramic electronic capacitor"],
    "diode": ["electronic diode component", "rectifier diode", "semiconductor diode"],
    "LED": ["LED light emitting diode", "single LED component", "LED electronic component"],
    "RGB LED": ["RGB LED component", "red green blue LED", "RGB light emitting diode"],
    "7 segment display": ["seven segment display", "7 segment LED display", "numeric seven segment display"],
    "LCD display": ["LCD display module", "character LCD electronic display", "liquid crystal display module"],
    "OLED display": ["OLED display module", "small OLED electronic display", "OLED screen module"],
    "relay module": ["electronic relay module", "relay board module", "electromechanical relay module"],
    "transistor": ["transistor electronic component", "BJT transistor", "semiconductor transistor"],
    "MOSFET": ["MOSFET transistor", "power MOSFET electronic component", "MOSFET semiconductor"],
    "voltage regulator": ["voltage regulator electronic component", "linear voltage regulator", "voltage regulator module"],
    "buck converter": ["DC DC buck converter module", "step down voltage converter", "buck converter board"],
    "boost converter": ["DC DC boost converter module", "step up voltage converter", "boost converter board"],
    "DC motor": ["small DC motor", "brushed DC electric motor", "DC motor component"],
    "servo motor": ["RC servo motor", "servo motor actuator", "hobby servo motor"],
    "stepper motor": ["stepper motor", "stepper electric motor", "stepper motor actuator"],
    "buzzer": ["electronic buzzer", "piezo buzzer", "buzzer component"], "speaker": ["small electronic speaker", "loudspeaker component", "speaker"],
    "microphone": ["electret microphone component", "microphone module", "electronic microphone"], "push button": ["electronic push button switch", "tactile push button", "momentary push button"],
    "switch": ["electronic switch", "toggle switch", "electrical switch component"], "rotary encoder": ["rotary encoder module", "electronic rotary encoder", "rotary encoder knob"],
    "joystick module": ["analog joystick module", "electronic joystick module", "two axis joystick module"], "IR receiver": ["infrared IR receiver module", "IR remote receiver", "infrared receiver component"],
    "ultrasonic sensor": ["ultrasonic distance sensor module", "HC-SR04 ultrasonic sensor", "ultrasonic sensor board"], "PIR motion sensor": ["PIR motion sensor module", "passive infrared motion sensor", "PIR sensor board"],
    "temperature sensor": ["electronic temperature sensor", "temperature sensor module", "digital temperature sensor"], "humidity sensor": ["humidity sensor module", "electronic humidity sensor", "temperature humidity sensor"],
    "light sensor": ["electronic light sensor module", "ambient light sensor", "light sensor board"], "gas sensor": ["gas sensor module", "electronic gas detection sensor", "MQ gas sensor"],
    "soil moisture sensor": ["soil moisture sensor module", "soil humidity sensor", "soil moisture probe"], "accelerometer": ["electronic accelerometer sensor", "accelerometer module", "motion accelerometer"],
    "gyroscope sensor": ["electronic gyroscope sensor", "gyroscope module", "gyro sensor board"], "RFID reader": ["RFID reader module", "RFID card reader", "RFID antenna reader board"],
    "RFID card": ["RFID card tag", "contactless RFID card", "RFID access card"], "GPS module": ["GPS receiver module", "GPS electronic module", "GPS board"],
    "Bluetooth module": ["Bluetooth wireless module", "Bluetooth serial module", "Bluetooth electronics board"], "WiFi module": ["WiFi wireless module", "WiFi electronics module", "WiFi development module"],
    "LoRa module": ["LoRa wireless module", "LoRa radio module", "LoRa electronics board"], "camera module": ["camera module board", "small electronic camera module", "camera sensor module"],
    "logic level converter": ["logic level converter module", "bidirectional level shifter", "logic voltage converter"], "motor driver module": ["motor driver module", "DC motor controller board", "H bridge motor driver"],
    "USB to serial adapter": ["USB to serial converter", "USB UART adapter", "USB serial electronics module"], "battery holder": ["battery holder", "battery case holder", "battery compartment"],
    "battery": ["electrical battery", "rechargeable battery", "battery cell"], "power supply adapter": ["AC DC power adapter", "electronic power supply adapter", "wall power adapter"],
    "charger": ["battery charger", "electronic charger", "USB charger"], "multimeter": ["digital multimeter", "electrical multimeter", "electronic test meter"],
    "oscilloscope": ["digital oscilloscope", "electronic oscilloscope", "oscilloscope test instrument"], "soldering iron": ["soldering iron", "electronic soldering tool", "electric soldering iron"],
    "jumper wires": ["Dupont jumper wires", "electronic jumper wires", "breadboard jumper cables"], "alligator clip": ["alligator clip test lead", "electronic crocodile clip", "alligator electrical clip"],
    "PCB": ["printed circuit board PCB", "electronic circuit board", "PCB board"], "integrated circuit IC chip": ["integrated circuit IC chip", "electronic IC chip", "semiconductor integrated circuit"],
    "DIP socket": ["DIP IC socket", "dual inline package socket", "IC socket"], "crystal oscillator": ["quartz crystal oscillator", "electronic crystal component", "crystal resonator"],
    "terminal block": ["electrical terminal block", "PCB screw terminal", "terminal connector"], "header pins": ["male header pins", "PCB header connector", "pin header"],
    "fuse": ["electrical fuse component", "glass fuse", "electronic fuse"], "transformer": ["electrical transformer", "power transformer", "transformer component"], "inductor": ["electronic inductor", "coil inductor component", "inductor coil"],
    "antenna": ["electronic antenna", "RF antenna", "wireless antenna"], "router": ["WiFi router", "wireless network router", "home router"], "network switch": ["Ethernet network switch", "network switch device", "LAN switch"],
    "webcam": ["USB webcam", "computer webcam", "web camera"], "computer monitor": ["computer monitor", "LCD computer monitor", "desktop display monitor"], "smartphone": ["smartphone", "mobile phone", "smart phone device"]
}

# Dataset names used by the current trained model -> canonical names used by the knowledge base.
YOLO_ALIASES = {
    "Arduino_UNO_R3":"Arduino UNO", "Arduino_Nano":"Arduino Nano", "Arduino_Mega_2560":"Arduino Mega",
    "ESP32_DevKit":"ESP32 development board", "ESP8266_NodeMCU":"ESP8266 development board", "Raspberry_Pi_4":"Raspberry Pi single board computer",
    "Raspberry_Pi_Pico":"Raspberry Pi single board computer", "Breadboard":"breadboard", "Breadboard_Power_Supply":"breadboard power supply module",
    "Resistor":"resistor", "Potentiometer":"potentiometer", "Electrolytic_Capacitor":"electrolytic capacitor", "LED":"LED",
    "Diode_1N4007":"diode", "Transistor":"transistor", "Relay_Module_1_Channel":"relay module", "Relay_Module_4_Channel":"relay module",
    "LCD_16x2":"LCD display", "LCD_20x4":"LCD display", "OLED_I2C":"OLED display", "TFT_LCD":"LCD display", "TM1637_7Segment":"7 segment display",
    "MAX7219_LED_Matrix":"LED matrix", "DC_Gear_Motor":"DC motor", "SG90_Servo_Motor":"servo motor", "NEMA17_Stepper_Motor":"stepper motor", "Stepper_28BYJ48":"stepper motor",
    "Buzzer":"buzzer", "Push_Button":"push button", "Joystick_Module":"joystick module", "IR_Obstacle_Sensor":"IR receiver", "HC_SR04":"ultrasonic sensor",
    "PIR_Motion_Sensor":"PIR motion sensor", "DHT11":"temperature sensor", "DHT22":"temperature sensor", "BMP280":"temperature sensor", "Rain_Sensor_Module":"rain sensor" if False else "humidity sensor",
    "MQ2_Gas_Sensor":"gas sensor", "Soil_Moisture_Sensor":"soil moisture sensor", "MPU6050":"accelerometer", "Color_Sensor_TCS3200":"color sensor",
    "RFID_RC522":"RFID reader", "GPS_NEO6M":"GPS module", "HC05_Bluetooth_Module":"Bluetooth module", "SIM800L_GSM_Module":"GSM module", "LoRa_RA02":"LoRa module",
    "ESP32_CAM":"camera module", "L298N_Motor_Driver":"motor driver module", "L293D_Motor_Driver":"motor driver module", "TP4056_Battery_Charger":"charger",
    "18650_Lithium_Battery":"battery", "9V_Battery":"battery", "Multimeter":"multimeter", "Oscilloscope":"oscilloscope", "Soldering_Iron":"soldering iron", "Jumper_Wires":"jumper wires",
    "555_Timer_IC":"integrated circuit IC chip", "Fingerprint_Sensor":"fingerprint sensor", "Sound_Sensor_Module":"sound sensor module", "TFT_LCD":"LCD display"
}

try:
    DETAILS_DB = json.loads(DETAILS.read_text(encoding="utf-8"))
except Exception as exc:
    raise RuntimeError(f"Cannot read details.json: {exc}") from exc


def canonical_name(name):
    return YOLO_ALIASES.get(str(name), str(name))


def class_display_name(name):
    """Human-friendly fallback label without changing the model's class identity."""
    return str(name).replace("_", " ").strip()


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1e-9, area_a + area_b - inter)


def deduplicate_detections(detections):
    """Remove repeated boxes for the same canonical class after model inference."""
    kept = []
    for det in sorted(detections, key=lambda x: x.get("score", 0.0), reverse=True):
        duplicate = any(
            canonical_name(det.get("name")) == canonical_name(old.get("name"))
            and iou_xyxy(det.get("box", [0, 0, 0, 0]), old.get("box", [0, 0, 0, 0])) >= DEDUP_IOU
            for old in kept
        )
        if not duplicate:
            kept.append(det)
    return kept


def detail_for(name):
    key = canonical_name(name)
    return DETAILS_DB.get(key, DETAILS_DB.get(name, DETAILS_DB.get("default", {})))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_conn():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, filename TEXT NOT NULL,
            image_path TEXT NOT NULL, result_name TEXT NOT NULL, result_name_th TEXT NOT NULL,
            confidence REAL NOT NULL, confidence_kind TEXT NOT NULL, level TEXT NOT NULL,
            engine TEXT NOT NULL, quality_json TEXT NOT NULL, detections_json TEXT NOT NULL,
            analysis_json TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analyses_name ON analyses(result_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analyses_level ON analyses(level)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analyses_engine ON analyses(engine)")
        c.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            corrected_label TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(analysis_id),
            FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_feedback_analysis ON feedback(analysis_id)")
        c.execute("""CREATE TABLE IF NOT EXISTS learned_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id TEXT,
            image_sha256 TEXT NOT NULL,
            image_dhash TEXT NOT NULL,
            label TEXT NOT NULL,
            raw_label TEXT,
            source TEXT NOT NULL,
            image_path TEXT,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            use_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(image_sha256, label)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_memory_sha ON learned_memory(image_sha256)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_memory_label ON learned_memory(label)")
        c.execute("""CREATE TABLE IF NOT EXISTS learning_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            raw_label TEXT NOT NULL,
            class_id INTEGER NOT NULL,
            image_path TEXT NOT NULL,
            label_path TEXT,
            metadata_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requires_annotation INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_learning_status ON learning_queue(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_learning_label ON learning_queue(label)")
        mem_existing={row[1] for row in c.execute("PRAGMA table_info(learned_memory)")}
        if "embedding" not in mem_existing: c.execute("ALTER TABLE learned_memory ADD COLUMN embedding BLOB")
        if "embedding_dim" not in mem_existing: c.execute("ALTER TABLE learned_memory ADD COLUMN embedding_dim INTEGER")
        existing={row[1] for row in c.execute("PRAGMA table_info(analyses)")}
        for name, ddl in {
            "object_count":"INTEGER NOT NULL DEFAULT 0", "processing_time_ms":"INTEGER", "model_version":"TEXT", "dataset_version":"TEXT"
        }.items():
            if name not in existing: c.execute(f"ALTER TABLE analyses ADD COLUMN {name} {ddl}")



def image_sha256(image):
    """Stable content hash for exact-image memory lookup."""
    buf = image.copy()
    buf.thumbnail((1600, 1600))
    import io
    out = io.BytesIO()
    buf.save(out, format="JPEG", quality=95, optimize=True)
    return hashlib.sha256(out.getvalue()).hexdigest()


def image_dhash(image, size=8):
    """64-bit perceptual hash; robust to small resize/compression changes."""
    gray = ImageOps.grayscale(image).resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(gray.getdata())
    bits = 0
    for y in range(size):
        row = y * (size + 1)
        for x in range(size):
            bits = (bits << 1) | int(px[row + x] > px[row + x + 1])
    return f"{bits:016x}"


def hash_similarity(a, b):
    try:
        x, y = int(str(a), 16), int(str(b), 16)
        return 1.0 - ((x ^ y).bit_count() / 64.0)
    except Exception:
        return 0.0


def normalize_label_text(value):
    return re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())


def resolve_label(value):
    """Resolve user feedback to a real dataset/model class without inventing classes."""
    q = normalize_label_text(value)
    if not q or q in {"unknown", "ไม่ทราบ", "ไม่รู้"}:
        return None
    # Exact raw/canonical/Thai display matches first.
    for raw in CLASSES:
        d = detail_for(raw)
        candidates = [raw, canonical_name(raw), d.get("name_th", "")]
        if any(normalize_label_text(x) == q for x in candidates):
            return {"raw": raw, "canonical": canonical_name(raw), "name_th": d.get("name_th", class_display_name(raw))}
    # Then allow a unique substring match for convenient typing.
    matches=[]
    for raw in CLASSES:
        d=detail_for(raw)
        vals=[normalize_label_text(raw), normalize_label_text(canonical_name(raw)), normalize_label_text(d.get("name_th", ""))]
        if any(q in x or x in q for x in vals if x):
            matches.append(raw)
    if len(matches)==1:
        raw=matches[0]; d=detail_for(raw)
        return {"raw": raw, "canonical": canonical_name(raw), "name_th": d.get("name_th", class_display_name(raw))}
    return None


def _pack_embedding(vec):
    """Store a normalized float32 vector compactly in SQLite."""
    if vec is None:
        return None, None
    try:
        values=[float(x) for x in vec]
        if not values:
            return None, None
        return sqlite3.Binary(struct.pack(f"<{len(values)}f", *values)), len(values)
    except Exception:
        return None, None


def _unpack_embedding(blob, dim):
    if not blob or not dim:
        return None
    try:
        return list(struct.unpack(f"<{int(dim)}f", blob))
    except Exception:
        return None


def cosine_similarity(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot=sum(x*y for x,y in zip(a,b))
    na=sum(x*x for x in a) ** 0.5
    nb=sum(y*y for y in b) ** 0.5
    return dot / max(1e-12, na*nb)


def remember_example(image_path, image, label, analysis_id=None, source="feedback", embedding=None):
    """Store a confirmed example immediately in the safe online-memory layer."""
    resolved = resolve_label(label) if isinstance(label, str) else label
    if not resolved:
        raise ValueError("ไม่พบชื่ออุปกรณ์ในคลาสของโมเดล")
    sha=image_sha256(image); dh=image_dhash(image); created=now_iso()
    rel_path=None
    if image_path:
        try: rel_path=str(Path(image_path).resolve().relative_to(BASE.resolve()))
        except Exception: rel_path=str(image_path)
    packed, dim=_pack_embedding(embedding)
    with db_conn() as c:
        # Exact image has one authoritative label. A correction replaces the previous memory.
        c.execute("DELETE FROM learned_memory WHERE image_sha256=?", (sha,))
        c.execute("""INSERT INTO learned_memory
            (analysis_id,image_sha256,image_dhash,label,raw_label,source,image_path,created_at,embedding,embedding_dim)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (analysis_id,sha,dh,resolved["canonical"],resolved["raw"],source,rel_path,created,packed,dim))
    return resolved, sha, dh


def find_memory(image, embedding=None):
    """Exact memory is authoritative; visual similarity is only a hint."""
    sha=image_sha256(image); dh=image_dhash(image)
    with db_conn() as c:
        exact=c.execute("SELECT * FROM learned_memory WHERE image_sha256=? ORDER BY created_at DESC LIMIT 1",(sha,)).fetchone()
        if exact:
            c.execute("UPDATE learned_memory SET last_used_at=?,use_count=use_count+1 WHERE id=?",(now_iso(),exact["id"]))
            return {"match":"exact","similarity":1.0,"row":dict(exact)}
        rows=c.execute("SELECT * FROM learned_memory ORDER BY created_at DESC LIMIT 5000").fetchall()
    best=None
    for row in rows:
        visual=0.0
        stored=_unpack_embedding(row["embedding"], row["embedding_dim"]) if "embedding" in row.keys() else None
        if embedding and stored:
            visual=cosine_similarity(embedding, stored)
        else:
            visual=hash_similarity(dh,row["image_dhash"])
        if visual >= MEMORY_SIMILARITY and (best is None or visual > best["similarity"]):
            best={"match":"similar","similarity":visual,"row":dict(row)}
    if best:
        with db_conn() as c:
            c.execute("UPDATE learned_memory SET last_used_at=?,use_count=use_count+1 WHERE id=?",(now_iso(),best["row"]["id"]))
    return best


def make_memory_result(memory):
    row=memory["row"]; label=row["label"]; d=detail_for(label)
    return {
        "engine":"learned-memory", "detector_path":None, "detections":[],
        "top":(label, 0.995 if memory["match"]=="exact" else min(0.99, memory["similarity"])),
        "candidates": [(label, 0.995 if memory["match"]=="exact" else memory["similarity"])],
        "raw_top":0.995 if memory["match"]=="exact" else memory["similarity"],
        "raw_margin":1.0, "is_unknown":False, "memory":{
            "match":memory["match"], "similarity":round(memory["similarity"],4),
            "source":row.get("source"), "analysis_id":row.get("analysis_id")
        }
    }


def queue_learning_sample(image_path, image, resolved, analysis_id, detections=None):
    """Create an idempotent, reviewable learning sample.

    A YOLO label is created only when there is exactly one trustworthy source box.
    Otherwise the sample is kept as an annotation-required item, preventing bogus
    full-image boxes from poisoning the detector during later training.
    """
    stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    out_img=LEARNING_IMAGE_DIR/f"{stamp}_{analysis_id}.jpg"
    out_lbl=LEARNING_LABEL_DIR/f"{out_img.stem}.txt"
    meta_path=LEARNING_META_DIR/f"{analysis_id}.json"
    existing=None
    with db_conn() as c:
        existing=c.execute("SELECT * FROM learning_queue WHERE analysis_id=?",(analysis_id,)).fetchone()
    if existing:
        out_img=BASE/existing["image_path"]
        out_lbl=BASE/existing["label_path"] if existing["label_path"] else out_lbl
        meta_path=BASE/existing["metadata_path"]
    else:
        image.convert("RGB").save(out_img,format="JPEG",quality=95)

    detections=detections or []
    usable=[d for d in detections if d.get("box") and d.get("score",0)>=YOLO_MIN_ACCEPT]
    label_path=None
    requires_annotation=True
    bbox=None
    if len(usable)==1:
        bbox=usable[0]["box"]
        x1,y1,x2,y2=[float(v) for v in bbox]
        w,h=image.size
        xc=((x1+x2)/2)/max(1,w); yc=((y1+y2)/2)/max(1,h)
        bw=max(0.0,min(1.0,(x2-x1)/max(1,w))); bh=max(0.0,min(1.0,(y2-y1)/max(1,h)))
        class_id=CLASSES.index(resolved["raw"])
        out_lbl.parent.mkdir(parents=True,exist_ok=True)
        out_lbl.write_text(f"{class_id} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n",encoding="utf-8")
        label_path=str(out_lbl.relative_to(BASE)); requires_annotation=False
    else:
        class_id=CLASSES.index(resolved["raw"])
        if out_lbl.exists(): out_lbl.unlink()

    meta={
        "created_at":now_iso(),"analysis_id":analysis_id,"label":resolved["canonical"],
        "raw_label":resolved["raw"],"class_id":class_id,"image":str(out_img.relative_to(BASE)),
        "label_file":label_path,"source_image":str(Path(image_path).relative_to(BASE)) if image_path else None,
        "requires_annotation":requires_annotation,"source_box":bbox,
        "instruction":"Review before model training. Samples without label_file require manual bounding-box annotation."
    }
    meta_path.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    entry={**meta,"updated_at":now_iso()}
    with db_conn() as c:
        if existing:
            c.execute("""UPDATE learning_queue SET label=?,raw_label=?,class_id=?,image_path=?,label_path=?,metadata_path=?,status='pending',requires_annotation=?,updated_at=? WHERE analysis_id=?""",
                (resolved["canonical"],resolved["raw"],class_id,str(out_img.relative_to(BASE)),label_path,str(meta_path.relative_to(BASE)),1 if requires_annotation else 0,now_iso(),analysis_id))
        else:
            c.execute("""INSERT INTO learning_queue(analysis_id,label,raw_label,class_id,image_path,label_path,metadata_path,status,requires_annotation,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (analysis_id,resolved["canonical"],resolved["raw"],class_id,str(out_img.relative_to(BASE)),label_path,str(meta_path.relative_to(BASE)),"pending",1 if requires_annotation else 0,now_iso(),now_iso()))
    # Keep a compact append-only manifest for external training tools.
    with LEARNING_MANIFEST.open("a",encoding="utf-8") as f:
        f.write(json.dumps(entry,ensure_ascii=False)+"\n")
    return {"analysis_id":analysis_id,"image":meta["image"],"label_file":label_path,"metadata_file":str(meta_path.relative_to(BASE)),"requires_annotation":requires_annotation,"status":"pending"}

def quality_check(image):
    """Non-blocking image quality analysis. Warnings guide the user but do not reject a valid image."""
    w, h = image.size
    gray = ImageOps.grayscale(image).resize((min(512, w), min(512, h)))
    stat = ImageStat.Stat(gray)
    brightness = float(stat.mean[0])
    contrast = float(stat.stddev[0])
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_std = float(ImageStat.Stat(edges).stddev[0])
    warnings, tips = [], []
    aspect = round(w / max(1, h), 3)
    pixels = w * h
    if w < 320 or h < 240:
        warnings.append("ความละเอียดต่ำ")
        tips.append("ถ่ายภาพให้มีความละเอียดอย่างน้อย 320×240 และควรเห็นรายละเอียดของอุปกรณ์ชัดเจน")
    if brightness < 45:
        warnings.append("ภาพมืดเกินไป")
        tips.append("เพิ่มแสงและหลีกเลี่ยงเงาทับบนอุปกรณ์")
    elif brightness > 225:
        warnings.append("ภาพสว่างเกินไป")
        tips.append("ลดแสงสะท้อนและหลีกเลี่ยงการถ่ายย้อนแสง")
    if contrast < 18:
        warnings.append("คอนทราสต์ต่ำ")
        tips.append("จัดแสงให้ตัวอุปกรณ์แยกจากพื้นหลังได้ชัด")
    if edge_std < 7.0:
        warnings.append("ภาพอาจเบลอ หรือมีรายละเอียดน้อย")
        tips.append("ถือกล้องให้นิ่งและโฟกัสที่ตัวอุปกรณ์")
    if pixels < 76800 and "ความละเอียดต่ำ" not in warnings:
        warnings.append("จำนวนพิกเซลค่อนข้างต่ำ")
        tips.append("ใช้กล้องความละเอียดสูงขึ้นเพื่อช่วยให้ AI เห็นรายละเอียดของขาและตัวอักษร")
    severity = "good" if not warnings else ("warning" if len(warnings) <= 2 else "poor")
    return {
        "ok": not warnings, "status": severity, "width": w, "height": h, "aspect_ratio": aspect,
        "pixels": pixels, "brightness": round(brightness, 1), "contrast": round(contrast, 1),
        "sharpness_indicator": round(edge_std, 2), "warnings": warnings, "tips": list(dict.fromkeys(tips))
    }

def quality_for_storage(q):
    return {k: v for k, v in q.items() if k not in {"tips"}}


def quality_is_severe(q):
    warnings = set(q.get("warnings", []))
    return (
        q.get("width", 0) < 240 or q.get("height", 0) < 180
        or q.get("brightness", 128) < 25 or q.get("brightness", 128) > 245
        or q.get("sharpness_indicator", 10) < 3.5
    )


def level_for_yolo(score):
    if score >= 0.90: return "High Confidence"
    if score >= 0.70: return "Medium Confidence"
    return "Needs Review"


def level_for_clip(margin, similarity):
    if similarity < CLIP_MIN_SIM or margin < CLIP_MIN_MARGIN: return "Needs Review"
    if margin >= 0.025 and similarity >= 0.24: return "High Confidence"
    return "Medium Confidence"


def circuit_analysis(detections):
    """Explain possible component relationships without claiming to electrically verify the circuit."""
    names = [canonical_name(d.get("name")) for d in detections if d.get("name")]
    unique = list(dict.fromkeys(names))
    normalized = {n.lower() for n in unique}
    notes, relationships, possible = [], [], []
    def has(*words): return any(any(w.lower() in n for n in normalized) for w in words)
    if has("arduino") and has("led"):
        possible.append("วงจรควบคุม LED ด้วยไมโครคอนโทรลเลอร์")
        relationships.append("Arduino + LED → อาจเป็นวงจรควบคุมไฟหรือการทดลอง Digital Output")
    if has("arduino") and has("hc-sr04", "ultrasonic"):
        possible.append("ระบบวัดระยะทาง")
        relationships.append("Arduino + Ultrasonic Sensor → อาจเป็นระบบตรวจวัดระยะ")
    if has("esp32") and has("dht"):
        possible.append("ระบบวัดอุณหภูมิและความชื้นแบบ IoT")
        relationships.append("ESP32 + DHT Sensor → อาจเป็นระบบอ่านค่าพร้อมส่งข้อมูลผ่านเครือข่าย")
    if has("arduino", "esp32", "esp8266") and has("relay"):
        possible.append("ระบบควบคุมโหลดผ่าน Relay")
        relationships.append("Microcontroller + Relay → อาจเป็นระบบสั่งเปิด/ปิดโหลด")
    if has("esp32", "arduino") and has("oled", "display", "lcd"):
        possible.append("ระบบแสดงผลข้อมูลจากเซนเซอร์")
        relationships.append("Microcontroller + Display → อาจใช้แสดงข้อมูลหรือสถานะของระบบ")
    if has("led") and not has("resistor"):
        notes.append({"level":"check","text":"พบ LED แต่ไม่พบ resistor ในผลตรวจจับ — ควรตรวจสอบว่ามีตัวต้านทานจำกัดกระแสหรือไม่"})
    if has("motor", "servo", "stepper") and not has("driver", "l298", "motor driver"):
        notes.append({"level":"check","text":"พบมอเตอร์โดยไม่พบวงจรขับที่ชัดเจน — ควรตรวจสอบ motor driver และกระแสของแหล่งจ่าย"})
    if has("arduino", "esp32", "esp8266"):
        notes.append({"level":"info","text":"พบไมโครคอนโทรลเลอร์บอร์ด ควรตรวจสอบ VCC/GND ระดับแรงดันและขาร่วมก่อนจ่ายไฟ"})
    if not possible:
        notes.append({"level":"info","text":"ยังไม่มีหลักฐานจากภาพเพียงพอสำหรับระบุรูปแบบวงจรที่เฉพาะเจาะจง"})
    return {
        "component_count": len(detections), "unique_components": unique,
        "possible_connections": relationships, "possible_circuits": possible,
        "notes": notes,
        "disclaimer": "ผลการวิเคราะห์เป็นการประเมินจากภาพ ไม่ใช่การตรวจสอบวงจรไฟฟ้าโดยตรง และไม่ควรใช้ยืนยันการต่อวงจรหรือความปลอดภัยเพียงอย่างเดียว"
    }


class AIEngine:
    """
    AI runtime.

    Production policy:
      1. Custom YOLO is the primary/authoritative model.
      2. If YOLO loads successfully, CLIP is never loaded.
      3. CLIP is an explicit opt-in fallback only when YOLO is unavailable.
      4. All model-path/load failures are logged with the real exception.
    """

    def __init__(self):
        self.model = None
        self.processor = None
        self.model_name = None
        self.text_features = None
        self.class_prompts = None

        self.detector = None
        self.detector_path = None

        self.lock = threading.Lock()
        self.loading = False
        self.error = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    @property
    def ready(self):
        # For this deployment, "ready" means the custom YOLO detector is ready.
        # CLIP-only fallback is deliberately not treated as the primary AI.
        return self.detector is not None

    def _model_candidates(self):
        candidates = []

        if CUSTOM_MODEL_ENV:
            env_path = Path(CUSTOM_MODEL_ENV).expanduser()
            if not env_path.is_absolute():
                env_path = BASE / env_path
            candidates.append(env_path)

        # Canonical production path first.
        candidates.extend([
            CUSTOM_MODEL,
            CUSTOM_MODEL_ALT,
            CUSTOM_MODEL_ALT2,
        ])

        # Also support an absolute /app path when the app is mounted there.
        candidates.append(Path("/app/models/best.pt"))

        # Remove duplicates while preserving order.
        unique = []
        seen = set()
        for candidate in candidates:
            try:
                key = str(candidate.resolve())
            except Exception:
                key = str(candidate)
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique

    def load_detector(self):
        logger.info("==================================================")
        logger.info("Searching for custom YOLO model...")
        logger.info("BASE directory: %s", BASE)
        logger.info("Python executable: %s", os.sys.executable)
        logger.info("Torch version: %s", getattr(torch, "__version__", "unknown"))
        logger.info("Device: %s", self.device)

        if YOLO is None:
            self.error = (
                "Ultralytics YOLO could not be imported. "
                "Check the ultralytics/torch installation in Railway."
            )
            logger.error("ULTRALYTICS IMPORT FAILED: YOLO is None")
            return False

        logger.info("Ultralytics import: SUCCESS")

        candidates = self._model_candidates()
        found_any = False
        errors = []

        for candidate in candidates:
            logger.info("Checking: %s", candidate)

            if not candidate.exists():
                logger.info("  -> NOT FOUND")
                continue

            if not candidate.is_file():
                logger.error("  -> EXISTS BUT IS NOT A FILE")
                errors.append(f"{candidate}: not a file")
                continue

            found_any = True
            try:
                size_mb = candidate.stat().st_size / (1024 * 1024)
                logger.info("  -> FOUND (%.2f MB)", size_mb)

                if candidate.stat().st_size < 1024 * 1024:
                    logger.warning("  -> Model file is unusually small; attempting load anyway.")

                logger.info("Loading YOLO model: %s", candidate)
                detector = YOLO(str(candidate))

                # Force the model to CPU when Railway has no GPU. This makes the
                # intended runtime explicit and avoids accidental CUDA assumptions.
                if self.device == "cpu":
                    try:
                        detector.to("cpu")
                    except Exception:
                        # Some Ultralytics versions do not expose .to() on the wrapper
                        # in exactly the same way; inference will still default to CPU.
                        pass

                self.detector = detector
                self.detector_path = candidate.resolve()
                self.error = None

                logger.info("SUCCESS: Custom YOLO model loaded")
                logger.info("Model path: %s", self.detector_path)
                logger.info("Model classes: %s", getattr(detector, "names", "unknown"))
                logger.info("==================================================")
                return True

            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                errors.append(f"{candidate}: {message}")
                logger.exception("FAILED to load YOLO model: %s", candidate)

        if not found_any:
            self.error = (
                "Custom YOLO model file was not found. "
                "Checked: " + "; ".join(str(x) for x in candidates)
            )
            logger.error("NO CUSTOM YOLO MODEL FOUND")
        else:
            self.error = "Custom YOLO model was found but could not be loaded: " + " | ".join(errors)
            logger.error("CUSTOM YOLO LOAD FAILED: %s", self.error)

        logger.info("==================================================")
        return False

    def load_clip_fallback(self):
        """
        Optional CLIP fallback. This function is never called when YOLO is ready.
        It is disabled by default to avoid Hugging Face downloads/RAM usage.
        """
        if not ENABLE_CLIP_FALLBACK:
            logger.info("CLIP fallback: DISABLED (ELECTRONICS_AI_ENABLE_CLIP_FALLBACK=0)")
            return False

        logger.info("CLIP fallback: ENABLED")
        logger.info("CLIP model download allowed: %s", ALLOW_CLIP_DOWNLOAD)

        try:
            from transformers import CLIPModel, CLIPProcessor
        except Exception as exc:
            logger.exception("Transformers/CLIP import failed")
            if self.detector is None:
                self.error = f"CLIP fallback import failed: {type(exc).__name__}: {exc}"
            return False

        last = None
        local_files_only = not ALLOW_CLIP_DOWNLOAD

        for name in (PRIMARY_MODEL, FALLBACK_MODEL):
            try:
                logger.info("Loading optional CLIP model: %s", name)
                logger.info("local_files_only=%s", local_files_only)

                proc = CLIPProcessor.from_pretrained(
                    name,
                    local_files_only=local_files_only,
                )
                model = CLIPModel.from_pretrained(
                    name,
                    local_files_only=local_files_only,
                ).to(self.device)
                model.eval()

                self.processor = proc
                self.model = model
                self.model_name = name
                self.prepare_text_features()

                logger.info("SUCCESS: Optional CLIP model loaded: %s", name)
                return True

            except Exception as exc:
                last = exc
                logger.exception("Optional CLIP load failed: %s", name)

        if self.detector is None and last is not None:
            self.error = f"Optional CLIP fallback failed: {type(last).__name__}: {last}"
        return False

    def load(self):
        if self.loading:
            return

        if self.detector is not None:
            return

        self.loading = True
        self.error = None

        try:
            # IMPORTANT: YOLO is always attempted first.
            yolo_ok = self.load_detector()

            # If YOLO works, STOP. Do not initialize/download CLIP.
            if yolo_ok:
                logger.info("Custom YOLO is ready; CLIP will NOT be loaded.")
                return

            # YOLO failed. CLIP is still optional and disabled by default.
            self.load_clip_fallback()

            if self.detector is None and self.model is None:
                if not self.error:
                    self.error = "No AI model is available."
                logger.error("AI initialization failed: %s", self.error)

        except Exception as exc:
            self.error = f"AI initialization failed: {type(exc).__name__}: {exc}"
            logger.exception("AI initialization crashed")

        finally:
            self.loading = False
            logger.info(
                "AI initialization finished | ready=%s | detector=%s | clip=%s | error=%s",
                self.ready,
                self.detector_path,
                self.model_name,
                self.error,
            )

    def prepare_text_features(self):
        prompts, owners = [], []
        for cls in CLASSES:
            variants = PROMPTS.get(cls, [class_display_name(cls)])
            for p in variants:
                prompts.extend([
                    f"a photo of {p}",
                    f"a clear product photo of {p}",
                    f"a real electronic device: {p}",
                ])
                owners.extend([cls] * 3)

        with torch.inference_mode():
            inp = self.processor(text=prompts, return_tensors="pt", padding=True)
            inp = {k: v.to(self.device) for k, v in inp.items()}
            feat = self.model.get_text_features(**inp)
            feat = feat / feat.norm(dim=-1, keepdim=True).clamp_min(1e-12)

        self.text_features = feat
        self.class_prompts = owners

    def image_embedding(self, image):
        """Return a normalized CLIP image embedding when optional CLIP is available."""
        if self.model is None or self.processor is None:
            return None
        with torch.inference_mode():
            inp = self.processor(images=image, return_tensors="pt")
            inp = {k: v.to(self.device) for k, v in inp.items()}
            feat = self.model.get_image_features(**inp)
            feat = feat / feat.norm(dim=-1, keepdim=True).clamp_min(1e-12)
            return feat[0].detach().float().cpu().tolist()

    @staticmethod
    def views(image):
        base = ImageOps.contain(image, (768, 768))
        enhanced = ImageEnhance.Contrast(base).enhance(1.06)
        sharpened = ImageEnhance.Sharpness(base).enhance(1.10)
        return [base, enhanced, sharpened]

    def yolo_analyze(self, image):
        if self.detector is None:
            return None

        results = self.detector.predict(
            source=image,
            conf=YOLO_CONF,
            imgsz=YOLO_IMGSZ,
            iou=0.50,
            max_det=MAX_DETECTIONS,
            augment=True,
            verbose=False,
            device="cpu" if self.device == "cpu" else None,
        )

        if not results:
            return None

        result = results[0]
        names = result.names
        detections = []

        if result.boxes is not None and len(result.boxes) > 0:
            for box, conf, cls_id in zip(
                result.boxes.xyxy.tolist(),
                result.boxes.conf.tolist(),
                result.boxes.cls.tolist()
            ):
                raw = (
                    names.get(int(cls_id), str(int(cls_id)))
                    if isinstance(names, dict)
                    else names[int(cls_id)]
                )
                detections.append({
                    "name": canonical_name(raw),
                    "raw_name": str(raw),
                    "score": round(float(conf), 4),
                    "box": [round(float(x), 1) for x in box],
                })

        detections.sort(key=lambda x: x["score"], reverse=True)
        detections = deduplicate_detections(detections)

        if not detections:
            return {
                "engine": "custom-yolo",
                "detector_path": str(self.detector_path) if self.detector_path else None,
                "detections": [],
                "top": ("Unknown", 0.0),
                "is_unknown": True,
                "raw_top": 0.0,
                "raw_margin": 0.0,
                "unknown_reason": "ไม่พบวัตถุที่โมเดลตรวจจับได้",
            }

        top = detections[0]
        return {
            "engine": "custom-yolo",
            "detector_path": str(self.detector_path) if self.detector_path else None,
            "detections": detections,
            "top": (top["name"], top["score"]),
            "is_unknown": top["score"] < YOLO_MIN_ACCEPT,
            "raw_top": top["score"],
            "raw_margin": (
                top["score"] - detections[1]["score"]
                if len(detections) > 1 else top["score"]
            ),
            "unknown_reason": (
                "ความมั่นใจจากตัวตรวจจับต่ำ"
                if top["score"] < YOLO_MIN_ACCEPT else None
            ),
        }

    def clip_analyze(self, image):
        if self.model is None or self.text_features is None:
            return None

        with self.lock, torch.inference_mode():
            scores = []
            for view in self.views(image):
                inp = self.processor(images=view, return_tensors="pt")
                inp = {k: v.to(self.device) for k, v in inp.items()}
                feat = self.model.get_image_features(**inp)
                feat = feat / feat.norm(dim=-1, keepdim=True).clamp_min(1e-12)
                logits = (feat @ self.text_features.T)[0]

                grouped = {c: [] for c in CLASSES}
                for score, owner in zip(logits.tolist(), self.class_prompts):
                    grouped[owner].append(score)

                scores.append(torch.tensor(
                    [sum(grouped[c]) / len(grouped[c]) for c in CLASSES],
                    device=self.device
                ))

            mean = torch.stack(scores).mean(dim=0)
            vals, inds = torch.topk(mean, k=min(TOP_K, len(CLASSES)))
            candidates = [(CLASSES[int(i)], float(v)) for v, i in zip(vals, inds)]
            raw = [float(v) for v in vals]
            top = raw[0] if raw else 0.0
            margin = raw[0] - raw[1] if len(raw) > 1 else top

            probs = torch.softmax(mean / max(CLIP_TEMPERATURE, 1e-4), dim=0)
            pvals = [float(probs[int(i)]) for i in inds]
            unknown = top < CLIP_MIN_SIM or margin < CLIP_MIN_MARGIN

            return {
                "engine": "clip-zero-shot",
                "detector_path": None,
                "detections": [],
                "top": candidates[0] if candidates else ("Unknown", 0.0),
                "candidates": candidates,
                "probabilities": pvals,
                "raw_top": top,
                "raw_margin": margin,
                "is_unknown": unknown,
                "unknown_reason": (
                    "คะแนนความคล้ายคลึงต่ำ"
                    if top < CLIP_MIN_SIM else (
                        "ผลลัพธ์อันดับต้น ๆ ใกล้เคียงกันเกินไป"
                        if margin < CLIP_MIN_MARGIN else None
                    )
                ),
            }

    def verify_detections(self, image, yolo_result):
        """Optional CLIP second opinion. It never changes the YOLO result."""
        if self.model is None or not yolo_result or not yolo_result.get("detections"):
            return yolo_result

        verified = []
        for det in yolo_result["detections"]:
            item = dict(det)
            x1, y1, x2, y2 = [max(0, int(v)) for v in det["box"]]
            crop = image.crop((
                x1, y1,
                min(image.width, x2),
                min(image.height, y2)
            ))

            if crop.width < 24 or crop.height < 24:
                item["verification"] = {
                    "engine": "clip",
                    "status": "skipped",
                    "reason": "วัตถุมีขนาดเล็กเกินไป"
                }
            else:
                try:
                    clip = self.clip_analyze(crop)
                    if clip:
                        raw_name = str(clip.get("top", ("Unknown", 0))[0])
                        item["verification"] = {
                            "engine": "clip",
                            "status": "supporting_evidence",
                            "name": canonical_name(raw_name),
                            "raw_name": raw_name,
                            "similarity": round(float(clip.get("raw_top", 0)), 4),
                            "margin": round(float(clip.get("raw_margin", 0)), 4),
                            "agrees": raw_name == str(det.get("raw_name", det.get("name", ""))),
                            "candidates": [
                                {
                                    "name": canonical_name(n),
                                    "raw_name": str(n),
                                    "similarity": round(float(v), 4)
                                }
                                for n, v in clip.get("candidates", [])[:TOP_K]
                            ]
                        }
                except Exception as exc:
                    item["verification"] = {
                        "engine": "clip",
                        "status": "skipped",
                        "reason": str(exc)[:200]
                    }

            item["trust_score"] = item["score"]
            verified.append(item)

        result = dict(yolo_result)
        result["detections"] = verified
        result["verification_engine"] = "clip-support-only"
        result["verification_review"] = False
        return result

    def analyze(self, image):
        """
        Primary inference path.

        If custom YOLO is loaded, it is the only model used. A low YOLO
        confidence does NOT trigger a CLIP download/load.
        """
        if self.detector is not None:
            try:
                return self.yolo_analyze(image)
            except Exception as exc:
                self.error = f"YOLO inference failed: {type(exc).__name__}: {exc}"
                logger.exception("YOLO inference failed")
                raise RuntimeError(self.error) from exc

        # CLIP is only considered when YOLO is unavailable and was explicitly enabled.
        if self.model is not None and self.text_features is not None:
            return self.clip_analyze(image)

        raise RuntimeError(
            self.error or
            "No local AI model is available. Custom YOLO is not loaded."
        )


engine=AIEngine()
threading.Thread(target=engine.load,name="ai-loader",daemon=True).start()

app=Flask(__name__)
app.config["MAX_CONTENT_LENGTH"]=MAX_IMAGE_BYTES
analyze_lock=threading.Lock()
init_db()


def is_allowed(filename):
    return bool(filename and "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXT)


def display_result(raw, quality):
    model_name, score = raw.get("top", ("Unknown", 0.0))
    model_name = str(model_name)
    knowledge_name = canonical_name(model_name)
    engine_name = raw.get("engine", "unknown")
    score = float(score or 0.0)
    detections = raw.get("detections", [])
    unknown = bool(raw.get("is_unknown"))
    reason = raw.get("unknown_reason")
    if quality_is_severe(quality) and not unknown:
        reason = "คุณภาพภาพควรปรับปรุง แต่ผลตรวจจับยังคงแสดงจากโมเดล"

    if unknown:
        return {
            "name": "Unknown",
            "name_th": "ไม่สามารถระบุอุปกรณ์ได้อย่างมั่นใจ",
            "type": "Unknown", "category": "Other",
            "description": "ระบบไม่มีหลักฐานเพียงพอที่จะยืนยันชนิดอุปกรณ์จากภาพนี้",
            "uses": "", "specs": "", "safety": "ลองถ่ายใหม่ให้เห็นอุปกรณ์เต็มชิ้น ชัดขึ้น และมีแสงเพียงพอ",
            "score": round(score, 4),
            "score_percent": round(max(0, min(1, score)) * 100, 1),
            "level": "Needs Review",
            "confidence_kind": "model confidence score" if engine_name == "custom-yolo" else ("learned memory match" if engine_name == "learned-memory" else "estimated similarity"),
            "margin": raw.get("raw_margin"),
            "engine": engine_name, "detector_path": raw.get("detector_path"),
            "detections": detections, "predictions": [],
            "unknown_reason": reason or "หลักฐานจากภาพยังไม่เพียงพอ"
        }

    d = detail_for(knowledge_name)
    if engine_name == "custom-yolo":
        verification_review = bool(raw.get("verification_review"))
        level = level_for_yolo(score)
        kind = "model confidence score"
    elif engine_name == "learned-memory":
        level = "Learned"
        kind = "learned memory match"
        candidates = [(x.get("raw_name", x["name"]), x.get("score", 0.0)) for x in detections[:TOP_K]]
    else:
        level = level_for_clip(raw.get("raw_margin", 0), score)
        kind = "estimated similarity ranking"
        candidates = raw.get("candidates", [(model_name, score)])

    return {
        "name": model_name, "name_th": d.get("name_th", class_display_name(model_name)),
        "type": d.get("type", "Electronic Device"), "category": d.get("category", "Other"),
        "description": d.get("description", ""), "uses": d.get("uses", d.get("usage", "")),
        "specs": d.get("specs", ""), "safety": d.get("safety", ""),
        "symbol": d.get("symbol", ""), "unit": d.get("unit", ""), "example": d.get("example", ""),
        "score": round(score, 4),
        "score_percent": round(max(0, min(1, score)) * 100, 1),
        "level": level, "confidence_kind": kind, "margin": raw.get("raw_margin"),
        "engine": engine_name, "detector_path": raw.get("detector_path"),
        "detections": detections,
        "predictions": [
            {
                "name": str(n),
                "name_th": detail_for(canonical_name(n)).get("name_th", class_display_name(n)),
                "score": round(float(s), 4),
                "score_percent": round(max(0, min(1, float(s))) * 100, 1)
            }
            for n, s in candidates[:TOP_K]
        ]
    }


def save_analysis(result, image_path, filename, quality, processing_time_ms=None):
    aid=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    created=now_iso(); circuit=circuit_analysis(result.get("detections",[]))
    result["circuit_analysis"]=circuit; result["created_at"]=created; result["id"]=aid
    with db_conn() as c:
        c.execute("""INSERT INTO analyses (id,created_at,filename,image_path,result_name,result_name_th,confidence,confidence_kind,level,engine,quality_json,detections_json,analysis_json,object_count,processing_time_ms,model_version,dataset_version)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            aid,created,filename,str(image_path.relative_to(BASE)),result["name"],result["name_th"],result["score_percent"],result["confidence_kind"],result["level"],result["engine"],json.dumps(quality_for_storage(quality),ensure_ascii=False),json.dumps(result.get("detections",[]),ensure_ascii=False),json.dumps(result,ensure_ascii=False),len(result.get("detections",[])),processing_time_ms,Path(engine.detector_path).name if engine.detector_path else engine.model_name,"custom_dataset"))
    result["image_url"]="/uploads/"+image_path.name; return result


def api_error(message,status=400,detail=None,code="REQUEST_ERROR"):
    payload={"success":False,"data":None,"error":{"code":code,"message":message}}
    # Legacy compatibility for existing frontend.
    payload["message"]=message
    if detail: payload["detail"]=detail
    return jsonify(payload),status

@app.get("/")
def index(): return render_template("index.html")

@app.get("/api/status")
def status():
    return jsonify({
        "success": True,
        "data": None,
        "ready": engine.ready,
        "loading": engine.loading,
        "error": engine.error,
        "model": "custom-yolo" if engine.detector else (engine.model_name or PRIMARY_MODEL),
        "device": engine.device,
        "classes": len(CLASSES),
        "custom_model": str(engine.detector_path) if engine.detector_path else None,
        "clip_enabled": ENABLE_CLIP_FALLBACK,
        "clip_loaded": engine.model is not None,
    })

@app.get("/api/library")
@app.get("/api/components")
def components():
    q=request.args.get("q","").strip().lower(); category=request.args.get("category","all").strip().lower(); items=[]
    for name in CLASSES:
        d=detail_for(name); item={"name":name,"name_th":d.get("name_th",name),"type":d.get("type","Electronic Device"),"category":d.get("category","Other"),"description":d.get("description",""),"uses":d.get("uses","")}
        if q and q not in name.lower() and q not in item["name_th"].lower(): continue
        if category!="all" and item["category"].lower()!=category: continue
        items.append(item)
    cats=sorted({x["category"] for x in items})
    return jsonify({"success":True,"items":items,"total":len(items),"categories":cats})

@app.get("/api/components/<path:name>")
def component_detail(name):
    key=canonical_name(name)
    if key not in CLASSES and key not in DETAILS_DB: return api_error("ไม่พบอุปกรณ์ในคลัง",404)
    d=detail_for(key); return jsonify({"success":True,"item":{"name":key,**d}})

@app.get("/api/history")
def history():
    q=request.args.get("q","").strip().lower(); period=request.args.get("period","all")
    page=max(1, request.args.get("page",1,type=int)); per_page=min(100,max(10,request.args.get("per_page",20,type=int)))
    sql="SELECT * FROM analyses WHERE 1=1"; args=[]
    if q: sql += " AND (lower(result_name) LIKE ? OR lower(result_name_th) LIKE ?)"; args += [f"%{q}%",f"%{q}%"]
    if period!="all":
        seconds={"today":86400,"week":7*86400,"month":31*86400}.get(period)
        if seconds: sql += " AND created_at >= ?"; args.append((datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat(timespec="seconds"))
    count_sql="SELECT COUNT(*) FROM analyses WHERE 1=1"
    count_args=list(args)
    if q: count_sql += " AND (lower(result_name) LIKE ? OR lower(result_name_th) LIKE ?)"; count_args += [f"%{q}%",f"%{q}%"]
    if period!="all":
        seconds={"today":86400,"week":7*86400,"month":31*86400}.get(period)
        if seconds: count_sql += " AND created_at >= ?"; count_args.append((datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat(timespec="seconds"))
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"; args += [per_page,(page-1)*per_page]
    with db_conn() as c:
        total=c.execute(count_sql,count_args).fetchone()[0]
        rows=c.execute(sql,args).fetchall()
    items=[]
    for r in rows:
        items.append({"id":r["id"],"image_url":"/"+r["image_path"].replace('\\','/'),"component":r["result_name"],"component_th":r["result_name_th"],"confidence":r["confidence"],"level":r["level"],"engine":r["engine"],"created_at":r["created_at"]})
    return jsonify({"success":True,"items":items,"total":total,"page":page,"per_page":per_page,"pages":max(1,(total+per_page-1)//per_page)})

@app.get("/api/history/<aid>")
def history_detail(aid):
    with db_conn() as c: r=c.execute("SELECT * FROM analyses WHERE id=?",(aid,)).fetchone()
    if not r: return api_error("ไม่พบประวัติ",404)
    result=json.loads(r["analysis_json"]); result.update({"success":True,"id":aid,"filename":r["filename"],"created_at":r["created_at"],"image_url":"/"+r["image_path"].replace('\\','/'),"quality":json.loads(r["quality_json"])})
    return jsonify(result)

@app.post("/api/history/<aid>/reanalyze")
def history_reanalyze(aid):
    with db_conn() as c: row=c.execute("SELECT filename,image_path FROM analyses WHERE id=?",(aid,)).fetchone()
    if not row: return api_error("ไม่พบประวัติ",404)
    candidate=(BASE/row["image_path"]).resolve()
    upload_root=UPLOAD_DIR.resolve()
    if upload_root not in candidate.parents or not candidate.exists(): return api_error("ไม่พบไฟล์ภาพต้นฉบับ",404)
    if not analyze_lock.acquire(blocking=False): return api_error("มีการวิเคราะห์อื่นกำลังทำงานอยู่ กรุณารอสักครู่",429)
    try:
        if not engine.ready: return api_error("AI ยังไม่พร้อม",503)
        with Image.open(candidate) as im: image=ImageOps.exif_transpose(im).convert("RGB")
        quality=quality_check(image); started=datetime.now(timezone.utc); raw=engine.analyze(image)
        elapsed=int((datetime.now(timezone.utc)-started).total_seconds()*1000)
        result=display_result(raw,quality); result["quality"]=quality; result["processing_time_ms"]=elapsed
        # Copy the source image so each history row owns its file and deletion is safe.
        import shutil
        suffix=candidate.suffix.lower() or ".jpg"
        copied=UPLOAD_DIR/f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_reanalyzed{suffix}"
        shutil.copy2(candidate,copied)
        result=save_analysis(result,copied,row["filename"],quality,elapsed)
        result["reanalyzed_from"]=aid
        return jsonify({"success":True,"data":result,**result})
    except Exception as exc:
        app.logger.error("reanalyze failed: %s\n%s",exc,traceback.format_exc()); return api_error("เกิดข้อผิดพลาดระหว่างวิเคราะห์ซ้ำ",500)
    finally: analyze_lock.release()

@app.delete("/api/history/<aid>")
def history_delete(aid):
    with db_conn() as c:
        r=c.execute("SELECT image_path FROM analyses WHERE id=?",(aid,)).fetchone()
        if not r: return api_error("ไม่พบประวัติ",404)
        c.execute("DELETE FROM analyses WHERE id=?",(aid,))
    (BASE/r["image_path"]).unlink(missing_ok=True)
    return jsonify({"success":True,"deleted":aid})

@app.get("/api/dashboard")
def dashboard():
    with db_conn() as c:
        total=c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
        cutoff_today=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(timespec="seconds")
        cutoff_week=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec="seconds")
        today=c.execute("SELECT COUNT(*) FROM analyses WHERE created_at >= ?",(cutoff_today,)).fetchone()[0]
        week=c.execute("SELECT COUNT(*) FROM analyses WHERE created_at >= ?",(cutoff_week,)).fetchone()[0]
        avg=c.execute("SELECT AVG(confidence) FROM analyses").fetchone()[0]
        avg_ms=c.execute("SELECT AVG(processing_time_ms) FROM analyses WHERE processing_time_ms IS NOT NULL").fetchone()[0]
        low=c.execute("SELECT COUNT(*) FROM analyses WHERE level='Needs Review' OR result_name='Unknown'").fetchone()[0]
        success=max(0,total-low)
        most=c.execute("SELECT result_name,result_name_th,COUNT(*) n FROM analyses WHERE result_name!='Unknown' GROUP BY result_name ORDER BY n DESC LIMIT 1").fetchone()
        recent=c.execute("SELECT id,created_at,result_name,result_name_th,confidence,level,engine,image_path,object_count,processing_time_ms FROM analyses ORDER BY created_at DESC LIMIT 8").fetchall()
        counts=c.execute("SELECT result_name,result_name_th,COUNT(*) n FROM analyses WHERE result_name!='Unknown' GROUP BY result_name ORDER BY n DESC LIMIT 8").fetchall()
        daily=c.execute("SELECT substr(created_at,1,10) day, COUNT(*) n FROM analyses WHERE created_at >= ? GROUP BY substr(created_at,1,10) ORDER BY day",((datetime.now(timezone.utc)-timedelta(days=13)).isoformat(timespec='seconds'),)).fetchall()
        confidence=c.execute("SELECT CASE WHEN confidence>=85 THEN '85-100' WHEN confidence>=70 THEN '70-84' WHEN confidence>=50 THEN '50-69' ELSE '0-49' END bucket, COUNT(*) n FROM analyses GROUP BY bucket").fetchall()
        engines=c.execute("SELECT engine, COUNT(*) n FROM analyses GROUP BY engine ORDER BY n DESC").fetchall()
    return jsonify({"success":True,"data":{
        "total_analyses":total,"today_analyses":today,"week_analyses":week,"average_confidence":round(avg or 0,1),
        "average_processing_time_ms":round(avg_ms or 0),"success_rate":round((success/total*100) if total else 0,1),
        "low_confidence_rate":round((low/total*100) if total else 0,1),
        "most_detected":{"name":most[0],"name_th":most[1],"count":most[2]} if most else None,
        "detected_components":sum(x[2] for x in counts),"top_components":[dict(x) for x in counts],
        "daily":[dict(x) for x in daily],"confidence_distribution":[dict(x) for x in confidence],"model_usage":[dict(x) for x in engines],
        "recent":[{**dict(x),"image_url":"/"+x["image_path"].replace('\\','/')} for x in recent]
    },"total_analyses":total,"today_analyses":today,"week_analyses":week,"average_confidence":round(avg or 0,1),
    "most_detected":{"name":most[0],"name_th":most[1],"count":most[2]} if most else None,"detected_components":sum(x[2] for x in counts),"top_components":[dict(x) for x in counts],"recent":[{**dict(x),"image_url":"/"+x["image_path"].replace('\\','/')} for x in recent]})


@app.get("/api/feedback/<aid>")
def get_feedback(aid):
    with db_conn() as c:
        row=c.execute("SELECT * FROM feedback WHERE analysis_id=?",(aid,)).fetchone()
    if not row:
        return jsonify({"success":True,"data":None})
    return jsonify({"success":True,"data":dict(row)})


@app.post("/api/feedback/<aid>")
def save_feedback(aid):
    payload=request.get_json(silent=True) or {}
    is_correct=bool(payload.get("is_correct"))
    corrected=payload.get("corrected_label")
    with db_conn() as c:
        row=c.execute("SELECT * FROM analyses WHERE id=?",(aid,)).fetchone()
    if not row:
        return api_error("ไม่พบรายการวิเคราะห์นี้",404,code="ANALYSIS_NOT_FOUND")
    image_path=(BASE / row["image_path"]).resolve()
    if not image_path.exists() or BASE.resolve() not in image_path.parents:
        return api_error("ไม่พบภาพต้นฉบับของรายการนี้",404,code="IMAGE_NOT_FOUND")
    try:
        with Image.open(image_path) as im: image=ImageOps.exif_transpose(im).convert("RGB")
    except Exception:
        return api_error("ไม่สามารถเปิดภาพต้นฉบับเพื่อบันทึกการเรียนรู้ได้",400,code="IMAGE_INVALID")
    resolved=None
    if is_correct:
        resolved=resolve_label(row["result_name"])
        if not resolved:
            return api_error("ผลลัพธ์เดิมไม่ตรงกับคลาสของโมเดล จึงยังจำตัวอย่างนี้ไม่ได้",400,code="LABEL_NOT_RESOLVED")
    else:
        if not str(corrected or "").strip():
            return api_error("กรุณาระบุชื่ออุปกรณ์ที่ถูกต้อง เพื่อให้ AI เรียนรู้จากข้อผิดพลาด",400,code="CORRECTION_REQUIRED")
        resolved=resolve_label(corrected)
        if not resolved:
            return api_error("ไม่พบชื่ออุปกรณ์นี้ในคลาสของโมเดล กรุณาใช้ชื่อจากคลังอุปกรณ์",400,code="LABEL_NOT_FOUND")
    try:
        embedding=None
        try:
            embedding=engine.image_embedding(image)
        except Exception:
            embedding=None
        remember_example(image_path,image,resolved,aid,source="feedback_correct" if is_correct else "feedback_correction",embedding=embedding)
        queue=None
        if not is_correct:
            analysis_json=json.loads(row["analysis_json"] or "{}")
            queue=queue_learning_sample(image_path,image,resolved,aid,analysis_json.get("detections",[]))
        with db_conn() as c:
            c.execute("""INSERT INTO feedback(analysis_id,is_correct,corrected_label,created_at) VALUES(?,?,?,?)\n                ON CONFLICT(analysis_id) DO UPDATE SET is_correct=excluded.is_correct,corrected_label=excluded.corrected_label,created_at=excluded.created_at""",
                (aid,1 if is_correct else 0,resolved["canonical"] if not is_correct else None,now_iso()))
        return jsonify({"success":True,"data":{
            "analysis_id":aid,"is_correct":is_correct,"learned":True,
            "label":resolved["canonical"],"label_th":resolved["name_th"],
            "memory":"exact image memory saved","training_queue":queue,
            "message":"AI จำภาพนี้แล้ว" if is_correct else "AI จำภาพนี้พร้อมคำตอบที่ถูกต้องแล้ว"
        }})
    except Exception as exc:
        app.logger.error("feedback failed: %s\n%s",exc,traceback.format_exc())
        return api_error("บันทึกการเรียนรู้ไม่สำเร็จ",500,str(exc) if app.debug else None,code="FEEDBACK_SAVE_FAILED")

@app.get("/api/learning/stats")
def learning_stats():
    with db_conn() as c:
        memories=c.execute("SELECT COUNT(*) n FROM learned_memory").fetchone()["n"]
        feedback=c.execute("SELECT COUNT(*) n FROM feedback").fetchone()["n"]
        correct=c.execute("SELECT COUNT(*) n FROM feedback WHERE is_correct=1").fetchone()["n"]
        corrections=c.execute("SELECT COUNT(*) n FROM feedback WHERE is_correct=0").fetchone()["n"]
        pending=c.execute("SELECT COUNT(*) n FROM learning_queue WHERE status='pending'").fetchone()["n"]
        ready=c.execute("SELECT COUNT(*) n FROM learning_queue WHERE status='pending' AND requires_annotation=0").fetchone()["n"]
        annotation=c.execute("SELECT COUNT(*) n FROM learning_queue WHERE status='pending' AND requires_annotation=1").fetchone()["n"]
        by_label=c.execute("SELECT label,COUNT(*) n FROM learned_memory GROUP BY label ORDER BY n DESC LIMIT 12").fetchall()
    return jsonify({"success":True,"data":{
        "memory_examples":memories,"feedback_total":feedback,"correct":correct,"corrections":corrections,
        "queue_pending":pending,"queue_ready_for_training":ready,"queue_requires_annotation":annotation,
        "top_learned":[dict(x) for x in by_label]
    }})


@app.get("/api/learning/queue")
def learning_queue():
    status=request.args.get("status","pending").strip().lower()
    if status not in {"pending","used","reviewed","all"}: status="pending"
    with db_conn() as c:
        if status=="all": rows=c.execute("SELECT * FROM learning_queue ORDER BY created_at DESC LIMIT 200").fetchall()
        else: rows=c.execute("SELECT * FROM learning_queue WHERE status=? ORDER BY created_at DESC LIMIT 200",(status,)).fetchall()
    return jsonify({"success":True,"data":[dict(x) for x in rows]})


@app.post("/api/learning/<int:item_id>/status")
def learning_queue_status(item_id):
    payload=request.get_json(silent=True) or {}
    status=str(payload.get("status","pending")).lower().strip()
    if status not in {"pending","used","reviewed"}:
        return api_error("สถานะคิวการเรียนรู้ไม่ถูกต้อง",400,code="INVALID_LEARNING_STATUS")
    with db_conn() as c:
        cur=c.execute("UPDATE learning_queue SET status=?,updated_at=? WHERE id=?",(status,now_iso(),item_id))
        if cur.rowcount != 1:
            return api_error("ไม่พบรายการเรียนรู้นี้",404,code="LEARNING_ITEM_NOT_FOUND")
        row=c.execute("SELECT * FROM learning_queue WHERE id=?",(item_id,)).fetchone()
    return jsonify({"success":True,"data":dict(row)})


@app.post("/api/learning/reload-memory")
def learning_reload_memory():
    """Compatibility endpoint: memory is persisted in SQLite and needs no model reload."""
    return jsonify({"success":True,"data":{"reloaded":True,"message":"ความจำจาก feedback ถูกบันทึกถาวรในฐานข้อมูลแล้ว ไม่ต้อง reload โมเดล"}})


@app.post("/api/analyze")
def analyze():
    if not analyze_lock.acquire(blocking=False): return api_error("มีการวิเคราะห์อื่นกำลังทำงานอยู่ กรุณารอสักครู่",429)
    path=None
    try:
        if "image" not in request.files: return api_error("กรุณาเลือกภาพก่อน",400)
        f=request.files["image"]
        if not f.filename or not is_allowed(f.filename): return api_error("รองรับเฉพาะ JPG, JPEG, PNG, WEBP และ BMP",400)
        if not engine.ready: return api_error("AI ยังไม่พร้อม",503,{"loading":engine.loading,"detail":engine.error})
        safe=secure_filename(f.filename)
        if not safe: return api_error("ชื่อไฟล์ไม่ถูกต้อง",400)
        stamp=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"); path=UPLOAD_DIR/f"{stamp}_{safe}"
        f.save(path)
        try:
            with Image.open(path) as im:
                fmt = im.format
                if fmt not in ALLOWED_FORMATS:
                    raise ValueError("invalid format")
                if im.width * im.height > MAX_IMAGE_PIXELS:
                    raise ValueError("image dimensions exceed limit")
                im.verify()
            with Image.open(path) as im:
                image = ImageOps.exif_transpose(im).convert("RGB")
        except Exception:
            path.unlink(missing_ok=True); return api_error("ไฟล์ภาพเสียหายหรือชนิดไฟล์ไม่ถูกต้อง",400)
        quality=quality_check(image)
        started=datetime.now(timezone.utc)
        raw=engine.analyze(image)
        # Exact memory can safely override the model because it is the same image the user previously confirmed.
        # Similar-memory matches are hints only; they never silently override a model prediction.
        embedding=None
        try:
            embedding=engine.image_embedding(image)
        except Exception:
            embedding=None
        memory=find_memory(image,embedding)
        if memory:
            if memory["match"] == "exact":
                raw=make_memory_result(memory)
            else:
                raw["memory_hint"]={"label":memory["row"]["label"],"similarity":round(memory["similarity"],4),"match":"similar"}
        elapsed=int((datetime.now(timezone.utc)-started).total_seconds()*1000)
        result=display_result(raw,quality); result["quality"]=quality; result["processing_time_ms"]=elapsed
        if raw.get("memory"):
            result["memory"]=raw["memory"]
        elif raw.get("memory_hint"):
            result["memory_hint"]=raw["memory_hint"]
        result=save_analysis(result,path,safe,quality,elapsed)
        return jsonify({"success":True,"data":result,**result})
    except Exception as exc:
        if path and path.exists(): path.unlink(missing_ok=True)
        app.logger.error("analyze failed: %s\n%s",exc,traceback.format_exc())
        return api_error("เกิดข้อผิดพลาดระหว่างวิเคราะห์ภาพ",500,str(exc) if app.debug else None)
    finally: analyze_lock.release()

@app.get("/uploads/<path:filename>")
def uploads(filename): return send_from_directory(UPLOAD_DIR,filename)

@app.errorhandler(413)
def too_large(_): return api_error("Image is too large. Maximum size is 12 MB.",413)

@app.errorhandler(500)
def server_error(_): return api_error("เซิร์ฟเวอร์เกิดข้อผิดพลาด",500)



# Production-friendly health/model metadata endpoints.
@app.get("/api/health")
def health():
    return jsonify({
        "success": True,
        "data": {
            "status": "ok" if engine.ready else "degraded",
            "ai_ready": engine.ready,
            "device": engine.device,
            "custom_model": str(engine.detector_path) if engine.detector_path else None,
            "clip_enabled": ENABLE_CLIP_FALLBACK,
            "clip_loaded": engine.model is not None,
        },
    }), (200 if engine.ready else 503)

@app.get("/api/models")
def models_info():
    model_path=Path(engine.detector_path) if engine.detector_path else None
    return jsonify({"success":True,"data":{
        "yolo":{"path":str(model_path) if model_path else None,"available":bool(model_path and model_path.exists())},
        "clip":{"name":engine.model_name,"available":engine.model is not None},
        "device":engine.device,"classes":len(CLASSES),"dataset_version":"custom_dataset","last_trained":datetime.fromtimestamp(model_path.stat().st_mtime,timezone.utc).isoformat() if model_path and model_path.exists() else None
    }})

if __name__=="__main__":
    host=os.getenv("HOST","127.0.0.1"); port=int(os.getenv("PORT","5000")); app.run(host=host,port=port,debug=False)
