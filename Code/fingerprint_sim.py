"""
Multi-Factor Driver Authentication System
Module: Fingerprint Authentication (Simulation + Real Sensor Ready)
--------------------------------------------------------------------
IMPORTANT - matching architecture: the enrolled fingerprint TEMPLATE is
stored on the RASPBERRY PI's own disk (FP_TEMPLATE_FILE), not in the
sensor's onboard flash database. Matching is done via a live 1:1
compareCharacteristics() between a freshly-captured scan and the
Pi-stored reference template (uploaded into the sensor's CharBuffer2 each
time), instead of storeTemplate()/searchTemplate()'s flash-backed 1:N
search.

Why: extensive diagnostics on this project's sensor unit (see
fp_diagnose.py, fp_capture_images.py, and testing with the unmodified
pyfingerprint example scripts) proved that storeTemplate()/searchTemplate()
were unreliable on this hardware - an enrolled finger would fail to match
itself while an unrelated finger matched instead, reproducibly, across
multiple template slots and even completely different software. Raw image
capture was independently verified clean and sharp (ruling out a wiring/
power/optics problem), which narrowed the defect down to the flash-backed
store+search path specifically. compareCharacteristics() (1:1, no flash
storage involved) behaved reliably and consistently throughout every
enrollment test in that same investigation, so verification is now routed
through that primitive instead.

Enrollment state is saved to disk (FP_TEMPLATE_FILE) so registration
persists across runs. Enroll once, verify forever - as long as the Pi's
disk holds the template, the sensor's own flash database doesn't matter.

States emitted via state_cb:
  "WAITING"   — sensor is ready, waiting for finger to be placed
  "SCANNING"  — finger detected, image capture in progress
  "LIFT"      — scan done, remove finger
  "DONE"      — result ready (matched / not matched)
"""

import time
import json
import os

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
SERIAL_PORT      = "/dev/ttyAMA0"   # Pi UART — change to COM3 on Windows
BAUD_RATE        = 57600
SENSOR_TIMEOUT   = 15

# The actual fingerprint template (a list of integers from the sensor's
# downloadCharacteristics()) lives here, on the Pi - NOT on the sensor's
# flash. Its existence IS the enrollment state; no separate flag file.
FP_TEMPLATE_FILE = "fingerprint_template.json"

USE_REAL_SENSOR  = True

# AS608/R307-family sensors have a firmware matching-strictness setting,
# 1 (most lenient) .. 5 (strictest, factory default is usually 3). This no
# longer controls match/no-match the way it did when verification went
# through searchTemplate() - compareCharacteristics() just returns a raw
# score that WE threshold ourselves (see FP_COMPARE_MATCH_THRESHOLD below).
# Still set for good measure in case it affects image-acquisition quality.
FP_SECURITY_LEVEL = 3

# compareCharacteristics() returns 0 for a definite non-match and a
# positive accuracy score for a match - higher is a closer match. Observed
# during this project's own testing: genuine same-finger compares scored
# 80-140+, a genuine mismatch scored 0. This threshold sits comfortably
# above the observed noise floor (0) and well below real-match scores,
# but tune it here if real-world testing shows otherwise.
FP_COMPARE_MATCH_THRESHOLD = 40

# How many times to retry the "place same finger again to confirm" scan
# during enrollment before giving up. A single mismatch used to fail the
# whole enrollment, forcing a resend of REGISTER FP over SMS just to get
# a second try at placing the finger consistently.
ENROLL_CONFIRM_ATTEMPTS = 3


# ─────────────────────────────────────────────
# ENROLLMENT PERSISTENCE (Pi-side template storage)
# ─────────────────────────────────────────────
def _save_template(characteristics: list):
    """Save the enrolled finger's characteristics data to the Pi's disk.
    This is the actual biometric template - the sensor's own flash is
    never used as the source of truth for matching in this design."""
    with open(FP_TEMPLATE_FILE, "w") as f:
        json.dump(characteristics, f)
    print(f"[FINGERPRINT] Template saved to {FP_TEMPLATE_FILE} "
          f"({len(characteristics)} values).")


def _load_template():
    """Return the saved characteristics list, or None if nothing enrolled."""
    if not os.path.exists(FP_TEMPLATE_FILE):
        return None
    with open(FP_TEMPLATE_FILE, "r") as f:
        return json.load(f)


def _real_sensor_clear_database() -> bool:
    """Best-effort wipe of the sensor's own flash template database.

    No longer load-bearing for matching (which now lives entirely in
    FP_TEMPLATE_FILE on the Pi), but still run on a full RESET as hygiene -
    e.g. so the unmodified pyfingerprint example scripts (fp_enroll.py/
    fp_verify.py), which DO use flash storage, don't get confused by
    leftover templates from this app's earlier testing.
    """
    try:
        from pyfingerprint.pyfingerprint import PyFingerprint
    except ImportError:
        print("[FINGERPRINT] pyfingerprint not installed - cannot clear sensor database.")
        return False
    try:
        f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            raise ValueError("Sensor password wrong")
        if not f.clearDatabase():
            print("[FINGERPRINT] Sensor reported it could not clear the database.")
            return False
        print("[FINGERPRINT] Sensor template database cleared.")
        return True
    except Exception as e:
        print(f"[FINGERPRINT] Failed to clear sensor database: {e}")
        return False


def _clear_enrollment():
    """Delete the Pi-stored template (the real enrollment state) and
    best-effort wipe the sensor's flash database too (hygiene only)."""
    if os.path.exists(FP_TEMPLATE_FILE):
        os.remove(FP_TEMPLATE_FILE)
        print("[FINGERPRINT] Pi-stored template cleared.")
    if USE_REAL_SENSOR:
        _real_sensor_clear_database()


# ─────────────────────────────────────────────
# HARDWARE: ENROLL
# ─────────────────────────────────────────────
def _real_sensor_enroll():
    """Returns (success: bool, reason: str). The reason is always populated
    (success or failure) so the caller can surface it via SMS/log even when
    no one has eyes on this process's stdout (e.g. the Pi is running the
    kiosk app headless/unattended)."""
    try:
        from pyfingerprint.pyfingerprint import PyFingerprint
        from pyfingerprint.pyfingerprint import FINGERPRINT_CHARBUFFER1
        from pyfingerprint.pyfingerprint import FINGERPRINT_CHARBUFFER2
    except ImportError:
        reason = "pyfingerprint library not installed on the Pi"
        print(f"[FINGERPRINT] {reason}.")
        print("  Run: pip install pyfingerprint pyserial")
        return False, reason

    try:
        f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            raise ValueError("Sensor password wrong")
    except Exception as e:
        reason = f"Sensor init failed: {e}"
        print(f"[FINGERPRINT] {reason}")
        return False, reason

    try:
        f.setSecurityLevel(FP_SECURITY_LEVEL)
    except Exception as e:
        print(f"[FINGERPRINT] Could not set security level {FP_SECURITY_LEVEL} "
              f"(continuing with sensor's current setting): {e}")

    # readImage()/convertImage()/etc. all go through the same unbounded
    # __readPacket() read loop as the rest of the library - if the sensor
    # stops responding mid-scan (comms glitch, bad wiring) these calls can
    # raise with nothing caught here, which used to kill this function
    # outright. Since this runs inside a daemon worker thread with no
    # caller-side try/except (see Main.py _fp_reg_worker), an uncaught
    # exception here silently kills the thread - rs.done never gets set,
    # so the UI/SMS just hangs forever with no error. Bound the wait for
    # a finger and catch sensor errors so enrollment always finishes with
    # a real True/False instead of hanging.
    try:
        print("\n[FINGERPRINT] Place finger on sensor to enroll...")
        deadline = time.monotonic() + SENSOR_TIMEOUT
        while not f.readImage():
            if time.monotonic() > deadline:
                reason = "Timeout - no finger detected on sensor (1st scan)"
                print(f"[FINGERPRINT] {reason}.")
                return False, reason
        f.convertImage(FINGERPRINT_CHARBUFFER1)
        print("[FINGERPRINT] Scan 1 done. Remove finger.")
        time.sleep(2)

        # Retry the confirm scan a few times in this same session instead of
        # failing the whole enrollment on one mismatch - this was the cause
        # of needing to resend REGISTER FP 2-3 times to get a clean enroll.
        confirmed = False
        for attempt in range(1, ENROLL_CONFIRM_ATTEMPTS + 1):
            print(f"[FINGERPRINT] Place same finger again to confirm "
                  f"(attempt {attempt}/{ENROLL_CONFIRM_ATTEMPTS})...")
            deadline = time.monotonic() + SENSOR_TIMEOUT
            while not f.readImage():
                if time.monotonic() > deadline:
                    reason = "Timeout - no finger detected on sensor (confirm scan)"
                    print(f"[FINGERPRINT] {reason}.")
                    return False, reason
            f.convertImage(FINGERPRINT_CHARBUFFER2)

            if f.compareCharacteristics() != 0:
                confirmed = True
                break
            print(f"[FINGERPRINT] Confirm scan didn't match scan 1 - reposition the "
                  f"same finger flat on the sensor and try again.")
            time.sleep(1.5)

        if not confirmed:
            reason = (f"The two scans did not match after {ENROLL_CONFIRM_ATTEMPTS} "
                       f"attempts - hold the same finger flat and steady both times")
            print(f"[FINGERPRINT] {reason}.")
            return False, reason

        # createTemplate() merges CharBuffer1+2 into the final template,
        # placed back in CharBuffer1 - download it from there as plain
        # data and save it on the Pi. The sensor's flash (storeTemplate())
        # is deliberately never touched for matching purposes.
        f.createTemplate()
        characteristics = f.downloadCharacteristics(FINGERPRINT_CHARBUFFER1)
        if not characteristics:
            reason = "Sensor returned empty characteristics data after createTemplate()"
            print(f"[FINGERPRINT] {reason}.")
            return False, reason
    except Exception as e:
        reason = f"Sensor communication failed during enroll: {e}"
        print(f"[FINGERPRINT] {reason}")
        return False, reason

    _save_template(characteristics)
    reason = f"Enrolled OK ({len(characteristics)} values stored on the Pi)"
    print(f"[FINGERPRINT] Driver 1 {reason}\n")
    return True, reason


# ─────────────────────────────────────────────
# HARDWARE: VERIFY
# ─────────────────────────────────────────────
def _real_sensor_verify(state_cb=None):
    characteristics = _load_template()
    if characteristics is None:
        print("[FINGERPRINT] No fingerprint enrolled - nothing to verify against.")
        if state_cb: state_cb("DONE")
        return False, 0.0

    try:
        from pyfingerprint.pyfingerprint import PyFingerprint
        from pyfingerprint.pyfingerprint import FINGERPRINT_CHARBUFFER1
        from pyfingerprint.pyfingerprint import FINGERPRINT_CHARBUFFER2
    except ImportError:
        print("[FINGERPRINT] pyfingerprint not installed.")
        print("  Run: pip install pyfingerprint pyserial")
        if state_cb: state_cb("DONE")
        return False, 0.0

    try:
        f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            raise ValueError("Sensor password wrong")
    except Exception as e:
        print(f"[FINGERPRINT] Sensor init failed: {e}")
        if state_cb: state_cb("DONE")
        return False, 0.0

    try:
        f.setSecurityLevel(FP_SECURITY_LEVEL)
    except Exception as e:
        print(f"[FINGERPRINT] Could not set security level {FP_SECURITY_LEVEL} "
              f"(continuing with sensor's current setting): {e}")

    # Push the Pi-stored reference template into CharBuffer2 up front, so
    # the live scan (captured into CharBuffer1 below) can be compared
    # against it directly via compareCharacteristics() - no flash storage
    # or searchTemplate() involved at all.
    try:
        f.uploadCharacteristics(FINGERPRINT_CHARBUFFER2, characteristics)
    except Exception as e:
        print(f"[FINGERPRINT] Failed to upload reference template to sensor: {e}")
        if state_cb: state_cb("DONE")
        return False, 0.0

    if state_cb: state_cb("WAITING")
    print("\n[FINGERPRINT] Place finger on sensor...")

    deadline = time.monotonic() + SENSOR_TIMEOUT
    while time.monotonic() < deadline:
        try:
            got_image = f.readImage()
        except Exception as e:
            print(f"[FINGERPRINT] Sensor communication failed while waiting for finger: {e}")
            if state_cb: state_cb("DONE")
            return False, 0.0

        if got_image:
            try:
                if state_cb: state_cb("SCANNING")
                print("[FINGERPRINT] Scanning...")
                f.convertImage(FINGERPRINT_CHARBUFFER1)

                if state_cb: state_cb("LIFT")
                print("[FINGERPRINT] Scan complete. Remove finger.")
                time.sleep(0.8)

                score = f.compareCharacteristics()
            except Exception as e:
                print(f"[FINGERPRINT] Sensor communication failed during scan: {e}")
                if state_cb: state_cb("DONE")
                return False, 0.0

            if state_cb: state_cb("DONE")

            confidence = float(min(99.9, score))
            matched = score >= FP_COMPARE_MATCH_THRESHOLD
            if matched:
                print(f"[FINGERPRINT] MATCH | Score: {score} | Confidence: {confidence}%")
            else:
                print(f"[FINGERPRINT] NO MATCH | Score: {score} | Confidence: {confidence}%")
            return matched, confidence

        time.sleep(0.05)

    print("[FINGERPRINT] Timeout — no finger detected.")
    if state_cb: state_cb("DONE")
    return False, 0.0


# ─────────────────────────────────────────────
# SIMULATION
# ─────────────────────────────────────────────
def enroll_fingerprint():
    print("\n[FINGERPRINT] Place finger on sensor to enroll...")
    time.sleep(1.5)
    print("[FINGERPRINT] Finger detected. Scanning...")
    time.sleep(1.0)
    print("[FINGERPRINT] Scan complete. Remove finger.")
    time.sleep(0.5)
    print("[FINGERPRINT] Place same finger again to confirm...")
    time.sleep(1.5)
    print("[FINGERPRINT] Confirmed. Driver 1 fingerprint enrolled successfully!\n")
    _save_template([1])   # placeholder - simulation has no real characteristics data
    return True, "Simulated enrollment OK"


def verify_fingerprint(state_cb=None):
    import random
    if _load_template() is None:
        print("[FINGERPRINT] No fingerprint enrolled. Please enroll first (choose option 1).")
        if state_cb: state_cb("DONE")
        return False, 0.0

    if state_cb: state_cb("WAITING")
    print("\n[FINGERPRINT] Place finger on sensor...")
    time.sleep(1.8)

    if state_cb: state_cb("SCANNING")
    print("[FINGERPRINT] Scanning...")
    time.sleep(1.0)

    if state_cb: state_cb("LIFT")
    print("[FINGERPRINT] Scan complete. Remove finger.")
    time.sleep(0.6)

    match_roll = random.random()
    if match_roll < 0.85:
        confidence = round(random.uniform(88.0, 99.5), 1)
        print(f"[FINGERPRINT] MATCH — Driver 1 | Confidence: {confidence}%")
        matched = True
    else:
        confidence = round(random.uniform(20.0, 45.0), 1)
        print(f"[FINGERPRINT] NO MATCH — Unknown finger | Confidence: {confidence}%")
        matched = False

    if state_cb: state_cb("DONE")
    return matched, confidence


def is_enrolled():
    return _load_template() is not None


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────
def fingerprint_enroll():
    if USE_REAL_SENSOR:
        return _real_sensor_enroll()
    else:
        return enroll_fingerprint()


def fingerprint_verify(state_cb=None):
    if USE_REAL_SENSOR:
        return _real_sensor_verify(state_cb)
    else:
        return verify_fingerprint(state_cb)


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    def _print_state(s):
        print(f"  [STATE] → {s}")

    print("=== Fingerprint Module ===")

    if is_enrolled():
        print("✅ Fingerprint already registered.")
        print("1. Verify fingerprint")
        print("2. Re-enroll (clears existing)")
        choice = input("Enter choice (1/2): ").strip()

        if choice == "1":
            matched, conf = fingerprint_verify(state_cb=_print_state)
            print(f"\nResult: {'✅ GRANTED' if matched else '❌ DENIED'} (conf: {conf}%)")

        elif choice == "2":
            _clear_enrollment()
            ok, reason = fingerprint_enroll()
            print(f"Re-enrollment {'done' if ok else 'FAILED'}: {reason}")
            if ok:
                print("Run the script again to verify.")

        else:
            print("Invalid choice.")

    else:
        print("No fingerprint registered yet.")
        choice = input("Register now? (y/n): ").strip().lower()
        if choice == "y":
            ok, reason = fingerprint_enroll()
            print(f"\nEnrollment {'done' if ok else 'FAILED'}: {reason}")
            if ok:
                print("Run the script again to verify.")
        else:
            print("Exiting.")
