"""
Multi-Factor Driver Authentication System
Module: SMS Alert + Command Receiver via SIM800C GSM Module
------------------------------------------------------------
Persistent serial connection - stays open, polls every 3s.
No re-init overhead per poll cycle.

Public API:
    save_phone(number)            -- save a 10-digit number
    load_phone()                  -> "+91XXXXXXXXXX" or None
    clear_phone()                 -- delete saved number
    is_phone_registered()         -> bool
    send_alert(message)           -- non-blocking send to registered number
    send_reply(to_number, msg)    -- non-blocking reply to any number
    send_long_reply(to, header, lines) -- non-blocking multi-part reply
    start_poller()                -> GsmPoller (call once; poll via pop_command())

SmsCommand fields:
    .cmd      : str   uppercase command e.g. "AUTH", "WAKE UP"
    .args     : str   remainder after command word
    .sender   : str   originating number e.g. "+919876543210"
    .raw_body : str   original message text
    .index    : str   SIM storage index
"""

import serial
import time
import threading
import os
import re
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
GSM_PORT        = '/dev/ttyAMA2'
BAUD_RATE       = 115200
COUNTRY_CODE    = '+91'
PHONE_FLAG_FILE = 'registered_phone.txt'
USE_REAL_GSM    = True

# SMS storage location passed to AT+CPMS. "SM" = SIM card memory (needs a
# SIM inserted). Set to "ME" to use the module's own onboard memory instead
# - useful for testing the SMS command flow with no SIM card present. Not
# all modules support "ME" for SMS; if AT+CPMS errors out, your module
# requires a SIM regardless of storage type.
SMS_STORAGE     = 'SM'

POLL_INTERVAL   = 1.5    # seconds between SMS polls
SERIAL_TIMEOUT  = 5      # serial read timeout

# ─────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────
@dataclass
class SmsCommand:
    cmd:      str
    args:     str
    sender:   str
    raw_body: str
    index:    str = ""


# ─────────────────────────────────────────────
# PHONE NUMBER PERSISTENCE
# ─────────────────────────────────────────────
def save_phone(number: str):
    n = number.strip()
    if n.startswith('+91'):
        digits = n[3:]
    elif n.startswith('91') and len(n) == 12:
        digits = n[2:]
    else:
        digits = n
    if len(digits) != 10 or not digits.isdigit():
        raise ValueError(f"Invalid phone number: {number!r}")
    with open(PHONE_FLAG_FILE, 'w') as f:
        f.write(digits)
    print(f"[SMS] Phone number saved: {COUNTRY_CODE}{digits}")


def load_phone() -> Optional[str]:
    if not os.path.exists(PHONE_FLAG_FILE):
        return None
    with open(PHONE_FLAG_FILE, 'r') as f:
        digits = f.read().strip()
    if len(digits) == 10 and digits.isdigit():
        return COUNTRY_CODE + digits
    return None


def clear_phone():
    if os.path.exists(PHONE_FLAG_FILE):
        os.remove(PHONE_FLAG_FILE)
        print("[SMS] Phone number cleared.")


def is_phone_registered() -> bool:
    return load_phone() is not None


# ─────────────────────────────────────────────
# LOW-LEVEL AT HELPERS
# ─────────────────────────────────────────────
def _send_at(ser: serial.Serial, command: str, wait: float = 1.0) -> str:
    ser.write((command + '\r\n').encode())
    time.sleep(wait)
    response = ser.read_all().decode(errors='ignore').strip()
    print(f"[GSM] >> {command}")
    print(f"[GSM] << {response}")
    return response


def _drain(ser: serial.Serial):
    """Discard any bytes waiting in the receive buffer."""
    time.sleep(0.1)
    ser.read_all()


# ─────────────────────────────────────────────
# SMS SENDING  (each send opens its own connection
#  so it never blocks the persistent poll connection)
# ─────────────────────────────────────────────
def _do_send(phone_number: str, message: str) -> bool:
    if not USE_REAL_GSM:
        print(f"[SMS] (SIM) To {phone_number}: {message}")
        return True
    try:
        ser = serial.Serial(GSM_PORT, BAUD_RATE, timeout=SERIAL_TIMEOUT)
        time.sleep(2)
        _send_at(ser, 'AT')
        _send_at(ser, 'ATE0')
        _send_at(ser, 'AT+CMGF=1')
        ser.write(f'AT+CMGS="{phone_number}"\r\n'.encode())
        time.sleep(1)
        ser.read_all()
        ser.write((message + chr(26)).encode())
        time.sleep(5)
        response = ser.read_all().decode(errors='ignore').strip()
        print(f"[GSM] << {response}")
        ser.close()
        if '+CMGS:' in response:
            print(f"[SMS] Sent OK to {phone_number}")
            return True
        else:
            print(f"[SMS] Send FAILED to {phone_number}")
            return False
    except Exception as e:
        print(f"[SMS] GSM error in _do_send: {e}")
        return False


def send_alert(message: str):
    """Non-blocking send to the registered number."""
    phone = load_phone()
    if not phone:
        print("[SMS] No phone registered - alert not sent.")
        return
    threading.Thread(target=_do_send, args=(phone, message), daemon=True).start()


def send_reply(to_number: str, message: str):
    """Non-blocking reply to any number."""
    if not to_number:
        return
    threading.Thread(target=_do_send, args=(to_number, message), daemon=True).start()


# ─────────────────────────────────────────────
# LONG / MULTI-PART REPLY  (e.g. full session log)
# ─────────────────────────────────────────────
SMS_CHUNK_LEN = 150     # per-message budget (leaves room for "(NN/NN) ")
MAX_LOG_SMS   = 12      # safety cap so a huge log can't flood the number

def _pack_lines(header: str, lines: list, limit: int = SMS_CHUNK_LEN) -> list:
    """Greedily pack header + lines into <=limit-char chunks, preferring to
    break on line boundaries. Over-long single lines are hard-split."""
    body_limit = max(20, limit - 9)   # reserve ~9 chars for the "(i/n) " tag
    chunks: list = []
    cur = header or ""
    for ln in lines:
        candidate = (cur + "\n" + ln) if cur else ln
        if len(candidate) <= body_limit:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        while len(ln) > body_limit:
            chunks.append(ln[:body_limit])
            ln = ln[body_limit:]
        cur = ln
    if cur:
        chunks.append(cur)
    return chunks


def _do_send_sequence(phone_number: str, messages: list):
    """Send a list of messages one after another over fresh connections."""
    for i, m in enumerate(messages):
        _do_send(phone_number, m)
        if i < len(messages) - 1:
            time.sleep(1.0)   # brief gap between parts


def send_long_reply(to_number: str, header: str, lines: list,
                    max_parts: int = MAX_LOG_SMS):
    """Non-blocking multi-part reply. Packs header+lines into numbered SMS
    parts and sends them sequentially in a single background thread.
    If the content exceeds max_parts, the final part notes how many
    entries were dropped."""
    if not to_number:
        return
    chunks = _pack_lines(header, lines)
    if len(chunks) > max_parts:
        # Keep the most recent entries: trim from the front of the body.
        # Re-pack from the tail so the newest events survive.
        kept_lines = list(lines)
        while True:
            test = _pack_lines(header, kept_lines)
            if len(test) <= max_parts - 1 or not kept_lines:
                break
            kept_lines.pop(0)
        dropped = len(lines) - len(kept_lines)
        chunks  = _pack_lines(header, kept_lines)
        chunks.append(f"...{dropped} earlier entries omitted.")
    total    = len(chunks)
    numbered = [f"({i+1}/{total}) {c}" for i, c in enumerate(chunks)]
    threading.Thread(target=_do_send_sequence,
                     args=(to_number, numbered), daemon=True).start()


# ─────────────────────────────────────────────
# SMS PARSING
# ─────────────────────────────────────────────
def _parse_sms_list(raw: str) -> list:
    messages = []
    lines = raw.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('+CMGL:'):
            match = re.search(
                r'\+CMGL:\s*(\d+),"[^"]*","([^"]*)",[^,]*,"([^"]*)"', line)
            if match:
                index     = match.group(1)
                number    = match.group(2)
                timestamp = match.group(3)
                body      = lines[i + 1].strip() if i + 1 < len(lines) else ''
                messages.append({
                    'index':     index,
                    'number':    number,
                    'timestamp': timestamp,
                    'body':      body,
                })
                i += 2
                continue
        i += 1
    return messages


def _body_to_command(body: str, number: str, index: str) -> Optional[SmsCommand]:
    clean = body.strip()
    if not clean:
        return None

    parts  = clean.split(None, 1)
    first  = parts[0].upper()
    rest   = parts[1].strip() if len(parts) > 1 else ""

    TWO_WORD = {
        ("REGISTER", "FACE"),
        ("REGISTER", "FP"),
        ("RESET",    "CONFIRM"),
        ("TURN",     "OFF"),
        ("LED",      "ON"),
        ("LED",      "OFF"),
        ("REGISTER", "PHONE"),
        ("SET",      "PASSWORD"),
        ("WAKE",     "UP"),
        ("SHUT",     "DOWN"),
    }

    if rest:
        rest_parts = rest.split(None, 1)
        second     = rest_parts[0].upper()
        tail       = rest_parts[1].strip() if len(rest_parts) > 1 else ""
        if (first, second) in TWO_WORD:
            cmd  = first + " " + second
            args = tail
        else:
            cmd  = first
            args = rest
    else:
        cmd  = first
        args = ""

    KNOWN = {
        "AUTH", "STATUS", "LOG", "RESET", "HELP",
        "REGISTER FACE", "REGISTER FP", "REGISTER PHONE",
        "SET PASSWORD",
        "RESET CONFIRM",
        "TURN OFF",
        "LED ON", "LED OFF",
        "WAKE UP",
        "SHUT DOWN",
    }

    if cmd not in KNOWN:
        print(f"[SMS] Unknown command ignored: {cmd!r}")
        return None

    return SmsCommand(cmd=cmd, args=args, sender=number,
                      raw_body=clean, index=index)


# ─────────────────────────────────────────────
# PERSISTENT POLLER  (runs in its own thread)
# ─────────────────────────────────────────────
class GsmPoller:
    """
    Keeps the serial port open permanently and polls for new SMS
    every POLL_INTERVAL seconds. Commands are queued for main.py
    to consume via pop_command().

    Sending SMS uses separate short-lived connections so it never
    blocks or conflicts with the poll loop.
    """

    def __init__(self):
        self._queue: list  = []
        self._q_lock       = threading.Lock()
        self._stop         = threading.Event()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        print(f"[GSM_POLLER] Started  poll every {POLL_INTERVAL}s")

    def stop(self):
        self._stop.set()

    def pop_command(self) -> Optional[SmsCommand]:
        with self._q_lock:
            return self._queue.pop(0) if self._queue else None

    # ── internal ──────────────────────────────────────────────────────

    def _run(self):
        while not self._stop.is_set():
            try:
                self._open_and_poll()
            except Exception as e:
                print(f"[GSM_POLLER] Connection lost: {e}  -- retrying in 5s")
                time.sleep(5)

    def _open_and_poll(self):
        """Open serial once, poll in a tight loop until error or stop."""
        print("[GSM_POLLER] Opening serial port...")
        ser = serial.Serial(GSM_PORT, BAUD_RATE, timeout=SERIAL_TIMEOUT)
        time.sleep(2)

        # One-time init
        _send_at(ser, 'AT')
        _send_at(ser, 'ATE0')
        _send_at(ser, 'AT+CMGF=1')
        _send_at(ser, f'AT+CPMS="{SMS_STORAGE}","{SMS_STORAGE}","{SMS_STORAGE}"')
        print("[GSM_POLLER] Ready  polling...")

        while not self._stop.is_set():
            try:
                self._poll_once(ser)
            except Exception as e:
                print(f"[GSM_POLLER] Poll error: {e}")
                break   # outer loop will reconnect
            self._stop.wait(POLL_INTERVAL)

        try:
            ser.close()
        except Exception:
            pass

    def _poll_once(self, ser: serial.Serial):
        _drain(ser)
        raw      = _send_at(ser, 'AT+CMGL="ALL"', wait=2)
        messages = _parse_sms_list(raw)

        for msg in messages:
            idx = msg['index']

            # Delete from SIM immediately. Every message returned by
            # CMGL "ALL" is, by definition, still on the SIM - so it is
            # either new or a leftover that failed to delete last time.
            # Either way it must be processed now: SIM slot indices get
            # reused for new messages, so a persistent "seen" set would
            # cause reused slots to be silently skipped forever and the
            # SIM storage to fill up (dropping future incoming SMS).
            _send_at(ser, f'AT+CMGD={idx}', wait=0.3)

            cmd_obj = _body_to_command(msg['body'], msg['number'], idx)
            if cmd_obj is not None:
                print(f"[GSM_POLLER] CMD from {msg['number']}: {cmd_obj.cmd!r}")
                with self._q_lock:
                    self._queue.append(cmd_obj)
            else:
                print(f"[GSM_POLLER] Ignored: {msg['body']!r}")


def start_poller() -> GsmPoller:
    poller = GsmPoller()
    poller.start()
    return poller
