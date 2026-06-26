"""
Multi-Factor Driver Authentication System
Dev tool: simulate an incoming SMS command with no SIM card.

WHY THIS EXISTS
----------------
sms_alert.GsmPoller holds the serial port open for the entire time Main.py
is running, so you cannot type AT commands into a separate terminal at the
same time - the port is exclusive to one process.

This script is the workaround: run it BEFORE starting Main.py. It opens
the port just long enough to write one fake message into the GSM module's
own storage via AT+CMGW, then closes the port. When Main.py starts and its
poller runs AT+CMGL="ALL", it will find that message sitting in storage and
process it exactly like a real incoming SMS - same parsing, same dispatcher,
same everything. This is a real end-to-end test of the SMS code path, not
a mock.

THE TRICK
---------
AT+CMGW actually writes an *outgoing* draft (status "STO UNSENT") addressed
to the number you give it - it does not let you fabricate a "received from"
field. But sms_alert._parse_sms_list() does not check message status, and
just reads whatever number you wrote as the message's "number" field. So
writing a draft addressed to your test number makes the poller treat that
number as the sender. That is the only reason this works.

REQUIREMENTS
-------------
- sms_alert.SMS_STORAGE must be "ME" (module's own flash), not "SM" (SIM
  card memory) - there is no SIM, so "SM" storage cannot exist. Edit that
  constant in sms_alert.py before using this script.
- Your GSM module's firmware must actually support SMS storage without a
  SIM inserted. Many cheap SIM800L clones refuse ALL SMS-related AT
  commands (CMGF/CMGW/CMGL) with "+CME ERROR: SIM not inserted" regardless
  of storage type, even for "ME". If AT+CMGW errors out below, your module
  requires a real SIM and this trick will not work - see the fallback in
  the module docstring instead.

USAGE
-----
    python simulate_sms.py +919876543210 AUTH
    python simulate_sms.py +919876543210 "REGISTER PHONE 9876543210"
    python simulate_sms.py +919876543210 "SET PASSWORD 5678"

Run it once per fake message, then start Main.py. Re-run it any time you
want to queue another simulated command (Main.py does not need to be
restarted - just send another command for the poller to pick up next
cycle, AS LONG AS Main.py isn't currently holding the port. If Main.py is
already running, stop it first, run this script, then start Main.py again.)
"""

import sys
import time
import serial

from sms_alert import GSM_PORT, BAUD_RATE, SMS_STORAGE


def _send(ser: serial.Serial, command: str, wait: float = 1.0) -> str:
    ser.write((command + '\r\n').encode())
    time.sleep(wait)
    resp = ser.read_all().decode(errors='ignore').strip()
    print(f">> {command}\n<< {resp}\n")
    return resp


def write_fake_sms(sender: str, body: str):
    if SMS_STORAGE == "SM":
        print("[WARN] sms_alert.SMS_STORAGE is still \"SM\" (SIM memory). "
              "Without a SIM card this WILL fail. Edit SMS_STORAGE to "
              "\"ME\" in sms_alert.py first.")

    print(f"[SIM] Opening {GSM_PORT} @ {BAUD_RATE}...")
    ser = serial.Serial(GSM_PORT, BAUD_RATE, timeout=5)
    time.sleep(2)

    _send(ser, 'AT')
    _send(ser, 'ATE0')
    _send(ser, 'AT+CMGF=1')
    resp = _send(ser, f'AT+CPMS="{SMS_STORAGE}","{SMS_STORAGE}","{SMS_STORAGE}"')
    if 'ERROR' in resp:
        print("[FAIL] AT+CPMS rejected this storage type without a SIM. "
              "Your module's firmware requires a SIM card for SMS storage "
              "- this simulation trick will not work on this hardware.")
        ser.close()
        return False

    ser.write(f'AT+CMGW="{sender}"\r\n'.encode())
    time.sleep(0.5)
    ser.read_all()                          # discard the "> " prompt
    ser.write((body + chr(26)).encode())    # Ctrl+Z ends the message
    time.sleep(2)
    resp = ser.read_all().decode(errors='ignore').strip()
    print(f">> {body} <Ctrl+Z>\n<< {resp}\n")
    ser.close()

    if '+CMGW:' in resp:
        print(f"[OK] Fake message stored: from {sender!r}, body {body!r}. "
              f"Start Main.py and it will be picked up on the next poll.")
        return True
    else:
        print("[FAIL] AT+CMGW did not confirm. See the response above - "
              "if it says SIM not inserted, this module needs a real SIM.")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <sender_number> <command text>")
        print('Example: python simulate_sms.py +919876543210 AUTH')
        sys.exit(1)
    sender_arg = sys.argv[1]
    body_arg   = " ".join(sys.argv[2:])
    write_fake_sms(sender_arg, body_arg)
