"""
Pi Camera Module — Live Feed Viewer
---------------------------------------
Opens a window showing the live camera feed.
Press Q to quit.

Usage:
    python3 camera_live.py
"""

import os
import sys
import time


def _setup_display():
    """Pick the right Qt/OpenCV backend for the current session."""
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":0"
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, "-c", "import cv2; print(cv2.getBuildInformation())"],
            capture_output=True, text=True, timeout=5)
        build = r.stdout
    except Exception:
        build = ""
    if "GTK" in build:
        os.environ.pop("QT_QPA_PLATFORM", None)
        os.environ["OPENCV_VIDEOIO_PRIORITY_GSTREAMER"] = "0"
    elif os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    else:
        os.environ["QT_QPA_PLATFORM"] = "xcb"


_setup_display()

import cv2
from picamera2 import Picamera2

CAM_W, CAM_H = 640, 480

print("=" * 52)
print("  Pi Camera Module — Live Feed")
print("=" * 52)

print("\n[LIVE] Detecting cameras...")
cameras = Picamera2.global_camera_info()
if not cameras:
    print("[LIVE] FAILED: No cameras detected.")
    sys.exit(1)
print(f"[LIVE] OK: {len(cameras)} camera(s) found.")

print("\n[LIVE] Opening camera...")
picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={"size": (CAM_W, CAM_H), "format": "RGB888"}
)
picam2.configure(config)
picam2.start()
time.sleep(1.0)
print("[LIVE] Camera started. Press Q in the window to quit.")

WIN = "Camera Live Feed"
cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)

frame_count = 0
fps_t0 = time.time()
fps = 0.0

try:
    while True:
        frame = picam2.capture_array()  # RGB888

        # Show capture size + live FPS overlay
        frame_count += 1
        if frame_count % 10 == 0:
            now = time.time()
            fps = 10.0 / (now - fps_t0)
            fps_t0 = now

        cv2.putText(frame, f"{frame.shape[1]}x{frame.shape[0]}  FPS:{fps:.1f}",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, "Press Q to quit",
                    (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

        cv2.imshow(WIN, frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == ord('Q'):
            print("\n[LIVE] Quit requested.")
            break

except KeyboardInterrupt:
    print("\n[LIVE] Interrupted.")

finally:
    picam2.stop()
    picam2.close()
    cv2.destroyAllWindows()
    print("[LIVE] Camera released. Done.")
