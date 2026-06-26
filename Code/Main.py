"""
Multi-Factor Driver Authentication System
MAIN  --  Full-Screen Single-Window UI  (v9 - SMS Control)

All interaction is via SMS messages sent to the SIM card in the GSM module.
The screen is display-only - no keyboard input required.

SMS COMMANDS  (case-insensitive, send to the GSM SIM number):
    AUTH                        -- Trigger manual authentication
    REGISTER FACE               -- Start face registration
    REGISTER FP                 -- Start fingerprint enrollment
    REGISTER PHONE <10digits>   -- Set alert/control phone number
    SET PASSWORD <pwd>          -- Set / change admin password
    STATUS                      -- Reply with current system status
    LOG                         -- Reply with the full current-session log
                                   (all events since boot, multi-part SMS)
    RESET                       -- Initiate data reset (prompts for confirm)
    RESET CONFIRM <pwd>         -- Confirm and execute reset
    TURN OFF                    -- Kill ignition remotely
    SHUT DOWN                   -- Shut down the Raspberry Pi
    LED ON / LED OFF            -- Manual LED override
    HELP                        -- Reply with command list

Uses Picamera2 (Raspberry Pi Camera Module).
"""

import os, sys

def _setup_display():
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

import cv2, numpy as np, threading, time, subprocess, textwrap
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from picamera2 import Picamera2

import FaceDetection as fd
import fingerprint_sim as fp
import sms_alert as sms
import logger as lg
import relay_controller as relay
import first_boot as fb

# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────
DEFAULT_PASSWORD        = "1234"
TARGET_FPS              = 15
REG_DETECT_EVERY        = 3
SAMPLES_PER_STEP        = 20
HAAR_SCALE              = 1.2
HAAR_NEIGHBORS          = 4
AUTO_AUTH_DENIED_SHOW   = 6.0
SMS_COOLDOWN            = 60.0

# A single denied periodic face check can be a false detection (bad
# lighting, odd head angle, etc.) - the real driver getting flagged as
# unauthorised on one frame is the main complaint this guards against.
# Require this many CONSECUTIVE denied checks in a row before treating
# the driver as actually unauthorised (cutting ignition / alerting).
# Any GRANTED check in between resets the streak back to 0.
AUTO_AUTH_CONFIRM_STREAK = 5
# Delay between the rapid re-checks used while confirming a denial streak
# (much shorter than the normal 5-minute cycle, since we need an answer
# quickly while still undecided).
AUTO_AUTH_RECHECK_DELAY  = 4.0

PASSWORD_FILE           = "admin_password.txt"

# ── Power / activity timing ───────────────────────────────────────
# Pre-auth boot window: after boot, if NEITHER a human is detected NOR
# an SMS interaction occurs within this many seconds, cut power (drop
# the self-power timer latch) and shut down.
BOOT_NO_ACTIVITY_TIMEOUT = 120.0    # 2 min

# Post-auth presence: once the first authentication is done, if no
# person is seen by the camera for this long, cut power and shut down.
PERSON_ABSENT_TIMEOUT    = 120.0    # 2 min

# First-boot setup wizard: if the unit boots into the 4-credential setup
# wizard (password, face, fingerprint, phone) and the user hasn't even
# started the process (no SET PASSWORD received yet) within this long,
# cut power and shut down rather than sit there indefinitely.
FIRST_BOOT_NO_PROGRESS_TIMEOUT = 180.0    # 3 min

# Post-auth 5-minute cycle. The timer starts the moment the first
# authentication completes, and restarts after every auto check-in OR
# any SMS interaction:
#     0:00 .. ACTIVE   -> normal idle UI, watching for SMS interaction
#     ACTIVE .. TOTAL  -> sleep screen
#     >= TOTAL         -> wake + auto face check-in, then cycle repeats
# (5:00 -> 3:00 active window, 3:00 -> 0:00 sleep, check-in at 0:00.)
CYCLE_ACTIVE_SECS        = 120.0    # 5:00 -> 3:00  (active window)
CYCLE_TOTAL_SECS         = 300.0    # full 5 min; auto check-in at the end

# Failed initial-authentication retry/shutdown policy.
AUTH_MAX_ATTEMPTS        = 4        # total attempts before giving up
AUTH_RETRY_DELAY         = 30.0     # seconds between retries

CAM_W, CAM_H = 640, 480
CANVAS_W     = 1280
CANVAS_H     = 720
SIDEBAR_W    = CANVAS_W - CAM_W
CAM_X        = 0
CAM_Y        = (CANVAS_H - CAM_H) // 2

# How long to hold a pending RESET before it expires (seconds)
RESET_CONFIRM_TIMEOUT   = 120.0

# ─────────────────────────────────────────────
# COLOURS  (BGR)
# ─────────────────────────────────────────────
C = dict(
    bg       = (18,  18,  22),
    panel    = (28,  28,  36),
    accent   = (255, 180,  0),
    green    = ( 80, 220, 100),
    red      = ( 60,  60, 220),
    orange   = (  0, 140, 255),
    blue     = (220, 160,   0),
    white    = (240, 240, 240),
    mid      = (140, 140, 150),
    dim      = ( 60,  60,  70),
    granted  = ( 60, 200,  80),
    denied   = ( 50,  50, 220),
    phone_c  = (200, 120, 255),
    sms_c    = ( 80, 200, 255),
)
FONT  = cv2.FONT_HERSHEY_SIMPLEX
FONTB = cv2.FONT_HERSHEY_DUPLEX

# Global text size multiplier applied to every _t()/_tc() call (and matched
# manually in the few spots that call cv2.putText directly). Bumped up for
# readability on small physical displays (e.g. a 3" Pi screen) where the
# 1280x720 canvas gets scaled way down.
FONT_SCALE_MULT = 1.2

# ─────────────────────────────────────────────
# PASSWORD
# ─────────────────────────────────────────────
def _load_password() -> str:
    if os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "r") as f:
            pwd = f.read().strip()
            return pwd if pwd else DEFAULT_PASSWORD
    return DEFAULT_PASSWORD

def _save_password(pwd: str):
    with open(PASSWORD_FILE, "w") as f:
        f.write(pwd)

ADMIN_PASSWORD = _load_password()

# ─────────────────────────────────────────────
# SMS SENDER AUTHORIZATION
# ─────────────────────────────────────────────
# All control happens over SMS with no other input channel, so trust is
# bootstrapped to whichever number sends the first command after boot (or
# after a reset). Every command after that must come from that same
# number, closing the "anyone who texts the SIM can register their own
# face/fingerprint" hole.
OWNER_FILE = "owner_sender.txt"

def _load_owner_sender() -> Optional[str]:
    if os.path.exists(OWNER_FILE):
        with open(OWNER_FILE, "r") as f:
            owner = f.read().strip()
            return owner or None
    return None

def _save_owner_sender(sender: str):
    with open(OWNER_FILE, "w") as f:
        f.write(sender)

def _clear_owner_sender():
    if os.path.exists(OWNER_FILE):
        os.remove(OWNER_FILE)

# ─────────────────────────────────────────────
# DRAWING HELPERS
# ─────────────────────────────────────────────
_OVL = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)

def _blend_rect(img, pt1, pt2, color, alpha=0.55):
    x1, y1 = max(0, pt1[0]), max(0, pt1[1])
    x2, y2 = min(img.shape[1], pt2[0]), min(img.shape[0], pt2[1])
    if x2 <= x1 or y2 <= y1: return
    roi = img[y1:y2, x1:x2]
    _OVL[y1:y2, x1:x2] = color
    cv2.addWeighted(_OVL[y1:y2, x1:x2], alpha, roi, 1 - alpha, 0, roi)
    img[y1:y2, x1:x2] = roi

def _t(img, text, xy, scale, color, thick=1, font=FONT):
    cv2.putText(img, text, xy, font, scale * FONT_SCALE_MULT, color, thick, cv2.LINE_AA)

def _tc(img, text, cy, scale, color, thick=1, font=FONTB, x0=0, x1=None):
    scale = scale * FONT_SCALE_MULT
    x1 = x1 or CANVAS_W
    (tw, th), _ = cv2.getTextSize(text, font, scale, thick)
    tx = x0 + (x1 - x0 - tw) // 2
    cv2.putText(img, text, (tx, cy + th // 2), font, scale, color, thick, cv2.LINE_AA)

def _rect(img, p1, p2, color, fill=-1, thick=1):
    cv2.rectangle(img, p1, p2, color, fill if fill != -1 else thick)

def _bar(img, x, y, w, h, pct, fg, bg=(40, 40, 50)):
    _rect(img, (x, y), (x + w, y + h), bg, -1)
    fw = max(0, int(w * min(pct, 1.0)))
    if fw: _rect(img, (x, y), (x + fw, y + h), fg, -1)
    _rect(img, (x, y), (x + w, y + h), C["dim"], thick=1)

def _oval(img, cx, cy, prog=0.0, done=False):
    col = C["green"] if done else C["mid"]
    cv2.ellipse(img, (cx, cy), (110, 140), 0, 0, 360, col, 2, cv2.LINE_AA)
    if not done and prog > 0:
        cv2.ellipse(img, (cx, cy), (110, 140), 0, -90,
                    int(-90 + 360 * prog), C["accent"], 4, cv2.LINE_AA)

def _fp_icon(img, cx, cy, state, matched=False):
    if state == "SCANNING":
        r = int(14 + 6 * abs((time.time() % 0.6) / 0.3 - 1))
        cv2.circle(img, (cx, cy), r, C["green"], 2, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 10, C["green"], -1, cv2.LINE_AA)
    elif state == "LIFT":
        cv2.circle(img, (cx, cy), 14, C["blue"], 2, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 10, C["blue"], -1, cv2.LINE_AA)
    elif state == "DONE":
        col = C["granted"] if matched else C["denied"]
        cv2.circle(img, (cx, cy), 14, col, -1, cv2.LINE_AA)
        _t(img, "+" if matched else "x", (cx - 6, cy + 6), 0.7, (0, 0, 0), 2)
    else:
        col = C["accent"] if int(time.time() * 2) % 2 == 0 else C["dim"]
        cv2.circle(img, (cx, cy), 14, col, 2, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 10, C["panel"], -1, cv2.LINE_AA)

def _dots(img, cx, y, cur, total):
    sp = 22; ox = cx - (sp * (total - 1)) // 2
    for i in range(total):
        px = ox + i * sp
        if   i < cur:  cv2.circle(img, (px, y), 5, C["accent"], -1, cv2.LINE_AA)
        elif i == cur: cv2.circle(img, (px, y), 7, C["white"],  -1, cv2.LINE_AA)
        else:          cv2.circle(img, (px, y), 4, C["dim"],    -1, cv2.LINE_AA)

def _arrow(img, cx, cy, d):
    col, s = C["accent"], 36
    if d == "left":
        pts = np.array([[cx-70,cy],[cx-70+s,cy-18],[cx-70+s,cy+18]])
        cv2.fillPoly(img, [pts], col)
        cv2.line(img, (cx-70+s, cy), (cx-20, cy), col, 3, cv2.LINE_AA)
    elif d == "right":
        pts = np.array([[cx+70,cy],[cx+70-s,cy-18],[cx+70-s,cy+18]])
        cv2.fillPoly(img, [pts], col)
        cv2.line(img, (cx+70-s, cy), (cx+20, cy), col, 3, cv2.LINE_AA)
    elif d == "up":
        pts = np.array([[cx,cy-110],[cx-18,cy-110+s],[cx+18,cy-110+s]])
        cv2.fillPoly(img, [pts], col)
        cv2.line(img, (cx, cy-110+s), (cx, cy-60), col, 3, cv2.LINE_AA)
    elif d == "down":
        pts = np.array([[cx,cy+110],[cx-18,cy+110-s],[cx+18,cy+110-s]])
        cv2.fillPoly(img, [pts], col)
        cv2.line(img, (cx, cy+110-s), (cx, cy+60), col, 3, cv2.LINE_AA)

def _draw_fp_panel(img):
    cx = CAM_W // 2
    cy = CAM_Y + CAM_H // 2
    _rect(img, (CAM_X, CAM_Y), (CAM_X + CAM_W, CAM_Y + CAM_H), (10, 12, 18), -1)
    pulse = abs((time.time() % 1.2) / 0.6 - 1)
    outer_r = int(130 + 20 * pulse)
    cv2.circle(img, (cx, cy), outer_r, (30, 60, 40), 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 110, (20, 35, 25), -1, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 110, C["green"], 3, cv2.LINE_AA)
    fp_col = C["green"]
    for ri in range(6, 90, 14):
        cv2.ellipse(img, (cx, cy - 10), (ri, int(ri * 1.15)), 0, 200, 340, fp_col, 2, cv2.LINE_AA)
    for ri in range(20, 90, 14):
        cv2.ellipse(img, (cx, cy - 10), (ri, int(ri * 1.15)), 0, 30, 160, fp_col, 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy - 10), 8, fp_col, 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy - 10), 3, fp_col, -1, cv2.LINE_AA)
    scan_y = cy - 90 + int(180 * ((time.time() % 1.5) / 1.5))
    scan_y = max(cy - 90, min(cy + 90, scan_y))
    cv2.line(img, (cx - 100, scan_y), (cx + 100, scan_y), (100, 255, 150), 2, cv2.LINE_AA)
    _blend_rect(img, (cx - 100, scan_y - 6), (cx + 100, scan_y + 6), (50, 180, 80), 0.25)
    _tc(img, "PLACE FINGER ON SENSOR", CAM_Y + CAM_H - 60, 0.52, C["green"], 2, FONTB, 0, CAM_W)
    _tc(img, "Hold still while scanning", CAM_Y + CAM_H - 28, 0.42, C["mid"], 1, FONT, 0, CAM_W)

def _led_badge(img, sx, led_on):
    lx, ly = sx + SIDEBAR_W - 56, 133
    if led_on:
        cv2.circle(img, (lx, ly), 18, (40, 140, 180), -1, cv2.LINE_AA)
        cv2.circle(img, (lx, ly), 13, (0, 200, 255),  -1, cv2.LINE_AA)
        for deg in range(0, 360, 45):
            a = np.radians(deg)
            cv2.line(img,
                (int(lx + 20*np.cos(a)), int(ly + 20*np.sin(a))),
                (int(lx + 27*np.cos(a)), int(ly + 27*np.sin(a))),
                (0, 180, 230), 2, cv2.LINE_AA)
        _t(img, "LED", (lx-14, ly+32), 0.38, (0, 200, 255))
    else:
        cv2.circle(img, (lx, ly), 13, (40, 40, 50), -1, cv2.LINE_AA)
        cv2.circle(img, (lx, ly), 13, C["dim"], 1, cv2.LINE_AA)
        _t(img, "LED", (lx-14, ly+32), 0.55, C["dim"])


# ─────────────────────────────────────────────
# STATE CLASSES
# ─────────────────────────────────────────────
class S:
    IDLE          = 0
    REG_FACE      = 2
    REG_FP        = 3
    AUTHING       = 4
    RESULT        = 5
    RESETTING     = 6
    FIRST_BOOT    = 10
    RETRY_WAIT    = 13

STEPS = [
    ("Look straight at the camera", None),
    ("Slowly turn your head RIGHT",  "right"),
    ("Slowly turn your head LEFT",   "left"),
    ("Tilt your head UP",            "up"),
    ("Tilt your head DOWN",          "down"),
]

@dataclass
class RegState:
    mode:        str  = "face"
    step_idx:    int  = 0
    step_total:  int  = len(STEPS)
    collected:   int  = 0
    sps:         int  = SAMPLES_PER_STEP
    instruction: str  = ""
    arrow: Optional[str] = None
    pass_label:  str  = ""
    dark_pass:   bool = False
    done:        bool = False
    success:     bool = False
    fp_phase:    str  = "IDLE"
    fail_reason: str  = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snap(self):
        with self._lock:
            return (self.mode, self.step_idx, self.step_total, self.collected,
                    self.sps, self.instruction, self.arrow, self.pass_label,
                    self.dark_pass, self.done, self.success, self.fp_phase)

@dataclass
class AuthState:
    face_done:    bool  = False
    face_matched: Optional[bool] = None
    face_conf:    float = 0.0
    fp_done:      bool  = False
    fp_matched:   Optional[bool] = None
    fp_conf:      float = 0.0
    fp_state:     str   = "IDLE"
    complete:     bool  = False
    decision:     Optional[str] = None
    is_auto:      bool  = False
    face_only:    bool  = False
    started_at:   float = field(default_factory=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_fp(self, s):
        with self._lock: self.fp_state = s

    def snap(self):
        with self._lock:
            return (self.face_done, self.face_matched, self.face_conf,
                    self.fp_done, self.fp_matched, self.fp_conf,
                    self.fp_state, self.complete, self.decision,
                    self.is_auto, self.face_only)

@dataclass
class WizardState:
    step:          str   = "welcome"
    pwd_done:  bool = False
    face_done: bool = False
    fp_done:   bool = False
    ph_done:   bool = False


# ─────────────────────────────────────────────
# CAMERA
# ─────────────────────────────────────────────
def _open_camera() -> Picamera2:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(
        main={"size": (CAM_W, CAM_H), "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(1.0)
    print("[INFO] Pi Camera initialised via Picamera2")
    return picam2

def _read_frame(picam2: Picamera2):
    try:
        frame = picam2.capture_array()
        return True, frame
    except Exception as e:
        print(f"[WARN] Frame capture error: {e}")
        return False, None

def _release_camera(picam2: Picamera2):
    try:
        picam2.stop()
        picam2.close()
        print("[INFO] Pi Camera released")
    except Exception:
        pass


# ─────────────────────────────────────────────
# SMS COMMAND POLLER
# ─────────────────────────────────────────────
class SmsCommandPoller:
    """Thin wrapper - delegates to sms.GsmPoller (persistent serial connection)."""

    def __init__(self):
        self._poller = None

    def start(self):
        self._poller = sms.start_poller()

    def pop_command(self):
        if self._poller is not None:
            return self._poller.pop_command()
        return None

    def stop(self):
        if self._poller is not None:
            self._poller.stop()


# ─────────────────────────────────────────────
# BACKGROUND WORKERS
# ─────────────────────────────────────────────
def _face_reg_worker(buf, recognizer, rs: RegState):
    cascade = cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH)
    samples, labels = [], []
    frame_ctr = 0
    for step_idx, (instruction, arrow) in enumerate(STEPS):
        for dark in (False, True):
            with rs._lock:
                rs.step_idx = step_idx; rs.instruction = instruction; rs.arrow = arrow
                rs.pass_label = "Low light" if dark else "Normal light"
                rs.dark_pass = dark; rs.collected = 0
            time.sleep(1.0)
            collected = 0
            while collected < rs.sps:
                frame = buf.read()
                if frame is None: time.sleep(0.05); continue
                frame_ctr += 1
                if frame_ctr % REG_DETECT_EVERY != 0: time.sleep(0.03); continue
                proc = cv2.convertScaleAbs(frame, alpha=0.3, beta=0) if dark else frame
                gray = cv2.equalizeHist(cv2.cvtColor(proc, cv2.COLOR_BGR2GRAY))
                raw  = cascade.detectMultiScale(gray, HAAR_SCALE, HAAR_NEIGHBORS, minSize=(60, 60))
                if len(raw) > 0:
                    (x, y, w, h) = raw[0]
                    roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
                    samples.append(roi); labels.append(1)
                    collected += 1
                    with rs._lock: rs.collected = collected
                time.sleep(0.02)
        with rs._lock: rs.collected = rs.sps
        time.sleep(0.3)
    if len(samples) >= 20:
        recognizer.train(samples, np.array(labels))
        recognizer.save(fd.DRIVER_FACE_FILE)
        lg.log_event("FACE_REGISTERED", detail=f"{len(samples)} samples", result="SUCCESS")
        with rs._lock: rs.done = True; rs.success = True
    else:
        lg.log_event("FACE_REGISTERED", detail="insufficient samples", result="FAIL")
        with rs._lock: rs.done = True; rs.success = False

def _fp_reg_worker(rs: RegState):
    with rs._lock: rs.fp_phase = "WAITING"
    def _cb(s):
        with rs._lock: rs.fp_phase = s
    # fp.fingerprint_enroll() talks to the sensor over serial - if it ever
    # raises (comms glitch, bad wiring), this is a daemon thread with no
    # caller-side handler, so an uncaught exception here would kill the
    # thread silently: rs.done never gets set and the UI/SMS hang forever
    # with no error. Always finish with a real True/False.
    try:
        ok, reason = fp.fingerprint_enroll()
    except Exception as e:
        print(f"[FP_REG] Unexpected error during enrollment: {e}")
        ok, reason = False, f"Unexpected error: {e}"
    _cb("DONE"); time.sleep(0.5)
    # Detail is logged (and surfaced via SMS LOG) so the actual failure
    # reason is visible remotely, not just in this process's stdout which
    # nobody can see once the Pi is running headless/unattended.
    lg.log_event("FP_REGISTERED", detail=reason, result="SUCCESS" if ok else "FAIL")
    with rs._lock: rs.done = True; rs.success = ok; rs.fail_reason = reason

FACE_FRAMES_NEEDED = 8    # consecutive single-face reads required to decide
FACE_SAMPLE_FRAMES = 40   # max frames to spend looking before giving up
FACE_MATCH_RATIO    = 0.7 # fraction of sampled reads that must match

def _auth_worker(buf, cascade, recognizer, auth: AuthState):
    # A single low-confidence frame is not trusted on its own - an
    # unregistered face can occasionally score a fluke low distance for
    # one frame. Require a majority of several consecutive single-face
    # reads to agree before declaring a match.
    matched_hits  = 0
    total_checked = 0
    last_conf     = 0.0

    for _ in range(FACE_SAMPLE_FRAMES):
        frame = buf.read()
        if frame is None: time.sleep(0.05); continue
        gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        faces = cascade.detectMultiScale(gray, HAAR_SCALE, HAAR_NEIGHBORS, minSize=(70, 70))
        if len(faces) == 1:
            (x, y, w, h) = faces[0]
            roi = cv2.resize(gray[y:y+h, x:x+w], (200, 200))
            lbl, conf = recognizer.predict(roi)
            total_checked += 1
            last_conf = conf
            if lbl == 1 and conf < fd.MATCH_THRESHOLD:
                matched_hits += 1
            if total_checked >= FACE_FRAMES_NEEDED:
                break
        elif len(faces) > 1:
            # More than one face in frame - never authenticate on this read.
            total_checked += 1
        time.sleep(0.04)

    face_matched = (total_checked > 0
                     and (matched_hits / total_checked) >= FACE_MATCH_RATIO)
    with auth._lock:
        auth.face_matched = face_matched; auth.face_conf = last_conf; auth.face_done = True

    with auth._lock: face_only = auth.face_only

    if not face_matched:
        # Face failed - never proceed to the fingerprint scan.
        with auth._lock:
            auth.fp_matched = False; auth.fp_conf = 0.0; auth.fp_done = True
            auth.fp_state = "SKIP"
    elif not face_only:
        # Same hang risk as _fp_reg_worker: an uncaught sensor exception
        # here would leave auth.fp_done unset and freeze AUTH forever.
        try:
            m, c = fp.fingerprint_verify(state_cb=auth.set_fp)
        except Exception as e:
            print(f"[AUTH] Unexpected error during fingerprint verify: {e}")
            m, c = False, 0.0
        with auth._lock: auth.fp_matched = m; auth.fp_conf = c; auth.fp_done = True
    else:
        with auth._lock:
            auth.fp_matched = None; auth.fp_conf = 0.0; auth.fp_done = True
            auth.fp_state = "SKIP"

    with auth._lock:
        fm = auth.face_matched; fc = auth.face_conf
        fpm = auth.fp_matched;  fpc = auth.fp_conf

    dec = lg.log_session(fm, fc, fpm, fpc, face_only=face_only)
    with auth._lock: auth.decision = dec; auth.complete = True


# ─────────────────────────────────────────────
# FRAME BUFFER
# ─────────────────────────────────────────────
class FrameBuffer:
    def __init__(self):
        self._lock = threading.Lock(); self._frame = None
    def write(self, f):
        with self._lock: self._frame = f
    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()


# ─────────────────────────────────────────────
# IDLE FACE DETECTOR
# ─────────────────────────────────────────────
class IdleDetector:
    INTERVAL     = 0.50
    LOG_COOLDOWN = 10.0
    # A single noisy frame (blink, head turn, lighting flicker) can score
    # below the match threshold for the registered driver - this is the
    # same false-detection risk _auth_worker guards against with a
    # multi-frame vote. Require this many CONSECUTIVE non-matching reads
    # before flipping the live "driver" status to "unknown" / alerting.
    # Flipping back to "driver" stays immediate since that direction
    # isn't security-sensitive.
    UNKNOWN_CONFIRM_STREAK = 3

    def __init__(self):
        self._cascade    = cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH)
        self._recognizer = None
        self._faces      = []
        self._alert      = None
        self._last_det   = 0.0
        self._last_log   = {}
        self._unmatch_streak = 0
        self._lock       = threading.Lock()

    def set_recognizer(self, recognizer, driver_loaded: bool):
        with self._lock:
            self._recognizer    = recognizer
            self._driver_loaded = driver_loaded

    def update(self, gray_frame):
        now = time.monotonic()
        if now - self._last_det < self.INTERVAL: return
        self._last_det = now
        raw   = self._cascade.detectMultiScale(gray_frame, HAAR_SCALE, HAAR_NEIGHBORS, minSize=(70, 70))
        rects = list(raw) if len(raw) > 0 else []
        faces = []; alert = None
        with self._lock:
            rec     = self._recognizer
            has_mod = getattr(self, "_driver_loaded", False)
        if len(rects) > 1:
            for (x, y, w, h) in rects: faces.append((x, y, w, h, "unknown"))
            alert = "MULTIPLE_FACES"
            self._unmatch_streak = 0
        elif len(rects) == 1:
            (x, y, w, h) = rects[0]
            if not has_mod or rec is None:
                faces.append((x, y, w, h, "no_model"))
                self._unmatch_streak = 0
            else:
                roi   = cv2.resize(gray_frame[y:y+h, x:x+w], (200, 200))
                label, conf = rec.predict(roi)
                matched = (label == 1 and conf < fd.MATCH_THRESHOLD)
                if matched:
                    self._unmatch_streak = 0
                else:
                    self._unmatch_streak += 1
                confirmed_unknown = self._unmatch_streak >= self.UNKNOWN_CONFIRM_STREAK
                status  = "unknown" if confirmed_unknown else "driver"
                faces.append((x, y, w, h, status))
                if confirmed_unknown: alert = "UNKNOWN_FACE"
        else:
            # No face in frame at all - don't let a stale streak from a
            # momentary disappearance carry over into the next sighting.
            self._unmatch_streak = 0
        if alert:
            last_logged = self._last_log.get(alert, 0.0)
            if now - last_logged >= self.LOG_COOLDOWN:
                detail = f"{len(rects)} faces" if alert == "MULTIPLE_FACES" else "unrecognised face"
                lg.log_event(alert, detail=detail, result="ALERT")
                self._last_log[alert] = now
        with self._lock:
            self._faces = faces; self._alert = alert

    def result(self):
        with self._lock: return list(self._faces), self._alert


class SmsThrottle:
    def __init__(self):
        self._last: dict = {}
    def maybe_send(self, alert_type: str, message: str):
        now = time.monotonic()
        if now - self._last.get(alert_type, 0.0) >= SMS_COOLDOWN:
            self._last[alert_type] = now
            sms.send_alert(message)


# ─────────────────────────────────────────────
# CANVAS DRAWING
# ─────────────────────────────────────────────
class Canvas:
    SX = CAM_W; SW = SIDEBAR_W; SH = CANVAS_H

    def __init__(self):
        self._buf = np.zeros((CANVAS_H, CANVAS_W, 3), np.uint8)

    def _fresh(self):
        self._buf[:] = C["bg"]; return self._buf

    def _paste_cam(self, c, f):
        if f is None: return
        c[CAM_Y:CAM_Y+CAM_H, CAM_X:CAM_X+CAM_W] = cv2.resize(f, (CAM_W, CAM_H))

    def _sidebar_base(self, c, face_ok, fp_ok, phone_ok, led_on, bright):
        """
        Fixed layout sidebar. All Y coords are absolute pixels.
        Sidebar: x=640..1280 (640px wide), y=0..720 (720px tall)
        Returns Y where the status section ends (for caller to continue from).
        """
        sx = self.SX   # 640
        sw = self.SW   # 640
        P  = 14        # left padding

        # Background + left border
        _rect(c, (sx, 0), (sx+sw, self.SH), C["panel"], -1)
        cv2.line(c, (sx, 0), (sx, self.SH), C["accent"], 3)

        # ── TITLE  y=0..54 ──────────────────────────────────────────
        _t(c, "DRIVER AUTH", (sx+P, 42), 1.1, C["accent"], 2, FONTB)
        cv2.line(c, (sx+P, 56), (sx+sw-P, 56), C["accent"], 1)

        # ── STATUS ROWS  y=56..200 (3 rows × 42px each) ─────────────
        rows = [
            ("Face",        face_ok,  False),
            ("Fingerprint", fp_ok,    False),
            ("Phone",       phone_ok, True),
        ]
        by = 72
        for lbl, ok, is_phone in rows:
            sym = "OK" if ok else "--"
            col = C["green"] if ok else (C["phone_c"] if is_phone else C["mid"])
            # subtle tinted background for the row
            _blend_rect(c, (sx+P, by-18), (sx+sw-P, by+10), col, 0.07)
            _t(c, sym, (sx+P+4, by),     0.7, col, 2, FONTB)
            _t(c, lbl, (sx+P+62, by),    0.7, col, 1, FONT)
            by += 42

        # ── LED + BRIGHTNESS  y=200..230 ────────────────────────────
        by = 204
        bcol    = C["orange"] if bright < fd.BRIGHTNESS_LOW else C["green"]
        led_col = (0, 200, 255) if led_on else C["dim"]
        _t(c, f"LED: {'ON ' if led_on else 'OFF'}",  (sx+P,     by), 0.65, led_col, 1, FONTB)
        _t(c, f"Lux: {int(bright)}",                 (sx+P+180, by), 0.60, bcol,    1, FONT)

        # ── DIVIDER ─────────────────────────────────────────────────
        by = 226
        cv2.line(c, (sx+P, by), (sx+sw-P, by), C["dim"], 1)
        return by + 8   # caller starts at ~234

    # Total vertical footprint of _draw_sms_panel: header(36) + 10*ROW_H + info box(46).
    # Must stay in sync with ROW_H below - drifting out of sync is what let
    # the panel's bottom info box (RESET PENDING / last command) run past
    # the fixed "Last: GRANTED/DENIED" banner at the bottom of the sidebar
    # and visually overlap it.
    ROW_H = 28
    SMS_PANEL_H = 36 + 10 * ROW_H + 46

    def _draw_sms_panel(self, c, top_y, last_sms_cmd=None, last_sms_time=None,
                        reset_pending=False, reset_expires_at=None):
        """
        Fixed-height SMS command panel (always SMS_PANEL_H px tall starting
        at top_y): header + 9 command rows + ONE info box at the bottom.
        The info box shows RESET PENDING (priority) or the last SMS command
        received, never both - keeping the total height constant so it
        never collides with whatever is drawn below it.
        """
        sx = self.SX
        sw = self.SW
        P  = 14
        by = top_y

        # Section header
        _t(c, "SMS COMMANDS", (sx+P, by+22), 0.75, C["sms_c"], 2, FONTB)
        cv2.line(c, (sx+P, by+28), (sx+sw-P, by+28), C["sms_c"], 1)
        by += 36

        # Command rows — 2-column layout
        # Left col: command (bold accent), Right col: description (dim)
        # Each row is ROW_H px tall (class constant, kept in sync with SMS_PANEL_H)
        ROW_H = self.ROW_H
        cmds = [
            ("AUTH",          "Authenticate now"),
            ("REGISTER FACE", "Register face"),
            ("REGISTER FP",   "Enroll fingerprint"),
            ("STATUS",    "Get system status"),
            ("LOG",       "Full session log"),
            ("TURN OFF",  "Kill ignition"),
            ("SHUT DOWN", "Power off the Pi"),
            ("WAKE UP",   "Wake from sleep"),
            ("RESET",     "Erase all data"),
            ("HELP",      "Full command list"),
        ]
        for cmd_txt, desc in cmds:
            row_top = by
            row_bot = by + ROW_H - 2
            _blend_rect(c, (sx+P, row_top), (sx+sw-P, row_bot), C["accent"], 0.04)
            _t(c, cmd_txt, (sx+P+6,   by+ROW_H-9), 0.56, C["accent"], 2, FONTB)
            _t(c, desc,    (sx+P+208, by+ROW_H-9), 0.48, C["mid"],    1, FONT)
            by += ROW_H

        # ── Single fixed-height info box (46px): RESET PENDING takes
        #    priority, otherwise show the last SMS command received ──
        box_top, box_bot = by + 2, by + 44
        if reset_pending and reset_expires_at is not None:
            rem = max(0, int(reset_expires_at - time.monotonic()))
            _blend_rect(c, (sx+P, box_top), (sx+sw-P, box_bot), (0, 0, 100), 0.85)
            cv2.rectangle(c, (sx+P, box_top), (sx+sw-P, box_bot), C["denied"], 2)
            _tc(c, f"RESET PENDING  confirm in {rem}s",
                (box_top + box_bot) // 2, 0.55, C["denied"], 2, FONTB, sx+P, sx+sw-P)
        elif last_sms_cmd and last_sms_time:
            ago = int(time.monotonic() - last_sms_time)
            _blend_rect(c, (sx+P, box_top), (sx+sw-P, box_bot), C["sms_c"], 0.06)
            cv2.rectangle(c, (sx+P, box_top), (sx+sw-P, box_bot), C["dim"], 1)
            _t(c, "Last:",             (sx+P+6,        box_top+20), 0.55, C["mid"],   1, FONT)
            _t(c, last_sms_cmd[:16],   (sx+P+76,       box_top+20), 0.62, C["sms_c"], 2, FONTB)
            _t(c, f"{ago}s ago",       (sx+sw-P-100,   box_top+38), 0.50, C["dim"],   1, FONT)
        else:
            _rect(c, (sx+P, box_top), (sx+sw-P, box_bot), C["dim"], thick=1)
            _tc(c, "Waiting for SMS command...", (box_top + box_bot) // 2,
                0.50, C["dim"], 1, FONT, sx+P, sx+sw-P)

    def draw_idle(self, cam, face_ok, fp_ok, phone_ok, last, led_on,
                  bright, faces, alert, next_auth_in=None, ignition_on=False,
                  last_sms_cmd=None, last_sms_time=None,
                  reset_pending=False, reset_expires_at=None,
                  last_result_time=None):
        c = self._fresh(); self._paste_cam(c, cam)
        P = 14
        for (x, y, w, h, status) in faces:
            box_col = C["granted"] if status == "driver" else \
                      C["denied"]  if status == "unknown" else C["accent"]
            label   = "Driver"  if status == "driver" else \
                      "Unknown" if status == "unknown" else "Face"
            cv2.rectangle(c, (CAM_X+x, CAM_Y+y), (CAM_X+x+w, CAM_Y+y+h), box_col, 2, cv2.LINE_AA)
            _t(c, label, (CAM_X+x, CAM_Y+y-6), 0.7, box_col, 2)
        if alert == "MULTIPLE_FACES":
            _blend_rect(c, (0, CAM_Y+CAM_H//2-40), (CAM_W, CAM_Y+CAM_H//2+40), (0,0,160), 0.82)
            _tc(c, "MULTIPLE FACES", CAM_Y+CAM_H//2, 1.0, (255,255,255), 2, FONTB, 0, CAM_W)
        elif alert == "UNKNOWN_FACE":
            _blend_rect(c, (0, CAM_Y+CAM_H-68), (CAM_W, CAM_Y+CAM_H), (0,60,120), 0.82)
            _tc(c, "UNKNOWN  Send AUTH", CAM_Y+CAM_H-30, 0.80, (255,220,80), 2, FONTB, 0, CAM_W)
        _t(c, datetime.now().strftime("%H:%M:%S"), (8, CAM_Y+CAM_H-10), 0.65, C["mid"], 1)
        if ignition_on:
            _blend_rect(c, (4, CAM_Y+4), (210, CAM_Y+46), (0,80,0), 0.80)
            cv2.rectangle(c, (4, CAM_Y+4), (210, CAM_Y+46), C["granted"], 2)
            _t(c, "IGNITION ON", (12, CAM_Y+34), 0.80, C["granted"], 2, FONTB)
        top_y = self._sidebar_base(c, face_ok, fp_ok, phone_ok, led_on, bright)
        sx = self.SX; sw = self.SW

        # ── Fixed-height notice strip (36px): alert > auto-check countdown > idle ──
        STRIP_H = 36
        if alert == "MULTIPLE_FACES":
            _blend_rect(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), (0,0,160), 0.75)
            cv2.rectangle(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), C["denied"], 2)
            _tc(c, "MULTIPLE FACES DETECTED", top_y+20, 0.62, (255,180,180), 2, FONTB, sx+P, sx+sw-P)
        elif alert == "UNKNOWN_FACE":
            _blend_rect(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), (0,60,100), 0.75)
            cv2.rectangle(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), (0,130,200), 2)
            _tc(c, "UNKNOWN - Send AUTH", top_y+20, 0.62, (255,220,80), 2, FONTB, sx+P, sx+sw-P)
        elif next_auth_in is not None and face_ok:
            mins = int(next_auth_in)//60; secs = int(next_auth_in)%60
            cd_col = C["denied"] if next_auth_in<30 else (C["orange"] if next_auth_in<60 else C["mid"])
            _rect(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), C["dim"], thick=1)
            _tc(c, f"Auto-check in {mins}:{secs:02d}", top_y+20, 0.55, cd_col, 1, FONT, sx+P, sx+sw-P)
        else:
            _rect(c, (sx+P, top_y), (sx+sw-P, top_y+STRIP_H), C["dim"], thick=1)
            _tc(c, "System Idle", top_y+20, 0.55, C["dim"], 1, FONT, sx+P, sx+sw-P)
        top_y += STRIP_H + 8

        self._draw_sms_panel(c, top_y, last_sms_cmd, last_sms_time, reset_pending, reset_expires_at)
        if last:
            col = C["granted"] if last == "GRANTED" else C["denied"]
            _blend_rect(c, (sx+P, self.SH-52), (sx+sw-P, self.SH-10), col, 0.28)
            cv2.rectangle(c, (sx+P, self.SH-52), (sx+sw-P, self.SH-10), col, 2)
            label = f"Last: {last}"
            if last_result_time:
                ago = max(0, int(time.monotonic() - last_result_time))
                label += f"  ({ago}s ago)" if ago < 60 else f"  ({ago//60}m ago)"
            _tc(c, label, self.SH-31, 0.72, col, 2, FONTB, sx+P, sx+sw-P)
        return c

    def draw_reg_face(self, cam, rs: RegState):
        c = self._fresh()
        (_, si, st, coll, sps, ins, arrow, plabel, dark, done, ok, _) = rs.snap()
        disp = cam.copy() if cam is not None else np.zeros((CAM_H, CAM_W, 3), np.uint8)
        if dark: disp = cv2.convertScaleAbs(disp, alpha=0.35, beta=0)
        self._paste_cam(c, disp)
        cx, cy = CAM_W//2, CANVAS_H//2
        prog = coll/sps if sps else 0
        _oval(c, cx, cy, prog, coll >= sps)
        if arrow: _arrow(c, cx, cy, arrow)
        _dots(c, cx, CANVAS_H-80, si, st)
        _tc(c, ins, 50, 0.90, C["accent"], 2, FONTB, 0, CAM_W)
        acol = (90, 90, 220) if dark else (80, 200, 80)
        _tc(c, plabel, 84, 0.65, acol, 1, FONT, 0, CAM_W)
        if arrow in ("left", "right"):
            _tc(c, "Show Both Eyes to camera", 118, 0.72, C["orange"], 2, FONTB, 0, CAM_W)
        if coll < sps:
            _tc(c, f"Scanning...  {coll}/{sps}", CANVAS_H-52, 0.80, C["accent"], 2, FONTB, 0, CAM_W)
        else:
            _tc(c, "Step complete!", CANVAS_H-52, 0.80, C["green"], 2, FONTB, 0, CAM_W)
        sx = self.SX
        _rect(c, (sx, 0), (sx+self.SW, self.SH), C["panel"], -1)
        cv2.line(c, (sx, 0), (sx, self.SH), C["accent"], 2)
        _t(c, "FACE REGISTRATION", (sx+20, 42), 1.0, C["accent"], 2, FONTB)
        cv2.line(c, (sx+20, 54), (sx+self.SW-20, 54), C["dim"], 1)
        _t(c, f"Step {si+1} of {st}", (sx+20, 88), 0.75, C["white"])
        _t(c, plabel, (sx+20, 114), 0.60, C["mid"])
        _bar(c, sx+20, 134, self.SW-40, 10, coll/sps, C["accent"])
        _t(c, f"{coll}/{sps} samples", (sx+20, 160), 0.58, C["mid"])
        cv2.line(c, (sx+20, 174), (sx+self.SW-20, 174), C["dim"], 1)
        for i, (ins2, _) in enumerate(STEPS):
            iy = 198 + i*42
            d  = (i < si) or (i == si and coll >= sps)
            col = C["green"] if d else (C["accent"] if i == si else C["dim"])
            sym = "[done]" if d else ("[>]" if i == si else "[ ]")
            _t(c, f" {sym}  {ins2}", (sx+14, iy), 0.42, col)
        if done:
            col = C["granted"] if ok else C["denied"]
            msg = "Face Registered!" if ok else "Registration Failed"
            _blend_rect(c, (sx+20, self.SH-80), (sx+self.SW-20, self.SH-44), col, 0.25)
            cv2.rectangle(c, (sx+20, self.SH-80), (sx+self.SW-20, self.SH-44), col, 1)
            _tc(c, msg, (self.SH-80+self.SH-44)//2, 0.6, col, 2, FONTB, sx+20, sx+self.SW-20)
        _t(c, "Auto-completes when done", (sx+14, self.SH-16), 0.55, C["dim"])
        return c

    def draw_reg_fp(self, cam, rs: RegState):
        c = self._fresh(); self._paste_cam(c, cam)
        (*_, done, ok, fp_phase) = rs.snap()
        cx, cy = CAM_W//2, CANVAS_H//2
        _blend_rect(c, (cx-230, cy-110), (cx+230, cy+150), C["panel"], 0.88)
        cv2.rectangle(c, (cx-230, cy-110), (cx+230, cy+150), C["accent"], 2, cv2.LINE_AA)
        _tc(c, "FINGERPRINT ENROLMENT", cy-80, 0.95, C["accent"], 2, FONTB, cx-230, cx+230)
        _fp_icon(c, cx, cy+10, fp_phase, matched=ok)
        lbs = {"WAITING":  "Place your finger on the sensor",
               "SCANNING": "Hold still  Scanning",
               "LIFT":     "Lift your finger",
               "DONE":     "Enrolment complete!",
               "IDLE":     "Preparing sensor"}
        _tc(c, lbs.get(fp_phase, ""), cy+62, 0.75, C["white"], 1, FONT, cx-230, cx+230)
        if done:
            col = C["granted"] if ok else C["denied"]
            _tc(c, "Fingerprint Saved!" if ok else "Enrolment Failed",
                cy+102, 0.82, col, 2, FONTB, cx-230, cx+230)
        sx = self.SX
        _rect(c, (sx, 0), (sx+self.SW, self.SH), C["panel"], -1)
        cv2.line(c, (sx, 0), (sx, self.SH), C["accent"], 2)
        _t(c, "FINGERPRINT ENROLMENT", (sx+20, 42), 0.95, C["accent"], 2, FONTB)
        cv2.line(c, (sx+20, 54), (sx+self.SW-20, 54), C["dim"], 1)
        fp_steps = [("Place finger on sensor",  fp_phase not in ("IDLE", "WAITING")),
                    ("Hold still - scanning",    fp_phase in ("LIFT", "DONE")),
                    ("Lift finger",              fp_phase == "DONE"),
                    ("Template saved",           done and ok)]
        for i, (lbl, d) in enumerate(fp_steps):
            col = C["green"] if d else (C["accent"] if i == 0 else C["dim"])
            _t(c, f" {'[done]' if d else '[ ]'}  {lbl}", (sx+14, 90+i*46), 0.68, col)
        # Surface the actual sensor-reported failure reason here (rather
        # than just "Enrolment Failed") so it's visible on-screen without
        # needing terminal/SSH access to this process's stdout.
        if done and not ok and rs.fail_reason:
            ry = 270
            _t(c, "Reason:", (sx+14, ry), 0.55, C["mid"])
            for i, line in enumerate(textwrap.wrap(rs.fail_reason, 44)[:4]):
                _t(c, line, (sx+14, ry+28+i*26), 0.48, C["denied"])
        _t(c, "Auto-completes when done", (sx+14, self.SH-16), 0.55, C["dim"])
        return c

    def draw_auth(self, cam, auth: AuthState):
        c = self._fresh()
        (fd_, fm, fc, fpd, fpm, fpc, fps, comp, dec, is_auto, face_only) = auth.snap()
        rem = max(0, 15 - (time.monotonic() - auth.started_at))
        show_fp_panel = (not face_only and fd_ and fps not in ("IDLE", "SKIP", "DONE"))
        if show_fp_panel:
            _draw_fp_panel(c)
        else:
            self._paste_cam(c, cam)
        _bar(c, 0, 0, CAM_W, 5, rem/15, C["accent"] if rem > 5 else C["red"])
        if not show_fp_panel:
            fy = CANVAS_H-148
            _blend_rect(c, (16, fy), (CAM_W-16, fy+36), C["panel"], 0.78)
            cv2.rectangle(c, (16, fy), (CAM_W-16, fy+36), C["dim"], 1)
            if not fd_:
                _t(c, "Face  -  scanning...", (30, fy+23), 0.68, C["blue"])
            else:
                col = C["granted"] if fm else C["denied"]
                _t(c, f"Face  -  {'MATCHED' if fm else 'NO MATCH'}  (conf {fc:.0f})", (30, fy+23), 0.68, col, 2)
            fp_y = CANVAS_H-102
            _blend_rect(c, (16, fp_y), (CAM_W-16, fp_y+36), C["panel"], 0.78)
            cv2.rectangle(c, (16, fp_y), (CAM_W-16, fp_y+36), C["dim"], 1)
            if face_only:
                _t(c, "Fingerprint  -  N/A (auto check, face only)", (30, fp_y+23), 0.62, C["dim"])
            else:
                fp_ui = {"WAITING":  ("Place finger on sensor", C["mid"]),
                         "SCANNING": ("Hold still  Scanning",   C["green"]),
                         "LIFT":     ("Lift your finger",        C["blue"]),
                         "IDLE":     ("Fingerprint  -  waiting...", C["mid"]),
                         "SKIP":     ("Fingerprint  -  skipped", C["dim"]),
                         "DONE":     (f"Fingerprint  -  {'MATCHED' if fpm else 'NO MATCH'}  ({fpc:.0f})",
                                      (C["granted"] if fpm else C["denied"]) if fpd else C["mid"])}
                lbl, col = fp_ui.get(fps, ("", C["mid"]))
                _t(c, lbl, (30, fp_y+23), 0.65, col)
        if comp and dec == "DENIED" and is_auto:
            _blend_rect(c, (0, CAM_Y+CAM_H//2-36), (CAM_W, CAM_Y+CAM_H//2+36), (0, 0, 140), 0.88)
            _tc(c, "AUTO-CHECK FAILED", CAM_Y+CAM_H//2-12, 0.7, (255, 80, 80), 3, FONTB, 0, CAM_W)
            _tc(c, "UNAUTHORISED INDIVIDUAL DETECTED",
                CAM_Y+CAM_H//2+22, 0.48, (255, 200, 200), 1, FONT, 0, CAM_W)
        sx = self.SX
        _rect(c, (sx, 0), (sx+self.SW, self.SH), C["panel"], -1)
        cv2.line(c, (sx, 0), (sx, self.SH), C["accent"], 2)
        hdr_col = (0, 180, 255) if is_auto else C["accent"]
        hdr_txt = "AUTO CHECK (FACE)" if is_auto else "AUTHENTICATING"
        _t(c, hdr_txt, (sx+20, 42), 1.1, hdr_col, 2, FONTB)
        if is_auto:
            _t(c, "Periodic face-only re-authentication", (sx+20, 62), 0.58, C["mid"])
        cv2.line(c, (sx+20, 70), (sx+self.SW-20, 70), C["dim"], 1)
        fp_label = "2  Fingerprint" if not face_only else "2  Fingerprint (skipped)"
        rows = [("1  Face Scan", fd_, fm),
                (fp_label,       fpd, fpm if not face_only else None)]
        for i, (lbl, d, m) in enumerate(rows):
            iy = 90 + i*82
            if face_only and i == 1:
                bc = C["dim"]
                _blend_rect(c, (sx+20, iy), (sx+self.SW-20, iy+58), bc, 0.07)
                cv2.rectangle(c, (sx+20, iy), (sx+self.SW-20, iy+58), C["dim"], 1)
                _t(c, lbl, (sx+34, iy+24), 0.65, C["dim"])
                _t(c, "N/A - auto check", (sx+34, iy+46), 0.42, C["dim"])
            else:
                bc = (C["granted"] if m else C["denied"]) if d else \
                     (C["accent"] if i == 0 and not fd_ else C["mid"])
                _blend_rect(c, (sx+20, iy), (sx+self.SW-20, iy+58), bc, 0.13)
                cv2.rectangle(c, (sx+20, iy), (sx+self.SW-20, iy+58), bc if d else C["dim"], 1)
                _t(c, lbl, (sx+34, iy+24), 0.72, bc if d else C["white"])
                if d: _t(c, "PASS" if m else "FAIL", (sx+34, iy+46), 0.65, bc)
        if comp and dec:
            col = C["granted"] if dec == "GRANTED" else C["denied"]
            _blend_rect(c, (sx+20, self.SH-110), (sx+self.SW-20, self.SH-54), col, 0.28)
            cv2.rectangle(c, (sx+20, self.SH-110), (sx+self.SW-20, self.SH-54), col, 2)
            verdict = "ACCESS GRANTED" if dec == "GRANTED" else "UNAUTHORISED"
            _tc(c, verdict, (self.SH-110+self.SH-54)//2, 0.95, col, 3, FONTB, sx+20, sx+self.SW-20)
        _t(c, f"Timeout in {int(rem)+1}s", (sx+20, self.SH-34), 0.55, C["dim"])
        return c

    def draw_result(self, cam, decision):
        c = self._fresh(); self._paste_cam(c, cam)
        col = (0, 60, 0) if decision == "GRANTED" else (60, 0, 0)
        _blend_rect(c, (0, 0), (CANVAS_W, CANVAS_H), col, 0.62)
        text = "ACCESS GRANTED" if decision == "GRANTED" else "ACCESS DENIED"
        tc   = C["granted"] if decision == "GRANTED" else C["denied"]
        sc, th = 1.6 * FONT_SCALE_MULT, 3
        (tw, tth), _ = cv2.getTextSize(text, FONTB, sc, th)
        tx = (CANVAS_W-tw)//2; ty = CANVAS_H//2 + tth//2
        cv2.putText(c, text, (tx+3, ty+3), FONTB, sc, (0, 0, 0), th+2, cv2.LINE_AA)
        cv2.putText(c, text, (tx,   ty),   FONTB, sc, tc,         th,   cv2.LINE_AA)
        sub = "Ignition Enabled" if decision == "GRANTED" else "Ignition Disabled"
        sub_sc = 0.6 * FONT_SCALE_MULT
        (sw, _), _ = cv2.getTextSize(sub, FONT, sub_sc, 1)
        cv2.putText(c, sub, ((CANVAS_W-sw)//2, ty+54), FONT, sub_sc, tc, 1, cv2.LINE_AA)
        return c

    def draw_retry_wait(self, cam, attempt, max_attempts, remaining_secs):
        c = self._fresh(); self._paste_cam(c, cam)
        _blend_rect(c, (0, 0), (CANVAS_W, CANVAS_H), (60, 0, 0), 0.68)
        text = "AUTHENTICATION FAILED"
        tc   = C["denied"]
        sc, th = 1.3 * FONT_SCALE_MULT, 3
        (tw, tth), _ = cv2.getTextSize(text, FONTB, sc, th)
        tx = (CANVAS_W-tw)//2; ty = CANVAS_H//2 - 60
        cv2.putText(c, text, (tx+3, ty+3), FONTB, sc, (0, 0, 0), th+2, cv2.LINE_AA)
        cv2.putText(c, text, (tx,   ty),   FONTB, sc, tc,         th,   cv2.LINE_AA)

        secs = max(0, int(round(remaining_secs)))
        retry_text = f"Retrying in {secs}s..."
        rsc, rth = 1.1 * FONT_SCALE_MULT, 3
        (rw, rh), _ = cv2.getTextSize(retry_text, FONTB, rsc, rth)
        rx = (CANVAS_W-rw)//2; ry = ty + 90
        cv2.putText(c, retry_text, (rx, ry), FONTB, rsc, C["white"], rth, cv2.LINE_AA)

        sub = f"Attempt {attempt} of {max_attempts}"
        sub_sc = 0.6 * FONT_SCALE_MULT
        (sw, _), _ = cv2.getTextSize(sub, FONT, sub_sc, 1)
        cv2.putText(c, sub, ((CANVAS_W-sw)//2, ry+48), FONT, sub_sc, C["mid"], 1, cv2.LINE_AA)
        return c

    def draw_reset(self, cam, done_at):
        c = self._fresh(); self._paste_cam(c, cam)
        _blend_rect(c, (0, 0), (CANVAS_W, CANVAS_H), (60, 0, 0), 0.72)
        _tc(c, "ALL DATA RESET", CANVAS_H//2-20, 1.0, C["denied"], 3)
        _tc(c, "Face + Fingerprint + Phone data deleted", CANVAS_H//2+36, 0.6, C["mid"], 1, FONT)
        rem = max(0.0, 2.5-(time.monotonic()-done_at))
        _tc(c, f"Returning in {rem:.1f}s", CANVAS_H//2+72, 0.5, C["dim"], 1, FONT)
        return c

    def draw_sleep(self):
        c = self._fresh()
        now_dt   = datetime.now()
        time_str = now_dt.strftime("%H:%M")
        date_str = now_dt.strftime("%A, %d %B %Y")
        font     = FONTB
        scale    = 5.5 * FONT_SCALE_MULT
        thick    = 6
        (tw, th), _ = cv2.getTextSize(time_str, font, scale, thick)
        tx = (CANVAS_W - tw) // 2
        ty = CANVAS_H // 2 + th // 2 - 30
        cv2.putText(c, time_str, (tx+2, ty+2), font, scale,
                    (40, 40, 50), thick + 2, cv2.LINE_AA)
        cv2.putText(c, time_str, (tx, ty), font, scale,
                    (220, 220, 230), thick, cv2.LINE_AA)
        ds    = 0.65 * FONT_SCALE_MULT
        dt_th = 1
        (dw, dh), _ = cv2.getTextSize(date_str, FONT, ds, dt_th)
        dx = (CANVAS_W - dw) // 2
        cv2.putText(c, date_str, (dx, ty + th // 2 + 36),
                    FONT, ds, (80, 80, 90), dt_th, cv2.LINE_AA)
        hint = "SMS commands still active while sleeping"
        hs   = 0.38 * FONT_SCALE_MULT
        (hw, _), _ = cv2.getTextSize(hint, FONT, hs, 1)
        cv2.putText(c, hint, ((CANVAS_W - hw) // 2, CANVAS_H - 28),
                    FONT, hs, (45, 45, 55), 1, cv2.LINE_AA)
        return c

    def draw_first_boot(self, cam, ws: WizardState, reg_state=None, shutdown_in=None):
        c = self._fresh(); self._paste_cam(c, cam)
        _blend_rect(c, (0, 0), (CANVAS_W, CANVAS_H), (0, 0, 0), 0.55)
        sx = self.SX
        _rect(c, (sx, 0), (sx+self.SW, self.SH), C["panel"], -1)
        cv2.line(c, (sx, 0), (sx, self.SH), C["accent"], 2)
        _t(c, "FIRST-TIME SETUP", (sx+20, 42), 1.0, C["accent"], 2, FONTB)
        cv2.line(c, (sx+20, 54), (sx+self.SW-20, 54), C["dim"], 1)

        # Pre-password no-progress countdown: only meaningful before the
        # very first step is done, since the watchdog disarms after that.
        if shutdown_in is not None and not ws.pwd_done:
            mm, ss = divmod(max(0, int(shutdown_in)), 60)
            timer_col = C["denied"] if shutdown_in <= 30 else C["accent"]
            cw_t, ch_t = 460, 70
            x1_t = (CAM_W // 2) - cw_t // 2
            y1_t = 14
            _blend_rect(c, (x1_t, y1_t), (x1_t+cw_t, y1_t+ch_t), (0, 0, 0), 0.6)
            cv2.rectangle(c, (x1_t, y1_t), (x1_t+cw_t, y1_t+ch_t), timer_col, 2, cv2.LINE_AA)
            _tc(c, f"Power off in {mm:01d}:{ss:02d} if setup not started",
                y1_t+44, 0.55, timer_col, 2, FONTB, x1_t, x1_t+cw_t)
        steps_info = [
            ("1  Set Password",   ws.pwd_done),
            ("2  Register Face",  ws.face_done),
            ("3  Fingerprint",    ws.fp_done),
            ("4  Phone (opt.)",   ws.ph_done),
        ]
        for i, (lbl, done) in enumerate(steps_info):
            iy  = 80 + i*44
            cur = (ws.step == "password"    and i == 0) or \
                  (ws.step == "face"        and i == 1) or \
                  (ws.step == "fingerprint" and i == 2) or \
                  (ws.step == "phone"       and i == 3)
            col = C["green"] if done else (C["accent"] if cur else C["dim"])
            sym = "[done]" if done else ("[>]" if cur else "[ ]")
            _t(c, f"  {sym}  {lbl}", (sx+14, iy), 0.68, col, 1 if not cur else 2)

        # SMS instructions per step
        cx_area = CAM_W // 2
        cy_area = CANVAS_H // 2

        if ws.step == "welcome":
            cw, ch = 560, 310; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), C["panel"], 0.97)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["accent"], 2, cv2.LINE_AA)
            _tc(c, "Welcome!", cy_area-120, 1.1, C["accent"], 3, FONTB, x1, x2)
            _tc(c, "Driver Authentication System", cy_area-80, 0.68, C["white"], 1, FONT, x1, x2)
            _tc(c, "SMS SETUP - send to this device's SIM:", cy_area-44, 0.62, C["mid"], 1, FONT, x1, x2)
            for i, line in enumerate([
                "SET PASSWORD <yourpassword>",
                "REGISTER PHONE <10digitnumber>",
                "REGISTER FACE",
                "REGISTER FP",
            ]):
                _tc(c, line, cy_area-14+i*32, 0.46, C["accent"], 2, FONTB, x1, x2)
            _tc(c, "Send SET PASSWORD to begin", cy_area+130, 0.68, C["sms_c"], 2, FONTB, x1, x2)

        elif ws.step == "password":
            cw, ch = 520, 220; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), C["panel"], 0.97)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["accent"], 2, cv2.LINE_AA)
            _tc(c, "SET ADMIN PASSWORD", cy_area-80, 0.88, C["accent"], 2, FONTB, x1, x2)
            _tc(c, "Send via SMS:", cy_area-38, 0.62, C["mid"], 1, FONT, x1, x2)
            _tc(c, "SET PASSWORD <yourpassword>", cy_area-6, 0.72, C["sms_c"], 2, FONTB, x1, x2)
            _tc(c, "Min 4 characters", cy_area+30, 0.42, C["mid"], 1, FONT, x1, x2)

        elif ws.step == "face":
            if reg_state is not None:
                return self.draw_reg_face(cam, reg_state)
            cw, ch = 520, 220; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), C["panel"], 0.97)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["accent"], 2, cv2.LINE_AA)
            _tc(c, "REGISTER YOUR FACE", cy_area-80, 0.95, C["accent"], 2, FONTB, x1, x2)
            _tc(c, "Stand in front of the camera, then send:", cy_area-38, 0.62, C["mid"], 1, FONT, x1, x2)
            _tc(c, "REGISTER FACE", cy_area-4, 0.75, C["sms_c"], 2, FONTB, x1, x2)

        elif ws.step == "fingerprint":
            if reg_state is not None:
                return self.draw_reg_fp(cam, reg_state)
            cw, ch = 520, 220; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), C["panel"], 0.97)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["accent"], 2, cv2.LINE_AA)
            _tc(c, "ENROLL FINGERPRINT", cy_area-80, 0.95, C["accent"], 2, FONTB, x1, x2)
            _tc(c, "Place finger on sensor, then send:", cy_area-38, 0.62, C["mid"], 1, FONT, x1, x2)
            _tc(c, "REGISTER FP", cy_area-4, 0.75, C["sms_c"], 2, FONTB, x1, x2)

        elif ws.step == "phone":
            cw, ch = 520, 220; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), C["panel"], 0.97)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["phone_c"], 2, cv2.LINE_AA)
            _tc(c, "REGISTER PHONE (OPTIONAL)", cy_area-80, 0.82, C["phone_c"], 2, FONTB, x1, x2)
            _tc(c, "Send via SMS:", cy_area-38, 0.62, C["mid"], 1, FONT, x1, x2)
            _tc(c, "REGISTER PHONE <10digits>", cy_area-4, 0.72, C["sms_c"], 2, FONTB, x1, x2)
            _tc(c, "Or send SKIP to continue without phone", cy_area+34, 0.60, C["dim"], 1, FONT, x1, x2)

        elif ws.step == "done":
            cw, ch = 520, 240; x1 = cx_area-cw//2; y1 = cy_area-ch//2
            x2 = x1+cw; y2 = y1+ch
            _blend_rect(c, (x1, y1), (x2, y2), (0, 40, 0), 0.92)
            cv2.rectangle(c, (x1, y1), (x2, y2), C["granted"], 2, cv2.LINE_AA)
            _tc(c, "Setup Complete!", cy_area-60, 1.2, C["granted"], 3, FONTB, x1, x2)
            _tc(c, "System is ready.", cy_area-10, 0.72, C["white"], 1, FONT, x1, x2)
            _tc(c, "Send AUTH to authenticate", cy_area+30, 0.68, C["sms_c"], 2, FONTB, x1, x2)

        # Sidebar note
        _t(c, "Send HELP for command list", (sx+14, self.SH-16), 0.36, C["sms_c"])
        return c


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def run():
    global ADMIN_PASSWORD

    relay.relay_init()
    relay.timer_latch_on()
    lg.log_event("TIMER_LATCH", detail="activated on startup", result="ON")

    sms_poller = SmsCommandPoller()
    sms_poller.start()

    try:
        picam2 = _open_camera()
    except Exception as e:
        print(f"[ERROR] Failed to open Pi Camera: {e}")
        sms_poller.stop()
        relay.relay_shutdown()
        return

    lg.init_logs()
    lg.mark_session_start()   # everything logged after this is "this session"
    recognizer         = cv2.face.LBPHFaceRecognizer_create()
    driver_face_loaded = False
    last_result        = None
    last_result_time   = 0.0
    buf                = FrameBuffer()
    cb                 = Canvas()
    idle_det           = IdleDetector()
    sms_throttle       = SmsThrottle()
    ignition_active    = False

    state        = S.IDLE
    reg_state:   Optional[RegState]  = None
    auth_state:  Optional[AuthState] = None
    wizard_state: Optional[WizardState] = None

    flash_until   = 0.0
    reset_done_at = 0.0

    led_on    = False
    led_timer = 0.0
    led_manual_override = False   # True when set via SMS

    reg_done_at = 0.0
    REG_LINGER  = 1.5

    auto_denied_until = 0.0
    auto_fail_streak  = 0      # consecutive DENIED periodic auto-checks
    auto_recheck_at   = 0.0    # when to fire the next rapid confirm re-check

    session_auth_done     = False
    first_detect_detected = False
    auth_attempts         = 0      # failed initial-auth attempts so far
    auth_retry_at         = 0.0    # when to fire the next retry (0 = none scheduled)

    owner_sender = _load_owner_sender()   # bound controller number, or None pre-bootstrap

    # ── Power / cycle timing state ────────────────────────────────
    # last_interaction / last_person_time are seeded at boot so the
    # pre-auth boot window counts down from startup.
    # NOTE: all of last_interaction/last_person_time/first_boot_started_at
    # and every other duration timer below use time.monotonic(), NOT
    # time.time(). On a Pi with no RTC, the wall clock starts wrong at
    # boot and gets stepped (jumped, not slewed) by NTP the moment the
    # network comes up - which made every timeout/countdown in this app
    # jump or fire early. monotonic() is immune to that; it only ever
    # moves forward at a steady rate from an arbitrary reference point,
    # so it's the right clock for "how much time has elapsed" math.
    # Wall-clock time.time()/datetime.now() is still used for log/SMS
    # timestamps (ts_str etc.) - those should show real calendar time.
    last_interaction = time.monotonic()   # last SMS command received
    last_person_time = time.monotonic()   # last time a human was seen on camera
    first_boot_started_at = time.monotonic()   # when the FIRST_BOOT wizard began
    cycle_start      = None          # set when the first auth completes
    sleeping         = False         # derived from the cycle each frame
    power_off_reason = None          # set -> break loop -> drop the latch

    # Reset confirm tracking
    reset_pending       = False
    reset_pending_at    = 0.0
    reset_expires_at    = 0.0

    # SMS UI state
    last_sms_cmd  = None
    last_sms_time = None

    if os.path.exists(fd.DRIVER_FACE_FILE):
        recognizer.read(fd.DRIVER_FACE_FILE)
        driver_face_loaded = True
        print("[INFO] Driver face loaded.")
    idle_det.set_recognizer(recognizer, driver_face_loaded)

    if fb.is_first_boot():
        wizard_state = WizardState()
        state = S.FIRST_BOOT
        print("[SETUP] First boot detected - starting wizard.")
    else:
        lg.log_event("SYSTEM_STARTED")

    WIN = "Driver Authentication System"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(WIN, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    frame_interval = 1.0 / TARGET_FPS
    last_render    = 0.0

    # ─────────────────────────────────────────
    # HELP MESSAGE TEXT
    # ─────────────────────────────────────────
    HELP_TEXT = (
        "COMMANDS: AUTH | REGISTER FACE [<pwd> if re-registering] | "
        "REGISTER FP [<pwd> if re-enrolling] | "
        "REGISTER PHONE <num> | SET PASSWORD <pwd> | "
        "STATUS | LOG | RESET | RESET CONFIRM <pwd> | "
        "TURN OFF | SHUT DOWN | LED ON | LED OFF | HELP"
    )

    def _status_text():
        face_s = "YES" if driver_face_loaded else "NO"
        fp_s   = "YES" if fp.is_enrolled() else "NO"
        ph_s   = sms.load_phone() or "NOT SET"
        ign_s  = "ON" if ignition_active else "OFF"
        led_s  = "ON" if led_on else "OFF"
        return (f"STATUS: Face={face_s} FP={fp_s} Phone={ph_s} "
                f"Ignition={ign_s} LED={led_s} "
                f"State={'BUSY' if state != S.IDLE else 'IDLE'}")

    # ─────────────────────────────────────────
    # SMS COMMAND DISPATCHER
    # ─────────────────────────────────────────
    def handle_sms_command(cmd_obj):
        """
        Process one SmsCommand. All mutation of shared state happens here
        (called from the main thread only - no concurrency issues).
        """
        nonlocal state, reg_state, auth_state, wizard_state
        nonlocal driver_face_loaded, session_auth_done, first_detect_detected
        nonlocal ignition_active, led_on, led_manual_override, led_timer
        nonlocal reset_done_at, flash_until
        nonlocal reset_pending, reset_pending_at, reset_expires_at
        nonlocal last_sms_cmd, last_sms_time, reg_done_at
        nonlocal sleeping, last_interaction, cycle_start
        nonlocal auth_attempts, auth_retry_at
        nonlocal auto_fail_streak, auto_recheck_at
        nonlocal recognizer, owner_sender
        global ADMIN_PASSWORD

        cmd    = cmd_obj.cmd
        args   = cmd_obj.args
        sender = cmd_obj.sender
        now    = time.monotonic()

        last_sms_cmd  = cmd
        last_sms_time = now

        # Any inbound SMS counts as an "interaction": it keeps the unit
        # alive during the pre-auth boot window, and once the post-auth
        # cycle is running it wakes the unit and restarts the 5-min timer.
        last_interaction = now
        if cycle_start is not None:
            cycle_start = now
            sleeping    = False

        # Record every interaction in the session log (redact secrets so
        # passwords never land in auth_log.csv or get texted back via LOG).
        if cmd in ("SET PASSWORD", "RESET CONFIRM", "REGISTER FACE", "REGISTER FP"):
            _log_detail = "<redacted>"
        else:
            _log_detail = args.strip()[:40]
        lg.log_event("SMS_RX", detail=f"{cmd} {_log_detail}".strip(),
                     result=f"from {sender}")

        def reply(msg):
            sms.send_reply(sender, msg)

        # ── SENDER AUTHORIZATION ─────────────────────────────────────
        # HELP is always answered (it's just the command list). Everything
        # else is locked to a single bound controller number: the first
        # sender to issue any non-HELP command after boot/reset becomes the
        # owner, and every subsequent command must come from that number.
        if cmd != "HELP":
            if owner_sender is None:
                owner_sender = sender
                _save_owner_sender(owner_sender)
                lg.log_event("OWNER_BOUND", detail=sender, result="SUCCESS")
            elif sender != owner_sender:
                lg.log_event("SMS_REJECTED_UNAUTHORIZED",
                             detail=f"{cmd} from {sender}", result="DENIED")
                reply("ERROR: This device is locked to its registered "
                      "controller number. Command ignored.")
                return

        # ── HELP ──────────────────────────────────────────────────────
        if cmd == "HELP":
            reply(HELP_TEXT)
            return

        # ── STATUS ────────────────────────────────────────────────────
        if cmd == "STATUS":
            reply(_status_text())
            return

        # ── LOG ───────────────────────────────────────────────────────
        # Full log of the CURRENT session (everything since boot), texted
        # back as numbered multi-part SMS.
        if cmd == "LOG":
            rows = lg.session_log_lines()
            if not rows:
                reply("LOG: No events recorded yet this session.")
                return
            lines = []
            for row in rows:
                ts  = row[0] if len(row) > 0 else ""
                ev  = row[1] if len(row) > 1 else ""
                det = row[2] if len(row) > 2 else ""
                res = row[3] if len(row) > 3 else ""
                # Compact: HH:MM:SS EVENT [detail] = result
                line = f"{ts[11:]} {ev}".strip()
                if det and det != "N/A":
                    line += f" [{det}]"
                if res and res != "N/A":
                    line += f" = {res}"
                lines.append(line)
            header = f"SESSION LOG ({len(lines)} events):"
            sms.send_long_reply(sender, header, lines)
            return

        # ── SET PASSWORD ──────────────────────────────────────────────
        if cmd == "SET PASSWORD":
            if len(args) < 4:
                reply("ERROR: Password must be at least 4 characters. "
                      "Usage: SET PASSWORD <newpassword>")
                return
            ADMIN_PASSWORD = args
            _save_password(ADMIN_PASSWORD)
            lg.log_event("PASSWORD_CHANGED", result="SUCCESS")
            reply(f"OK: Password updated successfully.")
            # During first boot, advance the wizard
            if state == S.FIRST_BOOT and wizard_state is not None:
                wizard_state.pwd_done = True
                fb.mark_step_done("password")
                if wizard_state.step == "welcome" or wizard_state.step == "password":
                    wizard_state.step = "face"
            return

        # ── REGISTER PHONE ────────────────────────────────────────────
        if cmd == "REGISTER PHONE":
            num = args.strip()
            if len(num) != 10 or not num.isdigit():
                reply(f"ERROR: Need exactly 10 digits. Got: {num!r}. "
                      f"Usage: REGISTER PHONE 9876543210")
                return
            sms.save_phone(num)
            lg.log_event("PHONE_REGISTERED", detail=f"+91{num}", result="SUCCESS")
            fb.mark_step_done("phone")
            reply(f"OK: Phone +91{num} registered. Alerts will be sent here.")
            if state == S.FIRST_BOOT and wizard_state is not None:
                wizard_state.ph_done = True
                if wizard_state.step == "phone":
                    wizard_state.step = "done"
            return

        # ── REGISTER FACE ─────────────────────────────────────────────
        if cmd == "REGISTER FACE":
            busy_states = (S.REG_FACE, S.REG_FP, S.AUTHING)
            if state in busy_states:
                reply("BUSY: System is already running a registration or auth. Wait and retry.")
                return
            # Re-registering overwrites the currently enrolled face, so
            # require the admin password as confirmation. First-time
            # registration (no face on file yet) needs no confirmation.
            if driver_face_loaded and args.strip() != ADMIN_PASSWORD:
                lg.log_event("REGISTER_FACE_CONFIRM_REQUIRED", result="PENDING")
                reply("WARNING: A face is already registered. This will overwrite it. "
                      "To confirm, send: REGISTER FACE <adminpassword>")
                return
            state = S.REG_FACE
            reg_state = RegState(mode="face"); reg_done_at = 0.0
            threading.Thread(target=_face_reg_worker,
                             args=(buf, recognizer, reg_state),
                             daemon=True).start()
            reply("OK: Face registration started. Stand in front of the camera "
                  "and follow the on-screen instructions.")
            if state == S.FIRST_BOOT and wizard_state is not None:
                wizard_state.step = "face"
            return

        # ── REGISTER FP ───────────────────────────────────────────────
        if cmd == "REGISTER FP":
            busy_states = (S.REG_FACE, S.REG_FP, S.AUTHING)
            if state in busy_states:
                reply("BUSY: System is already busy. Wait and retry.")
                return
            # Re-enrolling overwrites the currently enrolled fingerprint, so
            # require the admin password as confirmation. First-time
            # enrolment (nothing on file yet) needs no confirmation.
            if fp.is_enrolled() and args.strip() != ADMIN_PASSWORD:
                lg.log_event("REGISTER_FP_CONFIRM_REQUIRED", result="PENDING")
                reply("WARNING: A fingerprint is already enrolled. This will overwrite "
                      "it. To confirm, send: REGISTER FP <adminpassword>")
                return
            state = S.REG_FP
            reg_state = RegState(mode="fp"); reg_done_at = 0.0
            threading.Thread(target=_fp_reg_worker,
                             args=(reg_state,), daemon=True).start()
            reply("OK: Fingerprint enrolment started. Place your finger on "
                  "the sensor when prompted.")
            return

        # ── AUTH ──────────────────────────────────────────────────────
        if cmd == "AUTH":
            if state == S.AUTHING:
                reply("BUSY: Authentication already in progress.")
                return
            if not driver_face_loaded:
                reply("ERROR: No face registered yet. Send REGISTER FACE first.")
                return
            if not fp.is_enrolled():
                reply("ERROR: No fingerprint enrolled yet. Send REGISTER FP first.")
                return
            auth_state = AuthState(is_auto=False, face_only=False)
            state = S.AUTHING
            threading.Thread(
                target=_auth_worker,
                args=(buf, cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH),
                      recognizer, auth_state),
                daemon=True).start()
            reply("OK: Authentication started. Look at the camera and place "
                  "your finger on the sensor.")
            return

        # ── WAKE UP ───────────────────────────────────────────────────
        if cmd == "WAKE UP":
            # The interaction handler above already woke the unit and reset
            # the 5-minute cycle; just acknowledge.
            reply("OK: System woken up. 5-minute timer restarted.")
            return

        # ── TURN OFF ──────────────────────────────────────────────────
        if cmd == "TURN OFF":
            if not ignition_active:
                reply("INFO: Ignition is already off.")
                return
            ignition_active = False
            relay.ignition_off()
            lg.log_event("SMS_COMMAND", detail="Turn Off from SMS", result="IGNITION_OFF")
            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            reply(f"OK: Ignition turned OFF at {ts_str}.")
            return

        # ── SHUT DOWN ────────────────────────────────────────────────
        if cmd == "SHUT DOWN":
            ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            reply(f"OK: Shutting down the system at {ts_str}. "
                  f"Power-cycle to bring it back up.")
            lg.log_event("SMS_COMMAND", detail="Shut Down from SMS", result="SHUTDOWN")
            relay.relay_shutdown()

            def _do_shutdown():
                # Give the modem time to actually transmit the reply above
                # before power drops. No OS-level `sudo shutdown` here by
                # design - de-energising the timer latch (GPIO23) directly
                # cuts power to the whole unit at the external supply.
                time.sleep(3.0)
                relay.timer_latch_off()

            threading.Thread(target=_do_shutdown, daemon=True).start()
            return

        # ── LED ON / LED OFF ──────────────────────────────────────────
        if cmd == "LED ON":
            led_on = True
            led_manual_override = True
            led_timer = 0
            relay.led_relay_on()
            lg.log_event("LED_ON", detail="SMS override", result="ON")
            reply("OK: LED turned ON (manual override).")
            return

        if cmd == "LED OFF":
            led_on = False
            led_manual_override = True
            led_timer = 0
            relay.led_relay_off()
            lg.log_event("LED_OFF", detail="SMS override", result="OFF")
            reply("OK: LED turned OFF (manual override). "
                  "Auto brightness control resumed on next change.")
            led_manual_override = False   # re-enable auto after manual off
            return

        # ── RESET ─────────────────────────────────────────────────────
        if cmd == "RESET":
            reset_pending    = True
            reset_pending_at = now
            reset_expires_at = now + RESET_CONFIRM_TIMEOUT
            reply(f"WARNING: This will delete ALL face, fingerprint, and phone data. "
                  f"To confirm, send: RESET CONFIRM <admin password>  "
                  f"(expires in {RESET_CONFIRM_TIMEOUT:.0f}s)")
            return

        # ── RESET CONFIRM ─────────────────────────────────────────────
        if cmd == "RESET CONFIRM":
            if not reset_pending:
                reply("ERROR: No reset pending. Send RESET first.")
                return
            if state in (S.REG_FACE, S.REG_FP, S.AUTHING):
                reply("BUSY: A registration or authentication is in progress. "
                      "Wait for it to finish, then send RESET CONFIRM again.")
                return
            if now > reset_expires_at:
                reset_pending = False
                reply("ERROR: Reset confirmation expired. Send RESET again.")
                return
            if args.strip() != ADMIN_PASSWORD:
                reply("ERROR: Wrong password. Reset cancelled.")
                reset_pending = False
                return
            # Execute reset
            reset_pending = False
            if os.path.exists(fd.DRIVER_FACE_FILE):
                os.remove(fd.DRIVER_FACE_FILE)
            fp._clear_enrollment()
            sms.clear_phone()
            fb.clear_setup_flag()
            _clear_owner_sender()
            owner_sender          = None   # unbound - next command rebinds a new owner
            recognizer            = cv2.face.LBPHFaceRecognizer_create()
            driver_face_loaded    = False
            session_auth_done     = False
            first_detect_detected = False
            auth_attempts         = 0
            auth_retry_at         = 0.0
            auto_fail_streak      = 0
            auto_recheck_at       = 0.0
            ignition_active       = False
            relay.ignition_off()
            idle_det.set_recognizer(recognizer, False)
            lg.log_event("RESET_ALL", result="CLEARED")
            reset_done_at = now
            state = S.RESETTING
            reply("OK: All data cleared. System will restart setup.")
            return

        # Fallthrough - shouldn't happen if _body_to_command is correct
        print(f"[SMS] Unhandled command: {cmd!r}")

    # ─────────────────────────────────────────
    # MAIN LOOP
    # ─────────────────────────────────────────
    while True:
        now = time.monotonic()
        elapsed = now - last_render
        if elapsed < frame_interval:
            time.sleep(frame_interval - elapsed)
            now = time.monotonic()
        last_render = now

        ret, raw = _read_frame(picam2)
        if not ret:
            time.sleep(0.05)
            continue
        raw = cv2.flip(raw, 1)
        buf.write(raw)

        # ── LED brightness auto-control ────────────────────────────────
        # Only relevant while face detection is actually running (i.e.
        # during authentication, manual or auto check-in). Skip entirely
        # outside S.AUTHING (idle, registration, sleep cycle, etc.) and
        # skip if manual override is active.
        brightness = fd.measure_brightness(raw)
        if not led_manual_override and state == S.AUTHING:
            if brightness < fd.BRIGHTNESS_LOW and not led_on:
                if led_timer == 0: led_timer = now
                elif now - led_timer >= 3.0:
                    led_on = True
                    relay.led_relay_on()
                    lg.log_event("LED_ON", detail=f"brightness={int(brightness)}", result="ON")
                    led_timer = 0
            elif brightness >= fd.BRIGHTNESS_OK and led_on:
                if led_timer == 0: led_timer = now
                elif now - led_timer >= 3.0:
                    led_on = False
                    relay.led_relay_off()
                    lg.log_event("LED_OFF", detail=f"brightness={int(brightness)}", result="OFF")
                    led_timer = 0
            else:
                led_timer = 0
        elif not led_manual_override and led_on:
            # Authentication ended (or never started) — make sure the LED
            # doesn't stay on outside the auth window.
            led_on = False
            relay.led_relay_off()
            lg.log_event("LED_OFF", detail="auth ended", result="OFF")
            led_timer = 0

        # ── Reset confirm expiry ──────────────────────────────────────
        if reset_pending and now > reset_expires_at:
            reset_pending = False
            print("[RESET] Confirm window expired.")

        # ── SMS command processing ─────────────────────────────────────
        cmd_obj = sms_poller.pop_command()
        if cmd_obj is not None:
            handle_sms_command(cmd_obj)

        # ── Post-auth 5-minute cycle (sleep window) ───────────────────
        # cycle_start is set when the first authentication completes and is
        # restarted by every auto check-in and SMS interaction. Within the
        # active window (0..CYCLE_ACTIVE_SECS) the normal UI is shown; from
        # there to CYCLE_TOTAL_SECS the sleep screen is shown; at
        # CYCLE_TOTAL_SECS an auto face check-in fires (scheduler below).
        # Computed BEFORE the camera-detection block below so the camera is
        # genuinely left untouched while the sleep (clock) screen is up - no
        # face/multi-face/unauthorised detection runs during sleep. A denial
        # streak still being confirmed (auto_fail_streak > 0) holds the unit
        # awake so the rapid re-checks below aren't interrupted by sleep.
        sleeping = False
        if (session_auth_done and cycle_start is not None
                and state == S.IDLE and auto_fail_streak == 0):
            cycle_elapsed = now - cycle_start
            if CYCLE_ACTIVE_SECS <= cycle_elapsed < CYCLE_TOTAL_SECS:
                sleeping = True

        # ── Idle face detection + SMS alerts ──────────────────────────
        # Skipped entirely while sleeping - the camera does no face,
        # multi-face, or unauthorised-person detection during the sleep
        # (clock) screen.
        phone_ok = sms.is_phone_registered()
        if state in (S.IDLE, S.RETRY_WAIT) and not sleeping:
            gray = cv2.equalizeHist(cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY))
            idle_det.update(gray)
        idle_faces, idle_alert = idle_det.result()

        ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if state == S.IDLE and not sleeping:
            if idle_alert == "MULTIPLE_FACES":
                sms_throttle.maybe_send(
                    "MULTIPLE_FACES",
                    f"[ALERT] {ts_str} - Multiple people detected.")
            elif idle_alert == "UNKNOWN_FACE":
                sms_throttle.maybe_send(
                    "UNKNOWN_FACE",
                    f"[ALERT] {ts_str} - Unrecognised person detected.")

        # ── Person-presence tracking ──────────────────────────────────
        # A human counts as "present" whenever the idle detector sees a
        # face, or whenever the unit is actively engaged with the driver
        # (authenticating / registering / showing a result). Drives both
        # power-off watchdogs below. While sleeping, the camera isn't being
        # checked at all, so absence of a detection must NOT be read as the
        # driver having left - just hold presence steady until we wake up.
        if sleeping:
            last_person_time = now
        else:
            person_seen = len(idle_faces) > 0
            if person_seen or state in (S.AUTHING, S.REG_FACE, S.REG_FP,
                                        S.RESULT, S.RESETTING, S.FIRST_BOOT):
                last_person_time = now

        # ── Power-off watchdogs ───────────────────────────────────────
        if not session_auth_done:
            # Pre-auth boot window: cut power if NEITHER a human nor an SMS
            # interaction has happened within BOOT_NO_ACTIVITY_TIMEOUT. This
            # check itself is guarded by state==IDLE, so the FIRST_BOOT
            # wizard has its own separate, shorter no-progress watchdog
            # below (FIRST_BOOT_NO_PROGRESS_TIMEOUT) instead.
            if (state == S.IDLE
                    and now - last_person_time >= BOOT_NO_ACTIVITY_TIMEOUT
                    and now - last_interaction >= BOOT_NO_ACTIVITY_TIMEOUT):
                power_off_reason = (f"boot timeout - no human or SMS for "
                                    f"{BOOT_NO_ACTIVITY_TIMEOUT:.0f}s")
                break
        else:
            # Post-auth: cut power if no person is seen on camera for
            # PERSON_ABSENT_TIMEOUT (driver has left the vehicle).
            if now - last_person_time >= PERSON_ABSENT_TIMEOUT:
                power_off_reason = (f"no person on camera for "
                                    f"{PERSON_ABSENT_TIMEOUT:.0f}s after auth")
                break

        # ── Session-start auto-auth ───────────────────────────────────
        if (state == S.IDLE
                and driver_face_loaded
                and fp.is_enrolled()
                and not session_auth_done
                and len(idle_faces) > 0):
            if not first_detect_detected:
                first_detect_detected = True
                auth_state = AuthState(is_auto=False, face_only=False)
                state = S.AUTHING
                lg.log_event("SESSION_AUTH_START", detail="first detection on boot")
                threading.Thread(
                    target=_auth_worker,
                    args=(buf, cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH),
                          recognizer, auth_state),
                    daemon=True).start()

        # ── Failed-auth retry scheduler ─────────────────────────────────
        # Fires AUTH_RETRY_DELAY seconds after a denied initial attempt
        # (see "Auth completion" below), up to AUTH_MAX_ATTEMPTS total.
        # Same gate as the first attempt: only run recognition when a
        # face is actually in front of the camera, not blindly on timer.
        if (state == S.RETRY_WAIT
                and not session_auth_done
                and auth_retry_at > 0.0
                and now >= auth_retry_at
                and len(idle_faces) > 0):
            auth_retry_at = 0.0
            auth_state = AuthState(is_auto=False, face_only=False)
            state = S.AUTHING
            lg.log_event("AUTH_RETRY_START",
                         detail=f"attempt {auth_attempts+1}/{AUTH_MAX_ATTEMPTS}")
            threading.Thread(
                target=_auth_worker,
                args=(buf, cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH),
                      recognizer, auth_state),
                daemon=True).start()

        # ── Registration completion ────────────────────────────────────
        _reg_active = state in (S.REG_FACE, S.REG_FP)
        if _reg_active and reg_state is not None and reg_state.done:
            if reg_done_at == 0: reg_done_at = now
            if now - reg_done_at >= REG_LINGER:
                is_face_reg = (reg_state.mode == "face")
                is_fp_reg   = (reg_state.mode == "fp")
                if is_face_reg and reg_state.success:
                    if os.path.exists(fd.DRIVER_FACE_FILE):
                        recognizer.read(fd.DRIVER_FACE_FILE)
                        driver_face_loaded = True
                        idle_det.set_recognizer(recognizer, True)
                    fb.mark_step_done("face")
                    sms.send_alert(f"[SYSTEM] Face registration SUCCESS at {ts_str}.")
                elif is_face_reg:
                    sms.send_alert(f"[SYSTEM] Face registration FAILED at {ts_str}. Try again.")
                if is_fp_reg and reg_state.success:
                    fb.mark_step_done("fingerprint")
                    sms.send_alert(f"[SYSTEM] Fingerprint enrolment SUCCESS at {ts_str}.")
                elif is_fp_reg:
                    sms.send_alert(f"[SYSTEM] Fingerprint enrolment FAILED at {ts_str}: "
                                    f"{reg_state.fail_reason or 'unknown error'}. Try again.")

                # Advance first boot wizard
                if wizard_state is not None:
                    if is_face_reg and reg_state.success:
                        wizard_state.face_done = True
                        wizard_state.step = "fingerprint"
                    elif is_face_reg:
                        wizard_state.step = "face"   # stay on face step to retry
                    if is_fp_reg and reg_state.success:
                        wizard_state.fp_done = True
                        wizard_state.step = "phone"
                    elif is_fp_reg:
                        wizard_state.step = "fingerprint"
                    state = S.FIRST_BOOT
                else:
                    state = S.IDLE
                reg_state = None; reg_done_at = 0.0

        # ── Auth completion ────────────────────────────────────────────
        if state == S.AUTHING and auth_state is not None and auth_state.complete:
            dec              = auth_state.decision
            is_auto     = auth_state.is_auto

            # Update the consecutive-denial streak for periodic auto checks
            # BEFORE anything else branches on it. A single denied auto
            # check is treated as a possible false detection (bad angle/
            # lighting) - only a confirmed run of AUTO_AUTH_CONFIRM_STREAK
            # denials IN A ROW is treated as an actual unauthorised driver.
            # Any GRANTED check in between resets the streak to 0.
            if is_auto and dec == "DENIED":
                auto_fail_streak += 1
            elif is_auto and dec == "GRANTED":
                auto_fail_streak = 0
                auto_recheck_at  = 0.0

            unconfirmed_recheck = (is_auto and dec == "DENIED"
                                   and auto_fail_streak < AUTO_AUTH_CONFIRM_STREAK)

            if not unconfirmed_recheck:
                last_result      = dec
                last_result_time = now

            if not session_auth_done and not is_auto:
                if dec == "GRANTED":
                    session_auth_done = True
                    auth_attempts     = 0
                    ignition_active   = True
                    relay.ignition_on()
                else:
                    ignition_active = False
                    relay.ignition_off()
                    auth_attempts  += 1
            elif is_auto and dec == "DENIED" and not unconfirmed_recheck:
                # Confirmed unauthorised across the full streak - only now
                # do we actually cut ignition.
                ignition_active = False
                relay.ignition_off()

            # SMS notification of auth result
            if not is_auto:
                if dec == "GRANTED":
                    sms.send_alert(f"[AUTH] {ts_str} - ACCESS GRANTED. Ignition enabled.")
                else:
                    sms.send_alert(f"[AUTH] {ts_str} - ACCESS DENIED. Ignition disabled.")

            # Every authentication that actually starts/continues a live
            # session (re)starts the 5-minute cycle. A failed initial
            # attempt does NOT start the cycle - it only queues a retry.
            # An unconfirmed denial streak also does NOT restart the normal
            # cycle - it keeps the unit awake on the faster recheck timer
            # below until the streak is resolved one way or the other.
            if session_auth_done and not unconfirmed_recheck:
                cycle_start      = now
                last_person_time = now
                sleeping         = False

            if is_auto:
                if dec == "GRANTED":
                    flash_until = now + 2.0
                    lg.log_event("AUTO_AUTH", detail="periodic face check", result="GRANTED")
                elif unconfirmed_recheck:
                    # Possible false detection - flash briefly, don't alarm,
                    # don't touch ignition, and queue a rapid recheck.
                    flash_until       = now + 1.0
                    auto_denied_until = now
                    auto_recheck_at   = now + AUTO_AUTH_RECHECK_DELAY
                    lg.log_event("AUTO_AUTH",
                                 detail=f"unconfirmed denial {auto_fail_streak}/"
                                        f"{AUTO_AUTH_CONFIRM_STREAK} - rechecking",
                                 result="DENIED - RECHECK")
                else:
                    auto_denied_until = now + AUTO_AUTH_DENIED_SHOW
                    lg.log_event("AUTO_AUTH",
                                 detail=f"confirmed after {auto_fail_streak} consecutive checks",
                                 result="DENIED - UNAUTHORISED")
                    sms_throttle.maybe_send(
                        "AUTO_AUTH_DENIED",
                        f"[SECURITY] {ts_str} - Unauthorised person in vehicle "
                        f"(confirmed after {auto_fail_streak} consecutive checks).")
                    auto_fail_streak = 0
                    auto_recheck_at  = 0.0
                state = S.RESULT
            elif not session_auth_done and dec == "DENIED":
                # Initial authentication failed - retry after a delay, up
                # to AUTH_MAX_ATTEMPTS times, then power down.
                flash_until = now + 2.5
                state       = S.RESULT
                if auth_attempts >= AUTH_MAX_ATTEMPTS:
                    power_off_reason = (f"authentication failed {auth_attempts} times "
                                        f"({AUTH_MAX_ATTEMPTS} max)")
                    lg.log_event("AUTH_RETRY_EXHAUSTED",
                                 detail=f"{auth_attempts} failed attempts", result="DENIED")
                    sms.send_alert(f"[SYSTEM] {ts_str} - Authentication failed "
                                   f"{auth_attempts} times. Powering off.")
                else:
                    auth_retry_at = now + AUTH_RETRY_DELAY
                    lg.log_event("AUTH_RETRY_SCHEDULED",
                                 detail=f"attempt {auth_attempts}/{AUTH_MAX_ATTEMPTS}, "
                                        f"retry in {AUTH_RETRY_DELAY:.0f}s",
                                 result="DENIED")
            else:
                flash_until = now + 2.5
                state = S.RESULT

        # ── Auto-denied result hold ────────────────────────────────────
        if state == S.RESULT and auth_state and auth_state.is_auto:
            if auth_state.decision == "DENIED" and now < auto_denied_until:
                pass
            elif now >= flash_until and now >= auto_denied_until:
                state = S.IDLE; auth_state = None

        # ── Auto check-in scheduler (end of the 5-minute cycle) ────────
        # When the cycle reaches CYCLE_TOTAL_SECS, wake from the sleep
        # screen and run a face-only re-authentication. Completion of this
        # auth restarts the cycle (see the auth-completion block above).
        # Gated on auto_fail_streak == 0 so this normal full-cycle trigger
        # doesn't fire on top of the faster recheck scheduler below while a
        # denial streak is still being confirmed.
        if (state == S.IDLE
                and driver_face_loaded
                and session_auth_done
                and cycle_start is not None
                and auto_fail_streak == 0
                and now - cycle_start >= CYCLE_TOTAL_SECS):
            auth_state = AuthState(is_auto=True, face_only=True)
            state = S.AUTHING
            sleeping = False
            lg.log_event("AUTO_CHECKIN_START",
                         detail=f"cycle={CYCLE_TOTAL_SECS:.0f}s")
            threading.Thread(
                target=_auth_worker,
                args=(buf, cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH),
                      recognizer, auth_state),
                daemon=True).start()

        # ── Auto check-in RECHECK scheduler (confirming a denial streak) ──
        # Fires AUTO_AUTH_RECHECK_DELAY seconds after an unconfirmed denied
        # auto-check, running another face-only check. Repeats until either
        # a GRANTED check resets the streak (false-detection ruled out) or
        # AUTO_AUTH_CONFIRM_STREAK consecutive denials confirm the driver is
        # actually unauthorised (handled in the Auth completion block).
        if (state == S.IDLE
                and driver_face_loaded
                and session_auth_done
                and auto_recheck_at > 0.0
                and now >= auto_recheck_at):
            auto_recheck_at = 0.0
            auth_state = AuthState(is_auto=True, face_only=True)
            state = S.AUTHING
            sleeping = False
            lg.log_event("AUTO_CHECKIN_RECHECK",
                         detail=f"confirm attempt {auto_fail_streak + 1}/"
                                f"{AUTO_AUTH_CONFIRM_STREAK}")
            threading.Thread(
                target=_auth_worker,
                args=(buf, cv2.CascadeClassifier(fd.HAAR_CASCADE_PATH),
                      recognizer, auth_state),
                daemon=True).start()

        # ── Result timeout ─────────────────────────────────────────────
        if state == S.RESULT and now >= flash_until:
            is_auto_denied = (auth_state and auth_state.is_auto
                              and auth_state.decision == "DENIED"
                              and now < auto_denied_until)
            if not is_auto_denied:
                if power_off_reason is not None:
                    break
                if auth_retry_at > 0.0 and not session_auth_done:
                    state = S.RETRY_WAIT
                else:
                    state = S.IDLE
                auth_state = None

        # ── Retry-wait countdown timeout ────────────────────────────────
        if state == S.RETRY_WAIT and auth_retry_at <= 0.0:
            # The retry scheduler above already consumed auth_retry_at and
            # started a new attempt (state will already be S.AUTHING), or
            # the retry budget was exhausted - either way this screen is
            # done; fall back to IDLE only if nothing else claimed the state.
            state = S.IDLE

        # ── Reset timeout ──────────────────────────────────────────────
        if state == S.RESETTING and now - reset_done_at > 2.5:
            # After reset, go to first-boot wizard
            wizard_state = WizardState()
            first_boot_started_at = now
            state = S.FIRST_BOOT

        # ── First boot completion check ────────────────────────────────
        if state == S.FIRST_BOOT and wizard_state is not None:
            if wizard_state.step == "done":
                # Check if truly done
                if wizard_state.pwd_done and wizard_state.face_done and wizard_state.fp_done:
                    fb.mark_setup_complete()
                    lg.log_event("FIRST_BOOT_COMPLETE", result="SUCCESS")
                    wizard_state = None
                    state = S.IDLE
                    ADMIN_PASSWORD = _load_password()
                    sms.send_alert(f"[SYSTEM] Setup complete at {ts_str}. Send AUTH to begin.")

        # ── First-boot no-progress watchdog ─────────────────────────────
        # Registration "hasn't started" until the very first wizard step
        # (password) is completed. If that doesn't happen within the
        # timeout, cut power instead of sitting in the wizard forever.
        if (state == S.FIRST_BOOT and wizard_state is not None
                and not wizard_state.pwd_done
                and now - first_boot_started_at >= FIRST_BOOT_NO_PROGRESS_TIMEOUT):
            power_off_reason = (f"first-boot setup not started within "
                                f"{FIRST_BOOT_NO_PROGRESS_TIMEOUT:.0f}s")
            break

        # ── DRAW ───────────────────────────────────────────────────────
        if sleeping:
            canvas = cb.draw_sleep()

        elif state == S.FIRST_BOOT and wizard_state is not None:
            fb_remaining = max(0.0, FIRST_BOOT_NO_PROGRESS_TIMEOUT
                               - (now - first_boot_started_at))
            canvas = cb.draw_first_boot(raw, wizard_state, reg_state,
                                         shutdown_in=fb_remaining)

        elif state == S.REG_FACE and reg_state is not None:
            canvas = cb.draw_reg_face(raw, reg_state)

        elif state == S.REG_FP and reg_state is not None:
            canvas = cb.draw_reg_fp(raw, reg_state)

        elif state == S.AUTHING and auth_state is not None:
            canvas = cb.draw_auth(raw, auth_state)

        elif state == S.RESULT:
            canvas = cb.draw_result(raw, last_result)

        elif state == S.RESETTING:
            canvas = cb.draw_reset(raw, reset_done_at)

        elif state == S.RETRY_WAIT:
            remaining = max(0.0, auth_retry_at - now)
            canvas = cb.draw_retry_wait(raw, auth_attempts, AUTH_MAX_ATTEMPTS, remaining)

        else:
            if session_auth_done and cycle_start is not None:
                next_in = max(0.0, CYCLE_TOTAL_SECS - (now - cycle_start))
            else:
                next_in = None
            canvas = cb.draw_idle(
                raw, driver_face_loaded, fp.is_enrolled(),
                phone_ok, last_result, led_on, brightness,
                idle_faces, idle_alert, next_in, ignition_active,
                last_sms_cmd, last_sms_time,
                reset_pending, reset_expires_at,
                last_result_time)

        cv2.imshow(WIN, canvas)

        # Minimal waitKey - no keyboard input used, just keeps OpenCV window alive
        key = cv2.waitKey(1) & 0xFF
        # Only Q key kept as emergency exit (physical keyboard only)
        if key == ord('q') or key == ord('Q'):
            print("[INFO] Emergency quit via keyboard.")
            break

    lg.log_event("SYSTEM_STOPPED")
    sms_poller.stop()

    if power_off_reason is not None:
        # Watchdog-triggered power-down: notify, then de-energise the
        # self-power timer latch (GPIO23) so the whole unit loses power.
        print(f"[SHUTDOWN] {power_off_reason} - cutting power.")
        lg.log_event("AUTO_SHUTDOWN", detail=power_off_reason, result="POWER_OFF")
        try:
            ts_off = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sms.send_alert(f"[SYSTEM] {ts_off} - Powering off ({power_off_reason}).")
        except Exception as e:
            print(f"[SHUTDOWN] Alert send failed: {e}")
        relay.ignition_off()
        relay.led_relay_off()
        relay.timer_latch_off()   # drops the latch -> unit powers down
        _release_camera(picam2)
        cv2.destroyAllWindows()
        print("[INFO] Power latch dropped. Unit shutting down.")
    else:
        # Manual emergency quit ('q'): leave the timer latch ON so the Pi
        # stays powered (matches relay_shutdown's documented behaviour).
        relay.relay_shutdown()
        _release_camera(picam2)
        cv2.destroyAllWindows()
        print("[INFO] System shut down cleanly.")


if __name__ == "__main__":
    run()