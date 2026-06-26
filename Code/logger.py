"""
Multi-Factor Driver Authentication System
Module: Session Logger (Integrated)
--------------------------------------
Logs individual events and full authentication sessions.

Public API:
    init_logs()
    mark_session_start()
    log_event(event, detail, result)
    log_session(face_matched, face_conf, fp_matched, fp_conf, face_only)
    session_log_lines()          → list of rows (current session)
    print_recent_sessions(n)
"""

import csv
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
LOG_FILE       = "auth_log.csv"
SESSION_LOG    = "session_summary.csv"

# ─────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────
def init_logs():
    """Create log files with headers if they don't exist."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "Event", "Detail", "Result"])

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
# EVENT LOGGER
# ─────────────────────────────────────────────
def log_event(event: str, detail: str = "N/A", result: str = "N/A"):
    """Log a single system event to auth_log.csv."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow([timestamp, event, detail, result])
    print(f"[LOG] {timestamp} | {event} | {detail} | {result}")


# ─────────────────────────────────────────────
# SESSION LOGGER
# ─────────────────────────────────────────────
_session_counter = 0

def log_session(face_matched: bool, face_conf: float,
                fp_matched=None, fp_conf: float = 0.0,
                face_only: bool = False) -> str:
    """
    Log one complete authentication attempt to session_summary.csv.
    face_only=True  → fingerprint skipped (auto-check mode)
    Returns 'GRANTED' or 'DENIED'.
    """
    global _session_counter
    _session_counter += 1

    timestamp   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    face_result = "MATCH" if face_matched else "NO MATCH"

    if face_only:
        fp_result = "SKIPPED"
        fp_conf   = 0.0
        final     = "GRANTED" if face_matched else "DENIED"
    else:
        fp_result = "MATCH" if fp_matched else "NO MATCH"
        final     = "GRANTED" if (face_matched and fp_matched) else "DENIED"

    with open(SESSION_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            _session_counter, timestamp,
            face_result, f"{face_conf:.1f}",
            fp_result,   f"{fp_conf:.1f}",
            final
        ])

    print("\n" + "─" * 48)
    print(f"  SESSION #{_session_counter}  —  {timestamp}")
    print(f"  Face       : {face_result:<10} (conf: {face_conf:.1f})")
    if face_only:
        print(f"  Fingerprint: SKIPPED (auto-check)")
    else:
        print(f"  Fingerprint: {fp_result:<10} (conf: {fp_conf:.1f})")
    icon = "✅" if final == "GRANTED" else "❌"
    print(f"  Decision   : {icon} {final}")
    print("─" * 48 + "\n")

    log_event("AUTH_SESSION",
              detail=f"Face={face_result}, FP={fp_result}, auto={face_only}",
              result=final)
    return final


# ─────────────────────────────────────────────
# CURRENT-SESSION LOG  (since this boot)
# ─────────────────────────────────────────────
# auth_log.csv persists across reboots, so we remember how many rows were
# already present when the program started; everything appended after that
# index belongs to the current session.
_session_start_index = 0

def mark_session_start():
    """Record the current end of the log as this session's starting point.
    Call once at startup, right after init_logs()."""
    global _session_start_index
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            # subtract 1 for the header row
            _session_start_index = max(0, len(list(csv.reader(f))) - 1)
    else:
        _session_start_index = 0
    print(f"[LOGGER] Session start marked at log index {_session_start_index}")


def session_log_lines() -> list:
    """Return every auth_log.csv row recorded since mark_session_start()
    (i.e. the full current-session log), excluding the header."""
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        rows = list(csv.reader(f))[1:]
    return rows[_session_start_index:]


def recent_sessions(n: int = 16) -> list:
    """Return last n rows from session_summary.csv (excluding header)."""
    if not os.path.exists(SESSION_LOG):
        return []
    with open(SESSION_LOG, "r") as f:
        rows = list(csv.reader(f))[1:]
    return rows[-n:]


# ─────────────────────────────────────────────
# PRINT UTILITY
# ─────────────────────────────────────────────
def print_recent_sessions(n: int = 5):
    rows = recent_sessions(n)
    if not rows:
        print("[LOGGER] No session log found.")
        return
    print(f"\n[LOGGER] Last {n} sessions:")
    print("─" * 80)
    for row in rows:
        print("  |  ".join(row))
    print("─" * 80 + "\n")


# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    init_logs()
    log_event("SYSTEM_STARTED")

    log_session(True,  92.5, True,  95.1)
    log_session(False, 35.2, False, 22.0)
    log_session(True,  88.0, face_only=True)

    print_recent_sessions()
