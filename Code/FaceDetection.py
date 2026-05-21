"""
Multi-Factor Driver Authentication System
Module: Face Recognition + iPhone-Style Registration + Auto Lighting
---------------------------------------------------------------------
Changes:
  1. Each directional step captures BOTH normal + dark samples
  2. Removed standalone low_light / bright steps
  3. Stricter face detection (larger minSize, higher minNeighbors, center-only zone)
  4. Multiple face alert
  5. LED flicker fix — 5-second hysteresis check before switching state

Registration steps:
  1. Look straight        (normal + dark)
  2. Turn head RIGHT      (normal + dark)
  3. Turn head LEFT       (normal + dark)
  4. Tilt head UP         (normal + dark)
  5. Tilt head DOWN       (normal + dark)

Controls:
  R = Start registration
  Q = Quit
"""

import cv2
import numpy as np
import os
import csv
import time
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
HAAR_CASCADE_PATH  = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
DRIVER_FACE_FILE   = "driver1_face.npy"
LOG_FILE           = "auth_log.csv"
CAMERA_INDEX       = 0
FRAME_WIDTH        = 640
FRAME_HEIGHT       = 480
MATCH_THRESHOLD    = 75
SAMPLES_PER_STEP   = 20   # per lighting condition — so 40 total per pose

# ── Lighting ──
BRIGHTNESS_LOW      = 80    # Raised — backlit faces are much darker than background
BRIGHTNESS_OK       = 100   # Hysteresis gap
RELAY_LED_HARDWARE  = False

# ── LED flicker fix ──
# LED state only switches after brightness stays consistently
# low/high for this many seconds
LED_CONFIRM_SECS    = 5.0

# ── Face detection strictness ──
# Higher minNeighbors = fewer false positives from background
DETECT_SCALE        = 1.1
DETECT_MIN_NEIGHBORS = 8      # was 5 — stricter, rejects background noise
DETECT_MIN_SIZE      = (100, 100)  # was 70 — ignores small false detections

# Detection zone — only look for faces in the center portion of the frame
# Reduces chance of background objects being detected at the edges
DETECT_ZONE_X        = 80    # pixels from left/right to ignore
DETECT_ZONE_Y        = 60    # pixels from top/bottom to ignore


# ─────────────────────────────────────────────
# REGISTRATION STEPS
# Each step runs TWICE: once normal light, once dark sim
# ─────────────────────────────────────────────
REGISTRATION_STEPS = [
    {
        "id":          "center",
        "instruction": "Look straight at the camera",
        "arrow":       None,
    },
    {
        "id":          "right",
        "instruction": "Slowly turn your head RIGHT",
        "arrow":       "right",
    },
    {
        "id":          "left",
        "instruction": "Slowly turn your head LEFT",
        "arrow":       "left",
    },
    {
        "id":          "up",
        "instruction": "Tilt your head UP",
        "arrow":       "up",
    },
    {
        "id":          "down",
        "instruction": "Tilt your head DOWN",
        "arrow":       "down",
    },
]


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "Event", "Detail", "Result"])

def log_event(event, detail="N/A", result="N/A"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([timestamp, event, detail, result])
    print(f"[LOG] {timestamp} | {event} | {detail} | {result}")


# ─────────────────────────────────────────────
# LED RELAY
# ─────────────────────────────────────────────
def led_relay_on():
    if RELAY_LED_HARDWARE:
        pass  # GPIO.output(LED_RELAY_PIN, GPIO.HIGH)
    print("[LED] ON — Low light confirmed")
    log_event("LED_RELAY", detail="Low brightness confirmed", result="ON")

def led_relay_off():
    if RELAY_LED_HARDWARE:
        pass  # GPIO.output(LED_RELAY_PIN, GPIO.LOW)
    print("[LED] OFF — Good light confirmed")
    log_event("LED_RELAY", detail="Good brightness confirmed", result="OFF")

def measure_brightness(frame, faces=None):
    """
    Measure brightness smartly:
    - If a face is detected, measure brightness ON the face region only.
      This handles backlit situations (bright window behind dark face).
    - If no face detected, use a dark-weighted blend:
      70% center crop + 30% overall frame average.
      This avoids bright backgrounds fooling the sensor.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    if faces and len(faces) > 0:
        # Use the largest detected face region
        (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
        face_roi = gray[y:y+h, x:x+w]
        return float(np.mean(face_roi))

    # No face — weighted blend to avoid bright background dominating
    fh, fw = gray.shape
    cx, cy = fw // 2, fh // 2
    center_roi    = gray[cy-75:cy+75, cx-100:cx+100]
    center_bright = float(np.mean(center_roi))
    overall_bright = float(np.mean(gray))

    # Weight: 70% center, 30% overall — punishes bright edges/windows
    return 0.7 * center_bright + 0.3 * overall_bright


# ─────────────────────────────────────────────
# FACE DETECTION  (center-zone only, strict)
# ─────────────────────────────────────────────
def detect_faces(gray_frame):
    """
    Detect faces only within the center zone of the frame.
    Returns list of (x, y, w, h) in original frame coordinates.
    """
    h, w = gray_frame.shape
    x1 = DETECT_ZONE_X
    y1 = DETECT_ZONE_Y
    x2 = w - DETECT_ZONE_X
    y2 = h - DETECT_ZONE_Y

    zone = gray_frame[y1:y2, x1:x2]

    raw_faces = cv2.CascadeClassifier(HAAR_CASCADE_PATH).detectMultiScale(
        zone,
        scaleFactor  = DETECT_SCALE,
        minNeighbors = DETECT_MIN_NEIGHBORS,
        minSize      = DETECT_MIN_SIZE,
        flags        = cv2.CASCADE_SCALE_IMAGE
    )

    if len(raw_faces) == 0:
        return []

    # Translate zone coords back to full frame coords
    return [(x + x1, y + y1, w, h) for (x, y, w, h) in raw_faces]


# ─────────────────────────────────────────────
# DRAWING HELPERS
# ─────────────────────────────────────────────
def draw_arrow(frame, direction):
    cx, cy = FRAME_WIDTH // 2, FRAME_HEIGHT // 2
    color  = (0, 220, 255)
    thick  = 3
    size   = 40

    if direction == "left":
        pts = np.array([[cx-80, cy], [cx-80+size, cy-20], [cx-80+size, cy+20]], np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.line(frame, (cx-80+size, cy), (cx-20, cy), color, thick)
    elif direction == "right":
        pts = np.array([[cx+80, cy], [cx+80-size, cy-20], [cx+80-size, cy+20]], np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.line(frame, (cx+80-size, cy), (cx+20, cy), color, thick)
    elif direction == "up":
        pts = np.array([[cx, cy-130], [cx-20, cy-130+size], [cx+20, cy-130+size]], np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.line(frame, (cx, cy-130+size), (cx, cy-80), color, thick)
    elif direction == "down":
        pts = np.array([[cx, cy+130], [cx-20, cy+130-size], [cx+20, cy+130-size]], np.int32)
        cv2.fillPoly(frame, [pts], color)
        cv2.line(frame, (cx, cy+130-size), (cx, cy+80), color, thick)


def draw_face_oval(frame, progress_pct, complete=False):
    cx, cy = FRAME_WIDTH // 2, FRAME_HEIGHT // 2
    rx, ry = 110, 140
    color  = (0, 255, 120) if complete else (200, 200, 200)
    cv2.ellipse(frame, (cx, cy), (rx, ry), 0, 0, 360, color, 2)
    if not complete and progress_pct > 0:
        end_angle = int(-90 + 360 * progress_pct)
        cv2.ellipse(frame, (cx, cy), (rx, ry), 0, -90, end_angle, (0, 220, 255), 4)


def draw_step_dots(frame, current_step, total_steps):
    # total_steps here = number of poses (each has 2 sub-passes: normal + dark)
    dot_y   = FRAME_HEIGHT - 55
    spacing = 18
    total_w = spacing * (total_steps - 1)
    start_x = (FRAME_WIDTH - total_w) // 2
    for i in range(total_steps):
        x = start_x + i * spacing
        if i < current_step:
            cv2.circle(frame, (x, dot_y), 5, (0, 220, 255), -1)
        elif i == current_step:
            cv2.circle(frame, (x, dot_y), 6, (255, 255, 255), -1)
        else:
            cv2.circle(frame, (x, dot_y), 4, (80, 80, 80), -1)


def draw_led_badge(frame, led_on):
    bx, by = FRAME_WIDTH - 70, 30
    if led_on:
        cv2.circle(frame, (bx, by), 10, (0, 200, 255), -1)
        for deg in range(0, 360, 60):
            a  = np.radians(deg)
            x1 = int(bx + 13 * np.cos(a)); y1 = int(by + 13 * np.sin(a))
            x2 = int(bx + 19 * np.cos(a)); y2 = int(by + 19 * np.sin(a))
            cv2.line(frame, (x1,y1), (x2,y2), (0,160,220), 2)
        cv2.putText(frame, "LED ON",  (bx-28, by+26), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0,200,255), 1)
    else:
        cv2.circle(frame, (bx, by), 10, (55, 55, 55), -1)
        cv2.putText(frame, "LED OFF", (bx-30, by+26), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (100,100,100), 1)


def draw_multiple_face_alert(frame):
    """Red flashing banner when more than one face is detected."""
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, FRAME_HEIGHT//2 - 30), (FRAME_WIDTH, FRAME_HEIGHT//2 + 30), (0, 0, 180), -1)
    cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
    cv2.putText(frame, "⚠  MULTIPLE FACES DETECTED — ONE PERSON ONLY",
                (20, FRAME_HEIGHT//2 + 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)


# ─────────────────────────────────────────────
# iPHONE-STYLE REGISTRATION
# Each pose = normal light pass + dark light pass
# ─────────────────────────────────────────────
def _capture_pass(cap, face_cascade, all_samples, all_labels,
                  step_idx, total_steps, instruction, arrow, dark_sim, pass_label):
    """
    Capture SAMPLES_PER_STEP samples for one lighting condition of one pose.
    dark_sim=True darkens the frame to simulate low light.
    pass_label: shown on screen e.g. "Normal light" / "Low light"
    """
    collected = 0

    # 1.5s countdown
    deadline = cv2.getTickCount()
    while (cv2.getTickCount() - deadline) / cv2.getTickFrequency() < 1.5:
        ret, frame = cap.read()
        if not ret: break
        frame = cv2.flip(frame, 1)
        if dark_sim:
            frame = cv2.convertScaleAbs(frame, alpha=0.3, beta=0)

        overlay = frame.copy()
        cv2.rectangle(overlay, (0,0), (FRAME_WIDTH, FRAME_HEIGHT), (0,0,0), -1)
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

        draw_face_oval(frame, 0)
        draw_step_dots(frame, step_idx, total_steps)

        cv2.putText(frame, instruction,
                    (FRAME_WIDTH//2 - len(instruction)*7//2, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2)
        light_col = (80, 80, 255) if dark_sim else (0, 220, 100)
        cv2.putText(frame, pass_label,
                    (FRAME_WIDTH//2 - 55, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, light_col, 1)
        cv2.putText(frame, "Get ready...", (FRAME_WIDTH//2 - 55, FRAME_HEIGHT - 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160,160,160), 1)
        cv2.imshow("Driver Authentication — Registration", frame)
        cv2.waitKey(1)

    # Capture loop
    while collected < SAMPLES_PER_STEP:
        ret, frame = cap.read()
        if not ret: break
        frame = cv2.flip(frame, 1)

        proc = cv2.convertScaleAbs(frame, alpha=0.3, beta=0) if dark_sim else frame.copy()

        gray  = cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY)
        gray  = cv2.equalizeHist(gray)

        # Use relaxed detection during registration so we can capture angled poses
        raw = cv2.CascadeClassifier(HAAR_CASCADE_PATH).detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60)
        )
        faces = list(raw) if len(raw) > 0 else []

        display = proc.copy()
        draw_face_oval(display, collected / SAMPLES_PER_STEP)
        if arrow:
            draw_arrow(display, arrow)
        draw_step_dots(display, step_idx, total_steps)

        cv2.putText(display, instruction,
                    (FRAME_WIDTH//2 - len(instruction)*7//2, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,220,255), 2)
        light_col = (80, 80, 255) if dark_sim else (0, 220, 100)
        cv2.putText(display, pass_label,
                    (FRAME_WIDTH//2 - 55, 68),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, light_col, 1)

        if len(faces) > 0:
            (x, y, w, h) = faces[0]
            face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
            all_samples.append(face_roi)
            all_labels.append(1)
            collected += 1
            cv2.rectangle(display, (x,y), (x+w,y+h), (0,220,255), 2)
            cv2.putText(display, f"Scanning... {collected}/{SAMPLES_PER_STEP}",
                        (FRAME_WIDTH//2 - 90, FRAME_HEIGHT - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0,220,255), 2)
        else:
            cv2.putText(display, "Align face inside oval",
                        (FRAME_WIDTH//2 - 95, FRAME_HEIGHT - 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100,100,100), 1)

        cv2.imshow("Driver Authentication — Registration", display)
        cv2.waitKey(1)

    return collected


def register_driver(cap, face_cascade, recognizer):
    all_samples = []
    all_labels  = []
    total_steps = len(REGISTRATION_STEPS)

    print("\n[REGISTER] Starting Face ID registration...\n")
    print("  Each pose will be captured in NORMAL light then LOW light.\n")

    for step_idx, step in enumerate(REGISTRATION_STEPS):
        instruction = step["instruction"]
        arrow       = step["arrow"]

        print(f"[STEP {step_idx+1}/{total_steps}] {instruction}")

        # ── Pass 1: Normal light ──
        n = _capture_pass(cap, face_cascade, all_samples, all_labels,
                          step_idx, total_steps, instruction, arrow,
                          dark_sim=False, pass_label="Normal light")
        print(f"    Normal light: {n} samples")

        # ── Pass 2: Dark / low light ──
        n = _capture_pass(cap, face_cascade, all_samples, all_labels,
                          step_idx, total_steps, instruction, arrow,
                          dark_sim=True, pass_label="Low light")
        print(f"    Low light:    {n} samples")

        # Step complete flash
        for _ in range(20):
            ret, frame = cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1)
            draw_face_oval(frame, 1.0, complete=True)
            draw_step_dots(frame, step_idx + 1, total_steps)
            cv2.putText(frame, "Done!", (FRAME_WIDTH//2 - 30, FRAME_HEIGHT//2 + 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,120), 2)
            cv2.imshow("Driver Authentication — Registration", frame)
            cv2.waitKey(1)

        print(f"  Step {step_idx+1} complete\n")

    # ── Train ──
    if len(all_samples) >= 20:
        recognizer.train(all_samples, np.array(all_labels))
        recognizer.save(DRIVER_FACE_FILE)
        log_event("DRIVER_1_REGISTERED",
                  detail=f"{len(all_samples)} samples, {total_steps} poses x2 lighting",
                  result="SUCCESS")
        print(f"[REGISTER] Done! {len(all_samples)} samples across {total_steps} poses × 2 lighting conditions.\n")

        for _ in range(60):
            ret, frame = cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1)
            overlay = frame.copy()
            cv2.rectangle(overlay, (0,0), (FRAME_WIDTH, FRAME_HEIGHT), (0,40,0), -1)
            cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
            cv2.putText(frame, "Driver 1 Registered!", (FRAME_WIDTH//2 - 145, FRAME_HEIGHT//2 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.95, (0,255,120), 2)
            cv2.putText(frame, "Face ID setup complete", (FRAME_WIDTH//2 - 115, FRAME_HEIGHT//2 + 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180,255,180), 1)
            cv2.imshow("Driver Authentication — Registration", frame)
            cv2.waitKey(1)

        return True

    print("[REGISTER] Not enough samples.")
    return False


# ─────────────────────────────────────────────
# LED STATE MACHINE  (flicker-free)
# ─────────────────────────────────────────────
class LedController:
    """
    Debounced LED controller.
    Only switches state after brightness stays consistently
    low/high for LED_CONFIRM_SECS seconds.
    """
    def __init__(self):
        self.led_on          = False
        self._pending_on     = False   # Desired next state
        self._pending_since  = None    # When we first saw the pending state

    def update(self, brightness):
        """Call every frame. Returns True if LED state changed."""
        want_on = brightness < BRIGHTNESS_LOW

        if want_on != self._pending_on:
            # New desired state — start timer
            self._pending_on    = want_on
            self._pending_since = time.time()

        elapsed = time.time() - (self._pending_since or time.time())

        if elapsed >= LED_CONFIRM_SECS and want_on != self.led_on:
            # Confirmed — switch
            self.led_on = want_on
            if self.led_on:
                led_relay_on()
            else:
                led_relay_off()
            return True   # state changed

        return False


# ─────────────────────────────────────────────
# MAIN RECOGNITION LOOP
# ─────────────────────────────────────────────
def run():
    face_cascade = cv2.CascadeClassifier(HAAR_CASCADE_PATH)
    if face_cascade.empty():
        print("[ERROR] Haar cascade not found.")
        return

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("[ERROR] Cannot open camera.")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    init_log()
    recognizer    = create_recognizer()
    driver_loaded = False
    led           = LedController()

    if os.path.exists(DRIVER_FACE_FILE):
        recognizer.read(DRIVER_FACE_FILE)
        driver_loaded = True
        print("[INFO] Driver 1 face data loaded.")
    else:
        print("[INFO] No driver registered. Press R to register.")

    log_event("SYSTEM_STARTED")
    print("[INFO] Ready — R: Register  |  Q: Quit\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = cv2.flip(frame, 1)

        # ── Face detection first (strict, center-zone) ──
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray  = cv2.equalizeHist(gray)
        faces = detect_faces(gray)

        # ── LED (flicker-free, face-aware brightness) ──
        brightness = measure_brightness(frame, faces)
        led.update(brightness)

        # ── Status bar ──
        overlay = frame.copy()
        cv2.rectangle(overlay, (0,0), (FRAME_WIDTH, 75), (0,0,0), -1)
        cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)

        if not driver_loaded:
            cv2.putText(frame, "NO DRIVER REGISTERED", (15, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,165,255), 2)
            cv2.putText(frame, "Press R to set up Face ID", (15, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 1)

        # ── Multiple face alert ──
        if len(faces) > 1:
            draw_multiple_face_alert(frame)
            for (x, y, w, h) in faces:
                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,0,255), 2)
            log_event("MULTIPLE_FACES", detail=f"{len(faces)} faces", result="ALERT")

        # ── Single face recognition ──
        elif len(faces) == 1:
            (x, y, w, h) = faces[0]
            face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))

            if driver_loaded:
                label, confidence = recognizer.predict(face_roi)
                matched = (label == 1 and confidence < MATCH_THRESHOLD)

                box_col  = (0,255,0)  if matched else (0,0,255)
                status   = "DRIVER 1 — MATCHED" if matched else "NOT MATCHED"
                stat_col = (0,255,0)  if matched else (0,0,255)
                sub      = f"{'Access Granted' if matched else 'Access Denied'}  |  Conf: {confidence:.1f}"
                badge    = "MATCH"    if matched else "NO MATCH"

                log_event("FACE_MATCH" if matched else "FACE_NO_MATCH",
                          detail=f"conf={confidence:.1f}",
                          result="GRANTED" if matched else "DENIED")

                cv2.rectangle(frame, (x,y), (x+w,y+h), box_col, 3)
                cv2.putText(frame, status, (15,30), cv2.FONT_HERSHEY_SIMPLEX, 0.85, stat_col, 2)
                cv2.putText(frame, sub,    (15,58), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,255), 1)
                cv2.putText(frame, badge,  (x, y-12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, box_col, 2)
            else:
                cv2.rectangle(frame, (x,y), (x+w,y+h), (0,165,255), 2)

        # ── LED badge ──
        draw_led_badge(frame, led.led_on)

        # ── Brightness readout (helps tuning) ──
        b_col = (0, 60, 255) if brightness < BRIGHTNESS_LOW else (0, 200, 80)
        cv2.putText(frame, f"Brightness: {int(brightness)}",
                    (10, FRAME_HEIGHT - 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, b_col, 1)

        # ── Footer ──
        cv2.putText(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    (10, FRAME_HEIGHT-10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140,140,140), 1)
        cv2.putText(frame, "R: Register  |  Q: Quit",
                    (FRAME_WIDTH-195, FRAME_HEIGHT-10), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140,140,140), 1)

        cv2.imshow("Driver Authentication — Face Recognition", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('r'):
            if register_driver(cap, face_cascade, recognizer):
                driver_loaded = True

    log_event("SYSTEM_STOPPED")
    cap.release()
    cv2.destroyAllWindows()
    print(f"[INFO] Log saved to: {LOG_FILE}")


def create_recognizer():
    return cv2.face.LBPHFaceRecognizer_create()


if __name__ == "__main__":
    run()