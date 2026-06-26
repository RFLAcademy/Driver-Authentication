"""
Multi-Factor Driver Authentication System
Module: Face Detection Constants + Brightness Measurement
-----------------------------------------------------------
Main.py imports this module for the Haar cascade path, the face-match
threshold, the low-light brightness thresholds, and measure_brightness().
All camera I/O, registration capture, and recognition logic live in
Main.py itself - this module only holds shared config and one helper.
"""

import os
import sys

# ─────────────────────────────────────────────
# AUTO DISPLAY SETUP  (must run before import cv2)
# Detects GTK / Wayland / XCB and sets the right backend
# ─────────────────────────────────────────────
def _setup_display():
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()

    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import cv2; print(cv2.getBuildInformation())"],
            capture_output=True, text=True, timeout=5
        )
        build_info = result.stdout
    except Exception:
        build_info = ""

    has_gtk    = "GTK" in build_info
    has_xcb    = "xcb" in build_info.lower() or "X11" in build_info
    is_wayland = session == "wayland"

    if has_gtk:
        os.environ.pop("QT_QPA_PLATFORM", None)
        os.environ["OPENCV_VIDEOIO_PRIORITY_GSTREAMER"] = "0"
        print("[DISPLAY] Backend: GTK")
    elif is_wayland:
        os.environ["QT_QPA_PLATFORM"] = "wayland"
        print("[DISPLAY] Backend: Wayland")
    elif has_xcb:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        print("[DISPLAY] Backend: XCB/X11")
    else:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
        print("[DISPLAY] Backend: XCB (fallback)")

_setup_display()

import cv2
import numpy as np

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

def _find_cascade():
    candidates = [
        "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml",
        "/usr/local/share/opencv4/haarcascades/haarcascade_frontalface_default.xml",
    ]
    try:
        p = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(p):
            return p
    except Exception:
        pass
    for p in candidates:
        if os.path.exists(p):
            return p
    import subprocess
    result = subprocess.run(
        ["find", "/usr", "-name", "haarcascade_frontalface_default.xml"],
        capture_output=True, text=True, timeout=10
    )
    lines = result.stdout.strip().splitlines()
    if lines:
        return lines[0]
    return None

HAAR_CASCADE_PATH = _find_cascade()
if not HAAR_CASCADE_PATH:
    print("[ERROR] haarcascade_frontalface_default.xml not found!")
    print("  Run: sudo apt install -y opencv-data")
    sys.exit(1)
print(f"[INFO] Cascade: {HAAR_CASCADE_PATH}")

DRIVER_FACE_FILE     = "driver1_face.npy"
# LBPH distance threshold - lower distance means a CLOSER match, so a lower
# number here is STRICTER. Only one identity is ever trained (no "negative"
# faces to compare against), so this is the only thing standing between an
# unregistered face and a false accept. 55 was too permissive; tightened to
# reduce false accepts at some risk of the real driver occasionally needing
# a retry in poor lighting (the multi-frame FACE_MATCH_RATIO check in
# Main.py already absorbs most of that risk).
MATCH_THRESHOLD      = 45

# ── Lighting ──
BRIGHTNESS_LOW       = 80
BRIGHTNESS_OK        = 100


def measure_brightness(frame, faces=None):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if faces and len(faces) > 0:
        (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
        return float(np.mean(gray[y:y+h, x:x+w]))
    fh, fw = gray.shape
    cx, cy = fw // 2, fh // 2
    center_bright  = float(np.mean(gray[cy-75:cy+75, cx-100:cx+100]))
    overall_bright = float(np.mean(gray))
    return 0.7 * center_bright + 0.3 * overall_bright
