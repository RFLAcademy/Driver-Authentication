"""
Multi-Factor Driver Authentication System
Module: MAIN — Full System Integration
----------------------------------------------------------
Flow:
  1. Camera feed runs with mirroring + auto LED lighting (from FaceDetection.py)
  2. R → iPhone-style face registration (7 pose steps)
  3. E → Enroll fingerprint
  4. A → Authenticate: face check → fingerprint check → relay decision
  5. L → Print recent session log
  6. Q → Quit

All face logic is imported directly from FaceDetection.py
"""

import cv2
import numpy as np
import os
import time
from datetime import datetime

# ── Import our modules ──
import FaceDetection as fd
import fingerprint_sim as fp
import logger as log

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
CAMERA_INDEX  = 0
FRAME_WIDTH   = 640
FRAME_HEIGHT  = 480
RELAY_ENABLED = False   # Set True when ignition relay GPIO is connected


# ─────────────────────────────────────────────
# IGNITION RELAY CONTROL
# ─────────────────────────────────────────────
def relay_on():
    if RELAY_ENABLED:
        pass  # GPIO.output(RELAY_PIN, GPIO.HIGH)
    print("[RELAY] ✅ RELAY ON  — Ignition ENABLED")

def relay_off():
    if RELAY_ENABLED:
        pass  # GPIO.output(RELAY_PIN, GPIO.LOW)
    print("[RELAY] ❌ RELAY OFF — Ignition DISABLED")


# ─────────────────────────────────────────────
# FACE CHECK  (single frame auth, uses fd module)
# ─────────────────────────────────────────────
def check_face(cap, face_cascade, recognizer):
    """
    Grab up to 10 mirrored frames and check if Driver 1 face is present.
    Returns: (matched: bool, confidence: float)
    """
    print("[FACE] Scanning face...")
    for _ in range(10):
        ret, frame = cap.read()
        if not ret:
            continue

        frame = cv2.flip(frame, 1)   # Mirror — same as FaceDetection.py

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray  = cv2.equalizeHist(gray)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(70, 70))

        if len(faces) > 0:
            (x, y, w, h) = faces[0]
            face_roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
            label, confidence = recognizer.predict(face_roi)
            matched = (label == 1 and confidence < fd.MATCH_THRESHOLD)
            print(f"[FACE] {'MATCHED' if matched else 'NO MATCH'} — confidence: {confidence:.1f}")
            return matched, confidence

        time.sleep(0.1)

    print("[FACE] No face detected.")
    return False, 0.0


# ─────────────────────────────────────────────
# FULL AUTHENTICATION FLOW
# ─────────────────────────────────────────────
def authenticate(cap, face_cascade, recognizer):
    print("\n" + "="*50)
    print("  AUTHENTICATION STARTED")
    print("="*50)
    log.log_event("AUTH_START")

    # ── Step 1: Face ──
    print("\n[STEP 1] Face Recognition...")
    face_matched, face_conf = check_face(cap, face_cascade, recognizer)

    if not face_matched:
        print("[AUTH] Face not matched. Access Denied.")
        log.log_session(False, face_conf, False, 0.0)
        relay_off()
        return "DENIED"

    print("[AUTH] Face matched. Proceeding to fingerprint...\n")
    log.log_event("FACE_STEP", detail=f"conf={face_conf:.1f}", result="PASS")

    # ── Step 2: Fingerprint ──
    print("[STEP 2] Fingerprint Verification...")
    fp_matched, fp_conf = fp.fingerprint_verify()

    # ── Step 3: Decision ──
    decision = log.log_session(face_matched, face_conf, fp_matched, fp_conf)
    relay_on() if decision == "GRANTED" else relay_off()
    return decision


# ─────────────────────────────────────────────
# UI OVERLAY  (drawn on top of FaceDetection live feed)
# ─────────────────────────────────────────────
def draw_ui(frame, driver_face_loaded, fp_enrolled, last_result, led_on):
    # Status bar background
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (FRAME_WIDTH, 80), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    # Face + FP status
    face_col = (0, 255, 0) if driver_face_loaded else (0, 0, 255)
    fp_col   = (0, 255, 0) if fp_enrolled        else (0, 0, 255)
    cv2.putText(frame, "Face: Registered" if driver_face_loaded else "Face: Not registered",
                (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, face_col, 2)
    cv2.putText(frame, "FP: Enrolled" if fp_enrolled else "FP: Not enrolled",
                (15, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.6, fp_col, 2)

    # Last auth result
    if last_result == "GRANTED":
        cv2.putText(frame, "LAST: ACCESS GRANTED", (FRAME_WIDTH - 265, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    elif last_result == "DENIED":
        cv2.putText(frame, "LAST: ACCESS DENIED",  (FRAME_WIDTH - 255, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

    # LED badge (top right) — from FaceDetection
    fd.draw_led_badge(frame, led_on)

    # Controls footer
    cv2.putText(frame, "R:Register  E:Enroll FP  A:Auth  L:Log  Q:Quit",
                (10, FRAME_HEIGHT - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160), 1)

    # Timestamp
    cv2.putText(frame, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                (FRAME_WIDTH - 185, FRAME_HEIGHT - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 140, 140), 1)


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def run():
    face_cascade = cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH)
    cap          = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    log.init_logs()
    recognizer         = fd.create_recognizer()
    driver_face_loaded = False
    last_result        = None
    led_on             = False

    # Load saved face if exists
    if os.path.exists(fd.DRIVER_FACE_FILE):
        recognizer.read(fd.DRIVER_FACE_FILE)
        driver_face_loaded = True
        print("[INFO] Driver 1 face loaded.")
    else:
        print("[INFO] No driver registered. Press R to register.")

    log.log_event("SYSTEM_STARTED")
    print("\n[SYSTEM] Driver Authentication System Ready")
    print("[SYSTEM] R=Register  E=Enroll FP  A=Authenticate  L=Log  Q=Quit\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # ── Mirror (from FaceDetection) ──
        frame = cv2.flip(frame, 1)

        # ── Auto LED lighting (from FaceDetection) ──
        brightness = fd.measure_brightness(frame)
        if brightness < fd.BRIGHTNESS_LOW and not led_on:
            led_on = True
            fd.led_relay_on()
        elif brightness >= fd.BRIGHTNESS_OK and led_on:
            led_on = False
            fd.led_relay_off()

        # ── Live face detection display ──
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray  = cv2.equalizeHist(gray)
        faces = face_cascade.detectMultiScale(gray, 1.1, 5, minSize=(70, 70))

        for (x, y, w, h) in faces:
            cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 200, 255), 2)
            cv2.putText(frame, "Face in Frame", (x, y - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 1)

        # ── Draw UI ──
        draw_ui(frame, driver_face_loaded, fp.is_enrolled(), last_result, led_on)
        cv2.imshow("Driver Authentication System", frame)

        key = cv2.waitKey(1) & 0xFF

        if key == ord('q'):
            break

        elif key == ord('r'):
            # Uses iPhone-style registration from FaceDetection.py
            if fd.register_driver(cap, face_cascade, recognizer):
                driver_face_loaded = True

        elif key == ord('e'):
            fp.fingerprint_enroll()

        elif key == ord('a'):
            if not driver_face_loaded:
                print("[AUTH] Register face first (press R)")
            elif not fp.is_enrolled():
                print("[AUTH] Enroll fingerprint first (press E)")
            else:
                last_result = authenticate(cap, face_cascade, recognizer)

        elif key == ord('l'):
            log.print_recent_sessions()

    log.log_event("SYSTEM_STOPPED")
    cap.release()
    cv2.destroyAllWindows()
    print("[INFO] System shut down. Logs saved.")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == "__main__":
    run()