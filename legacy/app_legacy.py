import json
import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import torch
from PIL import Image, ImageTk, ImageOps, ImageEnhance

BASE = Path(__file__).resolve().parent
DETAILS = BASE / "details.json"
PRIMARY_MODEL = os.getenv("ELECTRONICS_AI_MODEL", "openai/clip-vit-large-patch14")
FALLBACK_MODEL = "openai/clip-vit-base-patch32"

# Broad electronics vocabulary. More specific names are intentionally used for
# visually similar families (Arduino/ESP boards, displays, sensors, etc.).
CLASSES = [
    "Arduino UNO", "Arduino Nano", "Arduino Mega", "ESP32 development board", "ESP8266 development board",
    "Raspberry Pi single board computer", "breadboard", "breadboard power supply module",
    "resistor", "potentiometer", "thermistor", "photoresistor LDR", "capacitor", "electrolytic capacitor",
    "ceramic capacitor", "diode", "LED", "RGB LED", "7 segment display", "LCD display", "OLED display",
    "relay module", "transistor", "MOSFET", "voltage regulator", "buck converter", "boost converter",
    "DC motor", "servo motor", "stepper motor", "buzzer", "speaker", "microphone", "push button",
    "switch", "rotary encoder", "joystick module", "IR receiver", "ultrasonic sensor", "PIR motion sensor",
    "temperature sensor", "humidity sensor", "light sensor", "gas sensor", "soil moisture sensor",
    "accelerometer", "gyroscope sensor", "RFID reader", "RFID card", "GPS module", "Bluetooth module",
    "WiFi module", "LoRa module", "camera module", "logic level converter", "motor driver module",
    "USB to serial adapter", "battery holder", "battery", "power supply adapter", "charger", "multimeter",
    "oscilloscope", "soldering iron", "jumper wires", "alligator clip", "PCB", "integrated circuit IC chip",
    "DIP socket", "crystal oscillator", "terminal block", "header pins", "fuse", "transformer",
    "inductor", "antenna", "router", "network switch", "webcam", "computer monitor", "smartphone"
]

# Multiple natural descriptions reduce dependence on a single wording.
PROMPTS = {
    "Arduino UNO": ["Arduino UNO R3 development board", "Arduino UNO microcontroller board", "Arduino UNO board"],
    "Arduino Nano": ["Arduino Nano development board", "Arduino Nano microcontroller board", "Arduino Nano"],
    "Arduino Mega": ["Arduino Mega 2560 development board", "Arduino Mega microcontroller board", "Arduino Mega"],
    "ESP32 development board": ["ESP32 development board", "ESP32 WiFi Bluetooth microcontroller board", "ESP32 board"],
    "ESP8266 development board": ["ESP8266 development board", "ESP8266 WiFi microcontroller board", "ESP8266 board"],
    "Raspberry Pi single board computer": ["Raspberry Pi single board computer", "Raspberry Pi board", "Raspberry Pi computer"],
    "breadboard": ["solderless breadboard", "electronic prototyping breadboard", "white solderless breadboard"],
    "resistor": ["electronic resistor component", "resistor component with colored bands", "through hole resistor"],
    "potentiometer": ["potentiometer variable resistor", "rotary potentiometer", "variable resistor knob"],
    "thermistor": ["thermistor electronic component", "temperature dependent resistor", "thermistor"],
    "photoresistor LDR": ["LDR photoresistor", "light dependent resistor", "photoresistor component"],
    "capacitor": ["electronic capacitor component", "capacitor component", "non polarized capacitor"],
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
    "buzzer": ["electronic buzzer", "piezo buzzer", "buzzer component"],
    "speaker": ["small electronic speaker", "loudspeaker component", "speaker"],
    "microphone": ["electret microphone component", "microphone module", "electronic microphone"],
    "push button": ["electronic push button switch", "tactile push button", "momentary push button"],
    "switch": ["electronic switch", "toggle switch", "electrical switch component"],
    "rotary encoder": ["rotary encoder module", "electronic rotary encoder", "rotary encoder knob"],
    "joystick module": ["analog joystick module", "electronic joystick module", "two axis joystick module"],
    "IR receiver": ["infrared IR receiver module", "IR remote receiver", "infrared receiver component"],
    "ultrasonic sensor": ["ultrasonic distance sensor module", "HC-SR04 ultrasonic sensor", "ultrasonic sensor board"],
    "PIR motion sensor": ["PIR motion sensor module", "passive infrared motion sensor", "PIR sensor board"],
    "temperature sensor": ["electronic temperature sensor", "temperature sensor module", "digital temperature sensor"],
    "humidity sensor": ["humidity sensor module", "electronic humidity sensor", "temperature humidity sensor"],
    "light sensor": ["electronic light sensor module", "ambient light sensor", "light sensor board"],
    "gas sensor": ["gas sensor module", "electronic gas detection sensor", "MQ gas sensor"],
    "soil moisture sensor": ["soil moisture sensor module", "soil humidity sensor", "soil moisture probe"],
    "accelerometer": ["electronic accelerometer sensor", "accelerometer module", "motion accelerometer"],
    "gyroscope sensor": ["electronic gyroscope sensor", "gyroscope module", "gyro sensor board"],
    "RFID reader": ["RFID reader module", "RFID card reader", "RFID antenna reader board"],
    "RFID card": ["RFID card tag", "contactless RFID card", "RFID access card"],
    "GPS module": ["GPS receiver module", "GPS electronic module", "GPS board"],
    "Bluetooth module": ["Bluetooth wireless module", "Bluetooth serial module", "Bluetooth electronics board"],
    "WiFi module": ["WiFi wireless module", "WiFi electronics module", "WiFi development module"],
    "LoRa module": ["LoRa wireless module", "LoRa radio module", "LoRa electronics board"],
    "camera module": ["camera module board", "small electronic camera module", "camera sensor module"],
    "logic level converter": ["logic level converter module", "bidirectional level shifter", "logic voltage converter"],
    "motor driver module": ["motor driver module", "DC motor controller board", "H bridge motor driver"],
    "USB to serial adapter": ["USB to serial converter", "USB UART adapter", "USB serial electronics module"],
    "battery holder": ["battery holder", "battery case holder", "battery compartment"],
    "battery": ["electrical battery", "rechargeable battery", "battery cell"],
    "power supply adapter": ["AC DC power adapter", "electronic power supply adapter", "wall power adapter"],
    "charger": ["battery charger", "electronic charger", "USB charger"],
    "multimeter": ["digital multimeter", "electrical multimeter", "electronic test meter"],
    "oscilloscope": ["digital oscilloscope", "electronic oscilloscope", "oscilloscope test instrument"],
    "soldering iron": ["soldering iron", "electronic soldering tool", "electric soldering iron"],
    "jumper wires": ["Dupont jumper wires", "electronic jumper wires", "breadboard jumper cables"],
    "alligator clip": ["alligator clip test lead", "electronic crocodile clip", "alligator electrical clip"],
    "PCB": ["printed circuit board PCB", "electronic circuit board", "PCB board"],
    "integrated circuit IC chip": ["integrated circuit IC chip", "electronic IC chip", "semiconductor integrated circuit"],
    "DIP socket": ["DIP IC socket", "dual inline package socket", "IC socket"],
    "crystal oscillator": ["quartz crystal oscillator", "electronic crystal component", "crystal resonator"],
    "terminal block": ["electrical terminal block", "PCB screw terminal", "terminal connector"],
    "header pins": ["male header pins", "PCB header connector", "pin header"],
    "fuse": ["electrical fuse component", "glass fuse", "electronic fuse"],
    "transformer": ["electrical transformer", "power transformer", "electronic transformer"],
    "inductor": ["electronic inductor", "coil inductor", "inductor component"],
    "antenna": ["radio antenna", "wireless antenna", "electronic antenna"],
    "router": ["WiFi router", "wireless network router", "internet router"],
    "network switch": ["Ethernet network switch", "network switch", "LAN switch"],
    "webcam": ["USB webcam", "computer webcam", "web camera"],
    "computer monitor": ["computer monitor", "LCD computer monitor", "desktop display monitor"],
    "smartphone": ["smartphone", "mobile phone", "smart phone device"],
}

with open(DETAILS, "r", encoding="utf-8") as f:
    DETAILS_DB = json.load(f)


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("ELECTRONICS AI — High Accuracy Image Classifier")
        self.root.geometry("1280x820")
        self.root.minsize(1050, 680)
        self.model = None
        self.processor = None
        self.model_name = None
        self.text_features = None
        self.class_prompts = None
        self.current_path = None
        self.current_image = None
        self.photo = None
        self.job = 0
        self.busy = False
        self.status = tk.StringVar(value="กำลังเตรียม AI...")
        self.threshold = tk.DoubleVar(value=0.20)
        self.build_ui()
        threading.Thread(target=self.load_model, daemon=True).start()

    def build_ui(self):
        top = tk.Frame(self.root, padx=20, pady=14); top.pack(fill="x")
        tk.Label(top, text="ELECTRONICS AI", font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(top, textvariable=self.status, font=("Segoe UI", 10)).pack(side="right")
        ctl = tk.Frame(self.root, padx=20, pady=8); ctl.pack(fill="x")
        self.upload = tk.Button(ctl, text="📁 อัปโหลดรูปภาพ", width=18, height=2, command=self.open_image)
        self.upload.pack(side="left", padx=4)
        tk.Button(ctl, text="🧹 ล้างผล", width=12, height=2, command=self.clear).pack(side="left", padx=4)
        tk.Label(ctl, text="เกณฑ์แสดงผล", padx=12).pack(side="left")
        tk.Scale(ctl, from_=0.05, to=0.90, resolution=0.05, orient="horizontal", variable=self.threshold, length=180).pack(side="left")
        body = tk.Frame(self.root, padx=20, pady=10); body.pack(fill="both", expand=True)
        left = tk.Frame(body, bd=1, relief="sunken"); left.pack(side="left", fill="both", expand=True)
        self.image_view = tk.Label(left, text="อัปโหลดรูปอุปกรณ์อิเล็กทรอนิกส์ที่นี่", font=("Segoe UI", 18))
        self.image_view.pack(fill="both", expand=True, padx=8, pady=8)
        right = tk.Frame(body, width=430, padx=18); right.pack(side="right", fill="y"); right.pack_propagate(False)
        tk.Label(right, text="ผลการวิเคราะห์", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        self.name = tk.Label(right, text="ยังไม่มีข้อมูล", font=("Segoe UI", 21, "bold"), wraplength=390, justify="left")
        self.name.pack(anchor="w", pady=(15,4))
        self.conf = tk.Label(right, text="", font=("Segoe UI", 11)); self.conf.pack(anchor="w", pady=(0,10))
        self.text = tk.Text(right, wrap="word", font=("Segoe UI", 11), height=26); self.text.pack(fill="both", expand=True)
        self.set_text("รายละเอียดจะแสดงที่นี่หลังจากอัปโหลดรูปภาพ")

    def set_text(self, s):
        self.text.config(state="normal"); self.text.delete("1.0", "end"); self.text.insert("1.0", s); self.text.config(state="disabled")

    def set_status(self, s): self.root.after(0, lambda: self.status.set(s))

    def load_model(self):
        from transformers import CLIPModel, CLIPProcessor
        for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
            try:
                self.set_status(f"กำลังโหลด AI: {model_name} ...")
                proc = CLIPProcessor.from_pretrained(model_name)
                model = CLIPModel.from_pretrained(model_name)
                model.eval()
                self.processor, self.model, self.model_name = proc, model, model_name
                self.prepare_text_features()
                self.set_status(f"AI พร้อมใช้งาน ({model_name.split('/')[-1]})")
                if self.current_image is not None and not self.busy:
                    self.start_analysis(self.current_image.copy(), self.job)
                return
            except Exception as e:
                last = e
        self.set_status("โหลด AI ไม่สำเร็จ")
        self.root.after(0, lambda: messagebox.showerror("AI Model Error", "ดาวน์โหลด/โหลดโมเดลไม่ได้\n\n" + str(last)))

    def prepare_text_features(self):
        prompts, owners = [], []
        for cls in CLASSES:
            for p in PROMPTS.get(cls, [cls]):
                prompts.extend([f"a photo of {p}", f"a clear product photo of {p}", f"a real electronic device: {p}"])
                owners.extend([cls, cls, cls])
        with torch.no_grad():
            inp = self.processor(text=prompts, return_tensors="pt", padding=True)
            feat = self.model.get_text_features(**inp)
            feat = feat / feat.norm(dim=-1, keepdim=True)
        self.text_features = feat
        self.class_prompts = owners

    def open_image(self):
        path = filedialog.askopenfilename(title="เลือกรูปอุปกรณ์อิเล็กทรอนิกส์", filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.webp"), ("All files", "*.*")])
        if not path: return
        try: img = Image.open(path).convert("RGB")
        except Exception as e: messagebox.showerror("Image Error", str(e)); return
        self.job += 1; jid = self.job; self.current_path = Path(path); self.current_image = img
        self.show_image(img); self.name.config(text="กำลังวิเคราะห์..."); self.conf.config(text=""); self.set_text("รับรูปแล้ว\n\nAI กำลังวิเคราะห์อุปกรณ์ทั้งภาพ...")
        if self.model is None:
            self.set_status("รับรูปแล้ว — รอ AI โหลดเสร็จ"); return
        self.start_analysis(img.copy(), jid)

    def image_views(self, image):
        # Keep the whole object visible; mild contrast/sharpness variants improve robustness.
        a = ImageOps.contain(image, (768,768))
        b = ImageEnhance.Contrast(a).enhance(1.08)
        c = ImageEnhance.Sharpness(a).enhance(1.15)
        return [a,b,c]

    def start_analysis(self, image, jid):
        if self.model is None or self.busy: return
        self.busy = True; self.upload.config(state="disabled")
        threading.Thread(target=self.analyze, args=(image,jid), daemon=True).start()

    def analyze(self, image, jid):
        try:
            self.set_status("กำลังวิเคราะห์หลายมุมมองของรูป...")
            all_scores = []
            with torch.no_grad():
                for view in self.image_views(image):
                    inp = self.processor(images=view, return_tensors="pt")
                    img_feat = self.model.get_image_features(**inp)
                    img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
                    logits = (img_feat @ self.text_features.T)[0]
                    # Average prompt variants per class before softmax over classes.
                    sums = {c: [] for c in CLASSES}
                    for score, owner in zip(logits.tolist(), self.class_prompts): sums[owner].append(score)
                    class_logits = torch.tensor([sum(sums[c])/len(sums[c]) for c in CLASSES])
                    all_scores.append(class_logits)
                final_logits = torch.stack(all_scores).mean(dim=0)
                probs = final_logits.softmax(dim=0)
                vals, inds = torch.topk(probs, k=min(7,len(CLASSES)))
            candidates = [(CLASSES[int(i)], float(v)) for v,i in zip(vals,inds)]
            self.root.after(0, lambda: self.finish(candidates,jid))
        except Exception as e:
            self.root.after(0, lambda: self.error(str(e),jid))

    def finish(self, candidates, jid):
        if jid != self.job: return
        self.busy=False; self.upload.config(state="normal")
        name, conf = candidates[0]; detail = DETAILS_DB.get(name, DETAILS_DB.get("default", {}))
        # Do not hide the top prediction just because its softmax probability
        # is below the UI threshold. With many classes, even a correct class
        # can have a low absolute probability. Always show the best match.
        self.name.config(text=detail.get("name_th", name))

        # The number below is a ranking score, not a calibrated probability.
        # Only warn when the top two candidates are genuinely close.
        margin = conf - candidates[1][1] if len(candidates) > 1 else conf
        if margin >= 0.010:
            level = "ค่อนข้างมั่นใจ"
        elif margin >= 0.003:
            level = "ปานกลาง"
        else:
            level = "ผลใกล้เคียงกัน ควรตรวจสอบอีกครั้ง"
        self.conf.config(text=f"คะแนนการจัดอันดับ: {conf*100:.1f}%  •  {level}")
        lines=[f"ชื่อที่ AI วิเคราะห์: {detail.get('name_th',name)}",f"ประเภท: {detail.get('type','อุปกรณ์อิเล็กทรอนิกส์')}",f"\nรายละเอียด:\n{detail.get('description','ยังไม่มีข้อมูลเฉพาะรายการนี้')}",f"\nการใช้งาน:\n{detail.get('uses','ตรวจสอบรุ่นจริงก่อนใช้งาน')}",f"\nข้อมูลสำคัญ:\n{detail.get('specs','รายละเอียดขึ้นอยู่กับรุ่นจริง')}",f"\nข้อควรระวัง:\n{detail.get('safety','ตรวจสอบแรงดัน กระแส และ pinout ก่อนใช้งาน')}","\nผลลัพธ์รอง:"]
        for n,c in candidates[1:]: lines.append(f"• {DETAILS_DB.get(n,{}).get('name_th',n)} — {c*100:.1f}%")
        lines.append("\nหมายเหตุ: คะแนนนี้เป็นคะแนนเปรียบเทียบระหว่างคลาสที่ระบบรู้จัก ไม่ใช่เปอร์เซ็นต์การรับประกันความถูกต้อง")
        self.set_text("\n".join(lines)); self.status.set(f"วิเคราะห์เสร็จ: {self.current_path.name if self.current_path else ''}")

    def error(self,e,jid):
        if jid != self.job: return
        self.busy=False; self.upload.config(state="normal"); self.status.set("วิเคราะห์ไม่สำเร็จ"); messagebox.showerror("Analysis Error",e)

    def show_image(self,img):
        w=max(self.image_view.winfo_width()-20,500); h=max(self.image_view.winfo_height()-20,400)
        x=img.copy(); x.thumbnail((w,h)); self.photo=ImageTk.PhotoImage(x); self.image_view.config(image=self.photo,text="")

    def clear(self):
        self.job += 1; self.current_path=None; self.current_image=None; self.photo=None; self.name.config(text="ยังไม่มีข้อมูล"); self.conf.config(text=""); self.set_text("รายละเอียดจะแสดงที่นี่หลังจากอัปโหลดรูปภาพ"); self.image_view.config(image="",text="อัปโหลดรูปอุปกรณ์อิเล็กทรอนิกส์ที่นี่"); self.status.set("พร้อมใช้งาน — กด อัปโหลดรูปภาพ")


if __name__ == "__main__":
    root=tk.Tk(); App(root); root.mainloop()
