"""
Multi-Factor Driver Authentication System
Module: 3-Channel Relay Controller
------------------------------------
Relay Pin Assignment (BCM numbering):
  GPIO 23  →  Channel 1: Timer Latch  (active-high  — energised on boot, stays energised)
  GPIO 27  →  Channel 2: LED Light    (active-low   — energise by driving pin LOW)
  GPIO 22  →  Channel 3: Ignition     (active-high  — energise by driving pin HIGH)

Wiring guide:
  Relay IN1  → Pi GPIO 23  (pin 11)
  Relay IN2  → Pi GPIO 27  (pin 13)
  Relay IN3  → Pi GPIO 22  (pin 15)
  Relay VCC  → Pi 5V       (pin 2 or 4)
  Relay GND  → Pi GND      (pin 6, 9, 14, etc.)
  Relay COM  → your load's supply rail
  Relay NO   → your load's positive terminal (Normally Open — closes when HIGH)

Note: Channels use different relay modules with different polarities -
      Timer Latch and Ignition are ACTIVE-HIGH, LED is ACTIVE-LOW.
      See ACTIVE_LOW_PINS below to adjust per-channel polarity.
"""

import time

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────
PIN_TIMER_LATCH = 23   # BCM - active-high
PIN_LED_RELAY   = 27   # BCM - active-low
PIN_IGNITION    = 22   # BCM - active-high

# Pins whose relay module energises on a LOW signal.
# Any pin not listed here is treated as active-high.
ACTIVE_LOW_PINS = {PIN_LED_RELAY}

USE_REAL_GPIO = True   # Set False to run without hardware (simulation mode)

# ─────────────────────────────────────────────
# GPIO SETUP
# ─────────────────────────────────────────────
_gpio_ok = False
_GPIO = None

def _init_gpio():
    global _gpio_ok, _GPIO
    if not USE_REAL_GPIO:
        print("[RELAY] Simulation mode — no GPIO")
        return False
    try:
        import RPi.GPIO as GPIO
        _GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for pin in (PIN_TIMER_LATCH, PIN_LED_RELAY, PIN_IGNITION):
            GPIO.setup(pin, GPIO.OUT)
            # Default all relays OFF (per-pin polarity)
            off_level = GPIO.HIGH if pin in ACTIVE_LOW_PINS else GPIO.LOW
            GPIO.output(pin, off_level)
        _gpio_ok = True
        print(f"[RELAY] GPIO initialised — pins {PIN_TIMER_LATCH}, {PIN_LED_RELAY}, {PIN_IGNITION}")
        return True
    except Exception as e:
        print(f"[RELAY] GPIO init failed: {e}")
        _gpio_ok = False
        return False

def _set_pin(pin: int, state: bool):
    """
    state=True  → relay ON  (energised)
    state=False → relay OFF (de-energised)
    Handles per-pin active-low/active-high inversion automatically.
    """
    if not _gpio_ok or _GPIO is None:
        label = {PIN_TIMER_LATCH: "TIMER_LATCH",
                 PIN_LED_RELAY:   "LED",
                 PIN_IGNITION:    "IGNITION"}.get(pin, f"GPIO{pin}")
        print(f"[RELAY] (sim) {label} → {'ON' if state else 'OFF'}")
        return
    active_low = pin in ACTIVE_LOW_PINS
    level = (not state) if active_low else state
    _GPIO.output(pin, _GPIO.HIGH if level else _GPIO.LOW)

# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def relay_init():
    """Call once at startup. Sets timer latch HIGH immediately."""
    _init_gpio()
    timer_latch_on()
    print("[RELAY] Timer latch energised on boot.")

def relay_shutdown():
    """Call before shutdown. De-energises ignition/LED, leaves timer latch driven ON."""
    ignition_off()
    led_relay_off()
    # Timer latch intentionally left ON — do NOT call GPIO.cleanup(), it would
    # release GPIO23 back to input/floating and de-energise the latch relay.
    print("[RELAY] Ignition + LED released. Timer latch remains ON.")

# ── Timer Latch ──────────────────────────────
def timer_latch_on():
    _set_pin(PIN_TIMER_LATCH, True)
    print("[RELAY] Timer latch → ON")

def timer_latch_off():
    _set_pin(PIN_TIMER_LATCH, False)
    print("[RELAY] Timer latch → OFF")

# ── LED Light ────────────────────────────────
def led_relay_on():
    _set_pin(PIN_LED_RELAY, True)
    print("[RELAY] LED relay → ON")

def led_relay_off():
    _set_pin(PIN_LED_RELAY, False)
    print("[RELAY] LED relay → OFF")

# ── Ignition ─────────────────────────────────
def ignition_on():
    _set_pin(PIN_IGNITION, True)
    print("[RELAY] Ignition → ENABLED")

def ignition_off():
    _set_pin(PIN_IGNITION, False)
    print("[RELAY] Ignition → DISABLED")

# ─────────────────────────────────────────────
# STANDALONE TEST
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=== Relay Controller Test ===")
    relay_init()
    time.sleep(1)

    print("\nTesting LED relay...")
    led_relay_on();  time.sleep(1)
    led_relay_off(); time.sleep(1)

    print("\nTesting Ignition relay...")
    ignition_on();   time.sleep(1)
    ignition_off();  time.sleep(1)

    print("\nShutdown sequence...")
    relay_shutdown()
    print("Done.")
