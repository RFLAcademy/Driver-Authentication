"""
Multi-Factor Driver Authentication System
Module: First-Boot / Setup Wizard
-----------------------------------
Tracks whether initial setup has been completed.
On the very first run, the system must:
  1. Set admin password
  2. Register face
  3. Enroll fingerprint
  4. Register phone number (optional but prompted)

State is saved to disk in SETUP_FLAG_FILE.

Public API:
    is_first_boot()          → bool
    mark_setup_complete()
    clear_setup_flag()       (for testing / full reset)
    mark_step_done(step)
"""

import os
import json
from datetime import datetime

SETUP_FLAG_FILE  = "setup_complete.json"


def _load() -> dict:
    if not os.path.exists(SETUP_FLAG_FILE):
        return {"completed": False, "steps": {}, "first_run_ts": None}
    try:
        with open(SETUP_FLAG_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"completed": False, "steps": {}, "first_run_ts": None}


def _save(data: dict):
    with open(SETUP_FLAG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_first_boot() -> bool:
    """Return True if setup has never been completed."""
    return not _load().get("completed", False)


def mark_setup_complete():
    data = _load()
    data["completed"]    = True
    data["completed_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(data)
    print("[SETUP] First-boot setup marked complete.")


def mark_step_done(step: str):
    """step: 'password' | 'face' | 'fingerprint' | 'phone'"""
    data = _load()
    if "steps" not in data:
        data["steps"] = {}
    data["steps"][step] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if data.get("first_run_ts") is None:
        data["first_run_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(data)
    print(f"[SETUP] Step '{step}' marked done.")


def clear_setup_flag():
    """Reset first-boot flag (e.g. after full data reset)."""
    if os.path.exists(SETUP_FLAG_FILE):
        os.remove(SETUP_FLAG_FILE)
    print("[SETUP] Setup flag cleared — will prompt first-boot wizard on next run.")
