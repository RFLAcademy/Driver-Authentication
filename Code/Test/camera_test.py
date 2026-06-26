"""
Pi Camera Module — Hardware Test Script
------------------------------------------
Quick standalone test using Picamera2 to confirm the camera
is detected, can be opened, and frames can be captured.

Usage:
    python3 camera_test.py
    python3 camera_test.py --save   (also saves a still photo to test.jpg)

If this fails with "No cameras available", the issue is hardware/config,
not the application code - check:
    vcgencmd get_camera
    rpicam-hello --list-cameras
"""

import sys
import time

print("=" * 52)
print("  Pi Camera Module — Test")
print("=" * 52)

# ── Step 1: List available cameras ──────────────────────────────
try:
    from picamera2 import Picamera2
except ImportError:
    print("[TEST] FAILED: picamera2 not installed.")
    print("  Run: sudo apt install -y python3-picamera2")
    sys.exit(1)

print("\n[TEST] Detecting cameras...")
try:
    cameras = Picamera2.global_camera_info()
except Exception as e:
    print(f"[TEST] FAILED to query cameras: {e}")
    sys.exit(1)

if not cameras:
    print("[TEST] FAILED: No cameras detected.")
    print("  -> Check ribbon cable orientation and seating")
    print("  -> Check 'camera_auto_detect=1' in /boot/firmware/config.txt")
    print("  -> Run: vcgencmd get_camera")
    sys.exit(1)

print(f"[TEST] OK: {len(cameras)} camera(s) found:")
for i, cam in enumerate(cameras):
    print(f"  [{i}] {cam}")

# ── Step 2: Open and configure ──────────────────────────────────
print("\n[TEST] Opening camera 0...")
try:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (640, 480), "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    print("[TEST] OK: Camera started.")
except Exception as e:
    print(f"[TEST] FAILED to open/start camera: {e}")
    sys.exit(1)

# Let exposure / auto-gain settle
time.sleep(1.0)

# ── Step 3: Capture frames ──────────────────────────────────────
print("\n[TEST] Capturing 5 frames...")
ok_count = 0
for i in range(5):
    try:
        frame = picam2.capture_array()
        print(f"  Frame {i+1}: shape={frame.shape}, dtype={frame.dtype}")
        ok_count += 1
    except Exception as e:
        print(f"  Frame {i+1}: FAILED ({e})")
    time.sleep(0.2)

if ok_count == 5:
    print("\n[TEST] OK: All frames captured successfully.")
else:
    print(f"\n[TEST] WARNING: Only {ok_count}/5 frames captured.")

# ── Step 4: Optional - save a still photo ────────────────────────
if "--save" in sys.argv:
    out_path = "test.jpg"
    try:
        picam2.capture_file(out_path)
        print(f"\n[TEST] OK: Saved photo to {out_path}")
    except Exception as e:
        print(f"\n[TEST] FAILED to save photo: {e}")

# ── Cleanup ────────────────────────────────────────────────────
picam2.stop()
picam2.close()
print("\n[TEST] Camera released. Done.")
