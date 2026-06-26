import serial
import time
import re

GSM_PORT = '/dev/ttyAMA2'
BAUD_RATE = 9600

def send_at(ser, command, wait=1):
    ser.write((command + '\r\n').encode())
    time.sleep(wait)
    response = ser.read_all().decode(errors='ignore').strip()
    print(f">> {command}")
    print(f"<< {response}\n")
    return response

def parse_sms(raw):
    messages = []
    lines = raw.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('+CMGL:'):
            # +CMGL: index,"status","number",,"timestamp"
            match = re.search(r'\+CMGL:\s*(\d+),"[^"]*","([^"]*)",[^,]*,"([^"]*)"', line)
            if match:
                index = match.group(1)
                number = match.group(2)
                timestamp = match.group(3)
                # Next line is the message body
                body = lines[i + 1].strip() if i + 1 < len(lines) else ''
                messages.append({
                    'index': index,
                    'number': number,
                    'timestamp': timestamp,
                    'body': body
                })
                i += 2
                continue
        i += 1
    return messages

def display_messages(messages):
    if not messages:
        print("📭 No messages found.\n")
        return
    print(f"📬 {len(messages)} message(s) found:")
    print("=" * 50)
    for msg in messages:
        print(f"  #{msg['index']}")
        print(f"  From      : {msg['number']}")
        print(f"  Time      : {msg['timestamp']}")
        print(f"  Message   : {msg['body']}")
        print("-" * 50)

def read_sms():
    with serial.Serial(GSM_PORT, BAUD_RATE, timeout=5) as ser:
        time.sleep(2)

        send_at(ser, 'AT')
        send_at(ser, 'ATE0')          # Disable echo
        send_at(ser, 'AT+CMGF=1')     # Text mode
        send_at(ser, 'AT+CPMS="SM","SM","SM"')  # Use SIM card storage

        print("📡 Fetching all messages...\n")
        raw = send_at(ser, 'AT+CMGL="ALL"', wait=3)

        messages = parse_sms(raw)
        display_messages(messages)

def monitor_sms(interval=5):
    """Continuously poll for new messages every N seconds."""
    print(f"👂 Monitoring for incoming SMS every {interval}s... (Ctrl+C to stop)\n")
    seen_indices = set()

    with serial.Serial(GSM_PORT, BAUD_RATE, timeout=5) as ser:
        time.sleep(2)
        send_at(ser, 'AT')
        send_at(ser, 'ATE0')
        send_at(ser, 'AT+CMGF=1')
        send_at(ser, 'AT+CPMS="SM","SM","SM"')

        while True:
            raw = send_at(ser, 'AT+CMGL="ALL"', wait=2)
            messages = parse_sms(raw)

            for msg in messages:
                if msg['index'] not in seen_indices:
                    seen_indices.add(msg['index'])
                    print("🔔 New message!")
                    print("=" * 50)
                    print(f"  From    : {msg['number']}")
                    print(f"  Time    : {msg['timestamp']}")
                    print(f"  Message : {msg['body']}")
                    print("=" * 50 + "\n")

            time.sleep(interval)

# --- Choose mode ---
# Read all existing messages once:
read_sms()

# OR monitor continuously for new messages:
# monitor_sms(interval=5)
