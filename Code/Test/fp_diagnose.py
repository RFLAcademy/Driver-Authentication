"""
Standalone fingerprint sensor diagnostic - run this directly on the Pi:

    python3 fp_diagnose.py

Independent of Main.py / fingerprint_sim.py - talks to the R307S directly
so we can see exactly what the sensor itself reports, with no app-level
caching or assumptions in the way. Answers:
  1. How many templates are CURRENTLY stored on the sensor's own flash?
  2. Does clearDatabase() actually wipe them (per a fresh count readback)?
  3. After enrolling ONE new finger, does the sensor really hold exactly 1
     template, and does searchTemplate() then match ONLY that finger?
"""

import time
import sys

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    print("ERROR: pyfingerprint not installed. Run: pip install pyfingerprint pyserial")
    sys.exit(1)

SERIAL_PORT = "/dev/ttyAMA0"
BAUD_RATE   = 57600
TIMEOUT     = 15


def connect():
    f = PyFingerprint(SERIAL_PORT, BAUD_RATE, 0xFFFFFFFF, 0x00000000)
    if not f.verifyPassword():
        raise ValueError("Sensor password wrong")
    return f


def wait_for_finger(f, label):
    print(f"\n>>> Place finger on sensor ({label})...")
    deadline = time.time() + TIMEOUT
    while not f.readImage():
        if time.time() > deadline:
            print("    TIMEOUT - no finger detected.")
            return False
    return True


def main():
    print("=== Fingerprint Sensor Diagnostic ===")
    f = connect()
    print("Connected OK.")
    print(f"Sensor reports security level: {f.getSecurityLevel()}")
    print(f"Sensor storage capacity: {f.getStorageCapacity()}")

    count_before = f.getTemplateCount()
    print(f"\nTemplates stored on sensor BEFORE any action: {count_before}")

    input("\nPress Enter to clear the sensor's database now...")
    cleared = f.clearDatabase()
    count_after_clear = f.getTemplateCount()
    print(f"clearDatabase() returned: {cleared}")
    print(f"Templates stored AFTER clear: {count_after_clear}")
    if count_after_clear != 0:
        print("!!! Sensor did NOT actually clear. This is the root cause - "
              "the sensor itself is failing/ignoring the clear command. "
              "Try power-cycling the sensor (and the Pi) and re-running this script.")
        return

    print("\nDatabase confirmed empty. Now let's enroll ONE finger and verify "
          "ONLY that finger authenticates.")
    input("Press Enter, then place a finger when prompted...")

    if not wait_for_finger(f, "scan 1"):
        return
    f.convertImage(0x01)
    print("Scan 1 captured. Remove finger.")
    time.sleep(2)

    if not wait_for_finger(f, "scan 2 - SAME finger again"):
        return
    f.convertImage(0x02)

    score = f.compareCharacteristics()
    print(f"compareCharacteristics() score: {score}  (0 = scans did not match)")
    if score == 0:
        print("Scans did not match each other - try again with steadier placement.")
        return

    f.createTemplate()
    position = f.storeTemplate()
    count_after_store = f.getTemplateCount()
    print(f"Stored at position: {position}")
    print(f"Templates on sensor AFTER store: {count_after_store}")

    print("\nNow place THE SAME finger you just enrolled to confirm it matches...")
    input("Press Enter, then place that finger...")
    if not wait_for_finger(f, "verify - enrolled finger"):
        return
    f.convertImage(0x01)
    slot, sc = f.searchTemplate()
    print(f"searchTemplate() -> slot={slot}, score={sc}  "
          f"({'MATCH' if slot != -1 else 'NO MATCH'})")

    print("\nNow place a DIFFERENT finger (one you did NOT just enroll) - "
          "this should NOT match...")
    input("Press Enter, then place a different finger...")
    if not wait_for_finger(f, "verify - different finger"):
        return
    f.convertImage(0x01)
    slot2, sc2 = f.searchTemplate()
    print(f"searchTemplate() -> slot={slot2}, score={sc2}  "
          f"({'MATCH (WRONG - this should NOT have matched!)' if slot2 != -1 else 'correctly NO MATCH'})")

    # ── Slot-0 suspicion test ───────────────────────────────────────────
    # If the above match failed even for the just-enrolled finger, slot 0
    # itself may be bad on this sensor (known quirk on some AS608/R307
    # clones). Re-clear and force position 1 instead to test that theory.
    print("\n=== Re-testing with an explicit slot 1 (instead of slot 0) ===")
    f.clearDatabase()
    print(f"Cleared. Template count now: {f.getTemplateCount()}")

    print("\nPlace the SAME finger again to re-enroll at slot 1...")
    input("Press Enter, then place your finger...")
    if not wait_for_finger(f, "slot1 scan 1"):
        return
    f.convertImage(0x01)
    print("Scan 1 captured. Remove finger.")
    time.sleep(2)
    if not wait_for_finger(f, "slot1 scan 2 - SAME finger again"):
        return
    f.convertImage(0x02)
    score3 = f.compareCharacteristics()
    print(f"compareCharacteristics() score: {score3}")
    if score3 == 0:
        print("Scans did not match - try again with steadier placement.")
        return
    f.createTemplate()
    pos1 = f.storeTemplate(1)
    print(f"storeTemplate(1) returned position: {pos1}")
    print(f"Templates on sensor: {f.getTemplateCount()}")

    print("\nPlace the SAME finger to verify against slot 1...")
    input("Press Enter, then place your finger...")
    if not wait_for_finger(f, "verify against slot 1"):
        return
    f.convertImage(0x01)
    slot3, sc3 = f.searchTemplate()
    print(f"searchTemplate() -> slot={slot3}, score={sc3}  "
          f"({'MATCH' if slot3 != -1 else 'NO MATCH'})")
    if slot3 != -1:
        print("\n>>> CONFIRMED: slot 1 works where slot 0 did not. <<<")
    else:
        print("\n>>> Slot 1 also failed - the issue isn't specific to slot 0. <<<")

    # ── Repeatability test ──────────────────────────────────────────────
    # Whatever finger is currently enrolled at slot 1, verify it 3 times
    # in a row with NOTHING else touching the sensor in between. If even
    # the literal same finger flips between MATCH/NO MATCH across these
    # back-to-back reads, the sensor's matching algorithm itself is
    # unreliable - a hardware/firmware quality problem, not anything
    # fixable in fingerprint_sim.py.
    print("\n=== Repeatability test: verify the SAME enrolled finger 3x in a row ===")
    print("Use the exact same finger you just enrolled at slot 1 for all 3 reads.")
    results = []
    for i in range(1, 4):
        input(f"\nPress Enter, then place that finger for read {i}/3...")
        if not wait_for_finger(f, f"repeat read {i}/3"):
            continue
        f.convertImage(0x01)
        s, sc = f.searchTemplate()
        outcome = "MATCH" if s != -1 else "NO MATCH"
        print(f"Read {i}/3 -> slot={s}, score={sc}  ({outcome})")
        results.append(outcome)
        time.sleep(1)

    print(f"\nResults across 3 reads of the SAME finger: {results}")
    if len(set(results)) > 1:
        print(">>> INCONSISTENT - the same finger produced different outcomes across "
              "back-to-back reads. This points to an unreliable sensor (low-quality/"
              "counterfeit module) rather than a software bug. <<<")
    elif results and results[0] == "MATCH":
        print(">>> Consistent MATCH across all 3 reads - matching is reliable for this finger. <<<")
    else:
        print(">>> Consistent NO MATCH across all 3 reads - matching is at least consistent, "
              "but rejecting a finger that should be enrolled. Worth re-enrolling and "
              "re-running this test once more before concluding hardware fault. <<<")

    print("\n=== Done. Review the output above. ===")


if __name__ == "__main__":
    main()
