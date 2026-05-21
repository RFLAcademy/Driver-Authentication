"""
Multi-Factor Driver Authentication System
Module: Fingerprint Authentication (Simulation + Real Sensor Ready)
--------------------------------------------------------------------
Simulates fingerprint sensor now.
When hardware arrives, only change the  ── HARDWARE SWAP ──  section.
Supports: R307 / AS608 fingerprint sensor over UART serial.
"""

import time
import random

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
SERIAL_PORT    = "COM3"       # Change to your port tomorrow (check Device Manager)
BAUD_RATE      = 57600        # AS608 / R307 default baud rate
SENSOR_TIMEOUT = 10           # Seconds to wait for finger press
ENROLLED_ID    = 1            # Driver 1 fingerprint slot ID

# Set this to True when real sensor is connected tomorrow
USE_REAL_SENSOR = False


# ─────────────────────────────────────────────
# ── HARDWARE SWAP ──
# Everything below this block stays the same.
# Only this section changes when sensor arrives.
# ─────────────────────────────────────────────
def _real_sensor_verify():
    """
    Real AS608/R307 fingerprint verification via pyfingerprint library.
    Uncomment and use tomorrow when sensor is connected.

    Install when ready:
        pip install pyfingerprint

    Usage:
        from pyfingerprint.pyfingerprint import PyFingerprint
        f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
        if not f.verifyPassword():
            raise ValueError('Sensor password wrong')
        print('Waiting for finger...')
        while not f.readImage():
            pass
        f.convertImage(0x01)
        result = f.searchTemplate()
        positionNumber = result[0]
        if positionNumber == -1:
            return False, -1
        else:
            return True, positionNumber
    """
    pass


# ─────────────────────────────────────────────
# SIMULATION (used until hardware arrives)
# ─────────────────────────────────────────────
_enrolled = False   # Tracks if Driver 1 fingerprint is enrolled in simulation

def enroll_fingerprint():
    """Simulate enrolling Driver 1 fingerprint."""
    global _enrolled
    print("\n[FINGERPRINT] Place finger on sensor to enroll...")
    time.sleep(1.5)   # Simulate sensor read time
    print("[FINGERPRINT] Finger detected. Scanning...")
    time.sleep(1.0)
    print("[FINGERPRINT] Scan complete. Remove finger.")
    time.sleep(0.5)
    print("[FINGERPRINT] Place same finger again to confirm...")
    time.sleep(1.5)
    print("[FINGERPRINT] Confirmed. Driver 1 fingerprint enrolled successfully!\n")
    _enrolled = True
    return True


def verify_fingerprint():
    """
    Simulate fingerprint verification.
    Returns: (matched: bool, confidence: float)
    
    In simulation:
      - If enrolled: 85% chance of match (simulates real-world accuracy)
      - If not enrolled: always fails
    """
    global _enrolled

    if not _enrolled:
        print("[FINGERPRINT] No fingerprint enrolled. Enroll first.")
        return False, 0.0

    print("\n[FINGERPRINT] Place finger on sensor...")
    time.sleep(1.5)
    print("[FINGERPRINT] Scanning...")
    time.sleep(1.0)

    # Simulate match probability
    match_roll = random.random()

    if match_roll < 0.85:
        confidence = round(random.uniform(88.0, 99.5), 1)
        print(f"[FINGERPRINT] MATCH — Driver 1 | Confidence: {confidence}%")
        return True, confidence
    else:
        confidence = round(random.uniform(20.0, 45.0), 1)
        print(f"[FINGERPRINT] NO MATCH — Unknown finger | Confidence: {confidence}%")
        return False, confidence


def is_enrolled():
    return _enrolled


# ─────────────────────────────────────────────
# PUBLIC API  (main.py calls these)
# ─────────────────────────────────────────────
def fingerprint_enroll():
    if USE_REAL_SENSOR:
        pass   # Call _real_sensor_enroll() here tomorrow
    else:
        return enroll_fingerprint()


def fingerprint_verify():
    if USE_REAL_SENSOR:
        pass   # Call _real_sensor_verify() here tomorrow
    else:
        return verify_fingerprint()


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Fingerprint Module Test ===")
    fingerprint_enroll()
    for i in range(3):
        print(f"\n--- Verification attempt {i+1} ---")
        matched, conf = fingerprint_verify()
        print(f"Result: {'GRANTED' if matched else 'DENIED'}")