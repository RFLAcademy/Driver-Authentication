#!/usr/bin/env python3
"""
SIM800C Baud Rate Scanner — Raspberry Pi equivalent of the Arduino baud scanner.
UART2: TX=GPIO0, RX=GPIO1 → /dev/ttyAMA1
"""

import serial
import time

UART_PORT = "/dev/ttyAMA2"

BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]


def try_baud(port, baud) -> bool:
    """
    Open port at given baud, send AT three times (mirrors Arduino autobaud trick),
    and check for 'OK' in the response within 2 seconds.
    Returns True if OK received.
    """
    print(f"Trying: {baud}")
    try:
        ser = serial.Serial(port, baud, timeout=0.5)
    except serial.SerialException as e:
        print(f"  Could not open port: {e}")
        return False

    # Send AT three times for autobaud detection (mirrors Arduino sketch)
    for _ in range(3):
        ser.write(b"AT\r\n")
        time.sleep(0.3)

    # Read all available response within 2-second window
    found = False
    deadline = time.time() + 2.0
    response_buf = ""

    while time.time() < deadline:
        if ser.in_waiting:
            chunk = ser.read(ser.in_waiting).decode(errors="replace")
            response_buf += chunk
            if "OK" in response_buf:
                print(f"  Response: {repr(response_buf.strip())}")
                found = True
                break
        time.sleep(0.05)

    ser.close()
    time.sleep(0.5)     # settle before next attempt
    return found


def main():
    print("SIM800 Baud Rate Scanner")
    print("-" * 25)

    for baud in BAUD_RATES:
        if try_baud(UART_PORT, baud):
            print("=" * 33)
            print(f"  FOUND BAUD: {baud}")
            print("=" * 33)
            break
    else:
        print("\nScan finished — no baud rate matched.")
        print("Check wiring, power, and that UART2 is enabled in /boot/config.txt.")

    print("Scan Finished")


if __name__ == "__main__":
    main()
