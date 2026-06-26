import serial
import time

# SIM800C is on ttyAMA2 (GPIO 0/1 via uart2 overlay)
GSM_PORT = '/dev/ttyAMA2'
BAUD_RATE = 115200

def send_at(ser, command, wait=1, expect='OK'):
    ser.write((command + '\r\n').encode())
    time.sleep(wait)
    response = ser.read_all().decode(errors='ignore').strip()
    print(f">> {command}")
    print(f"<< {response}\n")
    return response

def send_sms(phone_number, message):
    with serial.Serial(GSM_PORT, BAUD_RATE, timeout=5) as ser:
        time.sleep(2)  # Let module settle

        # Basic check
        send_at(ser, 'AT')

        # Disable echo
        send_at(ser, 'ATE0')

        # Check SIM status
        send_at(ser, 'AT+CPIN?')

        # Check signal strength (0-31, higher is better, 99 = no signal)
        send_at(ser, 'AT+CSQ')

        # Check network registration (response should be +CREG: 0,1 or 0,5)
        send_at(ser, 'AT+CREG?')

        # Set SMS to text mode
        send_at(ser, 'AT+CMGF=1')

        # Set the recipient number (include country code, e.g. +91XXXXXXXXXX for India)
        ser.write(f'AT+CMGS="{phone_number}"\r\n'.encode())
        time.sleep(1)
        resp = ser.read_all().decode(errors='ignore')
        print(f"<< {resp}")

        # Send message body, terminated with Ctrl+Z (ASCII 26)
        ser.write((message + chr(26)).encode())
        time.sleep(5)  # Wait for SMS to send
        response = ser.read_all().decode(errors='ignore').strip()
        print(f"<< {response}")

        if '+CMGS:' in response:
            print("✅ SMS sent successfully!")
        else:
            print("❌ SMS sending failed. Check signal/SIM.")

# --- Run ---
send_sms('+919987208133', 'Hi')
