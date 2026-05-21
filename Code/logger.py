"""
Multi-Factor Driver Authentication System
Module: SD Card Logger (Upgraded)
----------------------------------------------------------
Logs complete authentication sessions:
  - Face match result
  - Fingerprint match result
  - Final access decision
  - Timestamp of every event
"""

import csv
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
LOG_FILE    = "auth_log.csv"
SESSION_LOG = "session_summary.csv"


# ─────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────
def init_logs():
    """Create log files with headers if they don't exist."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow([
                "Timestamp", "Event", "Detail", "Result"
            ])

    if not os.path.exists(SESSION_LOG):
        with open(SESSION_LOG, "w", newline="") as f:
            csv.writer(f).writerow([
                "Session_ID", "Timestamp",
                "Face_Result", "Face_Confidence",
                "Fingerprint_Result", "Fingerprint_Confidence",
                "Final_Decision"
            ])

    print(f"[LOGGER] Logs ready: {LOG_FILE}, {SESSION_LOG}")


# ─────────────────────────────────────────────
# EVENT LOGGER  (individual events)
# ─────────────────────────────────────────────
def log_event(event: str, detail: str = "N/A", result: str = "N/A"):
    """Log a single system event."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([timestamp, event, detail, result])
    print(f"[LOG] {timestamp} | {event} | {detail} | {result}")


# ─────────────────────────────────────────────
# SESSION LOGGER  (one row per auth attempt)
# ─────────────────────────────────────────────
_session_counter = 0

def log_session(face_matched: bool, face_confidence: float,
                fp_matched: bool, fp_confidence: float):
    """
    Log one complete authentication attempt.
    Final decision = GRANTED only if BOTH face AND fingerprint match.
    """
    global _session_counter
    _session_counter += 1

    timestamp     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    face_result   = "MATCH"    if face_matched else "NO MATCH"
    fp_result     = "MATCH"    if fp_matched   else "NO MATCH"
    final         = "GRANTED"  if (face_matched and fp_matched) else "DENIED"

    with open(SESSION_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            _session_counter, timestamp,
            face_result, f"{face_confidence:.1f}",
            fp_result,   f"{fp_confidence:.1f}",
            final
        ])

    # Print summary box
    print("\n" + "─" * 45)
    print(f"  SESSION #{_session_counter}  —  {timestamp}")
    print(f"  Face      : {face_result:<10} (conf: {face_confidence:.1f})")
    print(f"  Fingerprint: {fp_result:<10} (conf: {fp_confidence:.1f})")
    print(f"  Decision  : ✅ {final}" if final == "GRANTED" else f"  Decision  : ❌ {final}")
    print("─" * 45 + "\n")

    log_event("AUTH_SESSION", detail=f"Face={face_result}, FP={fp_result}", result=final)
    return final


# ─────────────────────────────────────────────
# PRINT RECENT LOG  (optional utility)
# ─────────────────────────────────────────────
def print_recent_sessions(n: int = 5):
    """Print last N session entries from session log."""
    if not os.path.exists(SESSION_LOG):
        print("[LOGGER] No session log found.")
        return

    with open(SESSION_LOG, "r") as f:
        rows = list(csv.reader(f))

    print(f"\n[LOGGER] Last {n} sessions:")
    print("─" * 80) 
    for row in rows[max(1, len(rows)-n):]:
        print("  |  ".join(row))
    print("─" * 80 + "\n")


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_logs()
    log_event("SYSTEM_STARTED")

    # Simulate 3 sessions
    log_session(True,  92.5, True,  95.1)   # Both match → GRANTED
    log_session(False, 35.2, False, 22.0)   # Both fail  → DENIED
    log_session(True,  88.0, False, 30.5)   # Face ok, FP fail → DENIED

    print_recent_sessions()