"""Gemini vision fallback for the electronics detector.

Gemini is used only when the local YOLO/YOLO-World detectors cannot make a
confident decision. The API key is read from GEMINI_API_KEY at runtime.
"""
from __future__ import annotations

import io
import json
import logging
import os
import threading
from typing import Any

from PIL import Image

logger = logging.getLogger("electronics-ai.gemini")

try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - handled at runtime
    genai = None
    types = None


class GeminiFallback:
    def __init__(self, classes: list[str]):
        self.classes = list(classes)
        self.enabled = os.getenv("ELECTRONICS_AI_ENABLE_GEMINI_FALLBACK", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = os.getenv("ELECTRONICS_AI_GEMINI_MODEL", "gemini-3.7-flash").strip()
        self.min_accept = float(os.getenv("ELECTRONICS_AI_GEMINI_MIN_ACCEPT", "0.55"))
        self.max_boxes = max(1, min(10, int(os.getenv("ELECTRONICS_AI_GEMINI_MAX_BOXES", "5"))))
        self.client = None
        self.lock = threading.Lock()
        self.error = None

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key and genai is not None)

    def _ensure_client(self):
        if not self.enabled:
            raise RuntimeError("Gemini fallback is disabled")
        if genai is None:
            raise RuntimeError("google-genai is not installed")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        with self.lock:
            if self.client is None:
                self.client = genai.Client(api_key=self.api_key)
        return self.client

    def _schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "boxes": {
                    "type": "array",
                    "maxItems": self.max_boxes,
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "description": "One exact class name from the allowed list.",
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "box_2d": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "minItems": 4,
                                "maxItems": 4,
                                "description": "[ymin, xmin, ymax, xmax], normalized to 0-1000.",
                            },
                        },
                        "required": ["label", "confidence", "box_2d"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["boxes"],
            "additionalProperties": False,
        }

    @staticmethod
    def _key(value: str) -> str:
        return "".join(ch.lower() for ch in str(value) if ch.isalnum())

    def _canonical_label(self, value: str) -> str | None:
        key = self._key(value)
        exact = {self._key(name): name for name in self.classes}
        if key in exact:
            return exact[key]

        aliases = {
            "led": "LED",
            "arduinounor3": "Arduino_UNO_R3",
            "arduinomega2560": "Arduino_Mega_2560",
            "arduinonano": "Arduino_Nano",
            "esp32": "ESP32_DevKit",
            "esp32devkit": "ESP32_DevKit",
            "esp32cam": "ESP32_CAM",
            "esp8266nodemcu": "ESP8266_NodeMCU",
            "raspberrypi4": "Raspberry_Pi_4",
            "raspberrypipico": "Raspberry_Pi_Pico",
            "breadboard": "Breadboard",
            "resistor": "Resistor",
            "potentiometer": "Potentiometer",
            "bmp280sensor": "BMP280",
            "dht11sensor": "DHT11",
            "dht22sensor": "DHT22",
            "ultrasonichcsr04": "HC_SR04",
        }
        target = aliases.get(key)
        return target if target in self.classes else None

    @staticmethod
    def _box_to_pixels(box: list[Any], width: int, height: int) -> list[int] | None:
        if not isinstance(box, list) or len(box) != 4:
            return None
        try:
            ymin, xmin, ymax, xmax = [float(v) for v in box]
        except (TypeError, ValueError):
            return None
        x1 = max(0, min(width, round(xmin / 1000 * width)))
        y1 = max(0, min(height, round(ymin / 1000 * height)))
        x2 = max(0, min(width, round(xmax / 1000 * width)))
        y2 = max(0, min(height, round(ymax / 1000 * height)))
        if x2 <= x1 or y2 <= y1:
            return None
        return [x1, y1, x2, y2]

    def analyze(self, image: Image.Image) -> dict[str, Any]:
        client = self._ensure_client()
        rgb = image.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=88, optimize=True)
        image_bytes = buf.getvalue()

        allowed = "\n".join(f"- {name}" for name in self.classes)
        prompt = f"""You are the fallback vision detector for an electronics-component web app.
Detect only prominent physical objects that belong to the allowed class list below.
Do not invent a class. If an object is not clearly one of these classes, omit it.
For each detected object return its exact class name, a confidence from 0 to 1,
and a bounding box [ymin, xmin, ymax, xmax] normalized to 0-1000.
Prefer no detection over a guess. Focus on the electronics component itself, not text labels or packaging.
Allowed classes:
{allowed}
"""

        response = client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=self._schema(),
                temperature=0.0,
            ),
        )

        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        data = json.loads(text)
        boxes = data.get("boxes", []) if isinstance(data, dict) else []

        detections = []
        for item in boxes[: self.max_boxes]:
            if not isinstance(item, dict):
                continue
            name = self._canonical_label(item.get("label", ""))
            if not name:
                continue
            try:
                score = max(0.0, min(1.0, float(item.get("confidence", 0))))
            except (TypeError, ValueError):
                score = 0.0
            box = self._box_to_pixels(item.get("box_2d"), rgb.width, rgb.height)
            if box is None or score < self.min_accept:
                continue
            detections.append({
                "name": name,
                "raw_name": str(item.get("label", name)),
                "score": round(score, 4),
                "box": box,
                "engine": "gemini-fallback",
            })

        detections.sort(key=lambda x: x["score"], reverse=True)
        if detections:
            top = detections[0]
            return {
                "engine": "gemini-fallback",
                "detector_path": None,
                "detections": detections,
                "top": (top["name"], top["score"]),
                "candidates": [(d["name"], d["score"]) for d in detections],
                "probabilities": [d["score"] for d in detections],
                "raw_top": top["score"],
                "raw_margin": top["score"] - (detections[1]["score"] if len(detections) > 1 else 0.0),
                "is_unknown": False,
                "unknown_reason": None,
            }

        return {
            "engine": "gemini-fallback",
            "detector_path": None,
            "detections": [],
            "top": ("Unknown", 0.0),
            "candidates": [],
            "probabilities": [],
            "raw_top": 0.0,
            "raw_margin": 0.0,
            "is_unknown": True,
            "unknown_reason": "Gemini ไม่พบอุปกรณ์ที่อยู่ในรายการคลาสอย่างมั่นใจ",
        }
