"""
R307S Fingerprint Sensor — Hardware Test Script
-------------------------------------------------
Tests all 6 wires including the blue TOUCH output.

Usage:
    python3 test_r307s.py

Requirements:
    pip install pyfingerprint RPi.GPIO --break-system-packages

── Pi serial setup (one-time) ──
    sudo raspi-config
      Interface Options → Serial Port
        "Login shell?" → No | "Hardware enabled?" → Yes
    Then reboot.

── Wiring ──
    Red    VCC    → Pin 4  (5V)
    Black  GND    → Pin 6  (GND)
    Yellow TXD    → Pin 10 (RX / GPIO15)
    Green  RXD    → Pin 8  (TX / GPIO14)
    Blue   TOUCH  → Pin 11 (GPIO17)
    White  WAKEUP → leave floating
"""

from pyfingerprint.pyfingerprint import PyFingerprint
import RPi.GPIO as GPIO
import time
import sys

SERIAL_PORT = "/dev/ttyAMA0"
BAUD_RATE   = 57600
TOUCH_GPIO  = 17    # BCM — blue wire
TIMEOUT     = 15    # seconds to wait for finger


# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────
def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(TOUCH_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    print(f"[TEST] GPIO{TOUCH_GPIO} configured as input with pull-up (active-low).")


def connect():
    print(f"[TEST] Connecting to sensor on {SERIAL_PORT}...")
    try:
        f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            print("[TEST] ❌ Password mismatch — check wiring.")
            GPIO.cleanup()
            sys.exit(1)
        print("[TEST] ✅ Sensor connected.")
        return f
    except Exception as e:
        print(f"[TEST] ❌ Connection failed: {e}")
        print("  → serial enabled? (raspi-config)")
        print("  → correct port? (/dev/ttyAMA0 for Pi 4)")
        print("  → TX/RX not swapped?")
        GPIO.cleanup()
        sys.exit(1)


# ─────────────────────────────────────────────
# TEST 1 — Sensor info
# ─────────────────────────────────────────────
def test_sensor_info(f):
    print("\n── Test 1: Sensor info ──")
    print(f"  Templates stored  : {f.getTemplateCount()}")
    print(f"  Storage capacity  : {f.getStorageCapacity()}")
    print("[TEST] ✅ Sensor info OK")


# ─────────────────────────────────────────────
# TEST 2 — Blue TOUCH wire
# ─────────────────────────────────────────────
def test_touch_wire():
    print("\n── Test 2: Blue TOUCH wire ──")
    print(f"[TEST] Place a finger on the sensor (waiting {TIMEOUT}s)...")

    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if GPIO.input(TOUCH_GPIO) == GPIO.LOW:
            print("[TEST] ✅ TOUCH pin went LOW — blue wire working! (active-low confirmed)")
            print("[TEST]    Remove finger...")
            while GPIO.input(TOUCH_GPIO) == GPIO.LOW:
                time.sleep(0.05)
            print("[TEST]    Finger released — pin back HIGH. ✅")
            return True
        time.sleep(0.02)

    print("[TEST] ❌ TOUCH pin never went HIGH.")
    print("  → blue wire on Pin 11 (GPIO17)?")
    print("  → common GND between Pi and sensor?")
    return False


# ─────────────────────────────────────────────
# TEST 3 — Read image over UART
# ─────────────────────────────────────────────
def test_read_image(f):
    print("\n── Test 3: Read image over UART ──")
    print(f"[TEST] Place finger on sensor (waiting {TIMEOUT}s)...")
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if f.readImage():
            f.convertImage(0x01)
            print("[TEST] ✅ Image captured and converted to CharBuffer1.")
            return True
        time.sleep(0.1)
    print("[TEST] ❌ Timed out reading image.")
    return False


# ─────────────────────────────────────────────
# TEST 4 — Touch interrupt → image capture
# ─────────────────────────────────────────────
def test_touch_then_image(f):
    print("\n── Test 4: Touch interrupt → image capture (combined flow) ──")
    print(f"[TEST] Place finger (waiting {TIMEOUT}s)...")
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if GPIO.input(TOUCH_GPIO) == GPIO.LOW:
            print("[TEST] Touch detected — waiting for image to settle...")
            # TOUCH pin goes HIGH before the sensor finishes capturing.
            # Give it 100 ms to stabilise, then poll readImage() a few times.
            time.sleep(0.1)
            for attempt in range(5):
                if f.readImage():
                    f.convertImage(0x01)
                    print(f"[TEST] ✅ Combined flow works perfectly (attempt {attempt+1}).")
                    return True
                time.sleep(0.05)
            print("[TEST] ❌ Touch detected but readImage() failed after retries.")
            return False
        time.sleep(0.02)
    print("[TEST] ❌ No touch detected within timeout.")
    return False


# ─────────────────────────────────────────────
# TEST 5 — Enroll Driver 1
# ─────────────────────────────────────────────
def _wait_finger(f):
    """Wait for touch pin then capture image. Raises TimeoutError."""
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        if GPIO.input(TOUCH_GPIO) == GPIO.LOW:
            if f.readImage():
                return
        time.sleep(0.02)
    raise TimeoutError("No finger detected.")


def test_enroll(f, slot=1):
    print(f"\n── Test 5: Enroll into slot {slot} ──")
    try:
        print("[TEST] Scan 1 — place finger on sensor...")
        _wait_finger(f)
        f.convertImage(0x01)
        print("[TEST] Scan 1 done. Remove finger.")
        time.sleep(1.5)

        print("[TEST] Scan 2 — place SAME finger again...")
        _wait_finger(f)
        f.convertImage(0x02)

        score = f.compareCharacteristics()
        if score == 0:
            print("[TEST] ❌ Scans don't match (score=0). Try again.")
            return False

        print(f"[TEST] Scans matched (score={score}). Saving template...")
        f.createTemplate()
        stored_slot = f.storeTemplate(slot, 1)
        print(f"[TEST] ✅ Enrolled in slot {stored_slot}.")
        return True
    except Exception as e:
        print(f"[TEST] ❌ Enroll failed: {e}")
        return False


# ─────────────────────────────────────────────
# TEST 6 — Verify
# ─────────────────────────────────────────────
def test_verify(f):
    print("\n── Test 6: Verify fingerprint ──")
    print(f"[TEST] Place finger on sensor (waiting {TIMEOUT}s)...")
    try:
        _wait_finger(f)
        f.convertImage(0x01)
        result = f.searchTemplate()
        slot, score = result[0], result[1]
        if slot == -1:
            print("[TEST] ❌ No match found in sensor memory.")
        else:
            print(f"[TEST] ✅ MATCH — Slot {slot} | Score: {score}")
        return slot != -1
    except Exception as e:
        print(f"[TEST] ❌ Verify error: {e}")
        return False


# ─────────────────────────────────────────────
# TEST 7 — Delete template
# ─────────────────────────────────────────────
def test_delete(f, slot=1):
    print(f"\n── Test 7: Delete slot {slot} ──")
    try:
        f.deleteTemplate(slot)
        print(f"[TEST] ✅ Slot {slot} deleted. Templates remaining: {f.getTemplateCount()}")
    except Exception as e:
        print(f"[TEST] ❌ Delete failed: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def run_all_tests():
    print("=" * 52)
    print("  R307S Fingerprint Sensor — Full Hardware Test")
    print("=" * 52)

    setup_gpio()
    f = connect()

    test_sensor_info(f)
    touch_ok = test_touch_wire()
    test_read_image(f)

    if touch_ok:
        test_touch_then_image(f)

    print("\nProceed to enroll Driver 1? [y/N]", end=" ")
    if input().strip().lower() == "y":
        if test_enroll(f, slot=1):
            print("\nVerify now? [y/N]", end=" ")
            if input().strip().lower() == "y":
                test_verify(f)

            print("\nDelete test template from slot 1? [y/N]", end=" ")
            if input().strip().lower() == "y":
                test_delete(f, slot=1)

    GPIO.cleanup()
    print("\n[TEST] All done.")
    print("[TEST] Set USE_REAL_SENSOR = True in fingerprint_sim.py when ready.")


if __name__ == "__main__":
    run_all_tests()
