import RPi.GPIO as GPIO
import time

RELAY_PIN = 27
INTERVAL  = 1   # seconds between toggles

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.LOW)

print(f"Testing relay on GPIO {RELAY_PIN}. Press Ctrl+C to stop.\n")

try:
    while True:
        GPIO.output(RELAY_PIN, GPIO.HIGH)
        print("Relay ON  ●")
        time.sleep(INTERVAL)

        GPIO.output(RELAY_PIN, GPIO.LOW)
        print("Relay OFF ○")
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\nStopped by user.")

finally:
    GPIO.cleanup()
    print("GPIO cleaned up.")
