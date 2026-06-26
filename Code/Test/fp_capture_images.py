"""
Final decisive diagnostic: pulls the RAW captured image straight off the
sensor for each finger, bypassing the matching algorithm entirely. We have
now proven through multiple independent tests that clearDatabase()/
storeTemplate()/getTemplateCount() all behave correctly, and that the
match failure (enrolled finger doesn't match itself, an unrelated finger
matches instead) reproduces across different slots and even completely
unmodified library example scripts. That rules out anything fixable in
this project's Python code. What's left to distinguish:

  (a) The sensor's on-chip MATCHING algorithm/firmware is bad/unreliable
      (defective or low-quality clone chip) - in which case the actual
      captured images should still look like clean, distinct fingerprints.
  (b) The IMAGE CAPTURE itself is corrupted (bad wiring, insufficient/
      noisy power to the sensor during the LED-illuminated capture,
      damaged optical window) - in which case the saved images themselves
      will look garbled, blank, washed out, or suspiciously identical
      regardless of which finger was used.

Run on the Pi:  python3 fp_capture_images.py
Requires Pillow: pip install Pillow

Then copy the resulting PNGs off the Pi (scp, USB, etc.) and look at them.
A real, useable fingerprint image should show clear, sharp ridge/valley
lines covering the frame. Compare the two images to each other.
"""

import os
import sys
import time

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    print("ERROR: pyfingerprint not installed. Run: pip install pyfingerprint pyserial")
    sys.exit(1)

SERIAL_PORT = "/dev/ttyAMA0"
BAUD_RATE   = 57600
TIMEOUT     = 15

# downloadImage() checks that os.path.dirname(destination) is a writable
# directory - a bare filename like "left_index.png" has an empty dirname,
# which fails that check. Use an absolute path in the current directory.
OUT_DIR = os.path.abspath(os.path.dirname(__file__) or ".")


def wait_for_finger(f, label):
    print(f"\n>>> Place finger on sensor ({label})...")
    deadline = time.time() + TIMEOUT
    while not f.readImage():
        if time.time() > deadline:
            print("    TIMEOUT - no finger detected.")
            return False
    return True


def main():
    f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
    if not f.verifyPassword():
        raise ValueError("Sensor password wrong")
    print("Connected OK.")

    left_path = os.path.join(OUT_DIR, "left_index.png")
    right_path = os.path.join(OUT_DIR, "right_index.png")

    if not wait_for_finger(f, "LEFT index"):
        return
    print("Downloading image...")
    f.downloadImage(left_path)
    print(f"Saved {left_path}")
    time.sleep(1)

    input("\nRemove finger, press Enter, then place your RIGHT index...")
    if not wait_for_finger(f, "RIGHT index"):
        return
    print("Downloading image...")
    f.downloadImage(right_path)
    print(f"Saved {right_path}")

    print("\nDone. Copy left_index.png and right_index.png off the Pi and "
          "look at them side by side. They should look like two CLEARLY "
          "DIFFERENT fingerprints with sharp, well-defined ridge lines. "
          "If either looks blank/smeared/garbled, or if they look "
          "suspiciously similar/identical despite being different fingers, "
          "that points to a capture/wiring/power problem rather than the "
          "matching algorithm.")


if __name__ == "__main__":
    main()
