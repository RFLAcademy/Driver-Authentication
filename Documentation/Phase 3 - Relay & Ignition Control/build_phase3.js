// Phase 3 — Relay & Ignition Control (RFL Academy template)
const fs = require("fs");
const { Packer } = require("docx");
const T = require("../_assets/rfl_template.js");
const { SEC, SUBSEC, P, bullet, callout, code, dataTable, imgPlaceholder, titleBlock, spacer, buildDoc, CONTENT_W } = T;

const children = [
  ...titleBlock("Relay & Ignition Control", "Multi-Factor Driver Authentication System  ·  Phase 3"),

  SEC("Overview", 1),
  P("Phase 3 connects the authentication logic of Phases 1 and 2 to physical hardware through a 3-channel relay board. The relay controller manages three independent loads: a timer-latch relay that keeps the Raspberry Pi powered, the LED lighting relay introduced in Phase 1, and the ignition relay that enables the vehicle only after a successful dual-factor authentication."),
  SUBSEC("1.1 Project Context"),
  P("Up to this point, authentication results existed only in software. Phase 3 makes them act on the world: a GRANTED decision energises the ignition relay, automatic lighting drives a real LED circuit, and a self-holding timer latch ensures the Pi has enough power-on time to boot and run before an external timer would otherwise cut power."),
  SUBSEC("1.2 Key Features"),
  bullet("3-channel relay control on BCM pins GPIO23 (timer latch), GPIO27 (LED), GPIO22 (ignition)"),
  bullet("Per-pin polarity: timer latch and ignition are active-high; the LED relay is active-low"),
  bullet("Self-holding timer latch energised on boot to keep the Pi powered past the external boot-timer window"),
  bullet("Ignition enabled only on a dual-factor GRANTED decision; disabled on DENIED or remote kill"),
  bullet("Automatic brightness-driven LED control with a debounce and SMS manual override"),
  bullet("Safe shutdown that releases ignition and LED but never de-energises the timer latch"),
  spacer(),
  callout("Phase Scope", "Phase 3 covers the relay controller, channel polarity, the timer-latch power hold, and how the ignition and LED relays are driven by the authentication and lighting logic. The SMS layer that issues remote relay commands is detailed in Phase 4."),

  SEC("Relay Channels", 2),
  SUBSEC("2.1 Channel Assignment"),
  P("The board exposes three independent relay channels. Because the channels use different relay modules, their trigger polarities differ — the controller accounts for this per pin via the ACTIVE_LOW_PINS set."),
  dataTable(["Channel", "BCM Pin", "Polarity", "Purpose"], [
    ["Timer Latch", "GPIO23", "Active-HIGH", "Self-holding power latch energised on boot; keeps the Pi powered"],
    ["LED Light", "GPIO27", "Active-LOW", "Cabin / sensor lighting, driven by the auto-brightness logic"],
    ["Ignition", "GPIO22", "Active-HIGH", "Vehicle ignition enable, gated on a GRANTED authentication"],
  ], [1900, 1500, 1900, CONTENT_W - 5300]),
  spacer(),
  callout("Per-Pin Polarity", "ACTIVE_LOW_PINS = {PIN_LED_RELAY}. Only the LED channel energises on a LOW signal; any pin not in this set is treated as active-high. The _set_pin() helper inverts the output level automatically so the rest of the code can simply request ON or OFF."),
  spacer(),
  SUBSEC("2.2 Wiring Guide"),
  dataTable(["Relay Terminal", "Connects To", "Notes"], [
    ["IN1", "Pi GPIO23 (pin 11)", "Timer-latch trigger"],
    ["IN2", "Pi GPIO27 (pin 13)", "LED trigger"],
    ["IN3", "Pi GPIO22 (pin 15)", "Ignition trigger"],
    ["VCC", "Pi 5V (pin 2 / 4)", "Relay board power"],
    ["GND", "Pi GND (pin 6, 9, 14…)", "Common ground"],
    ["COM", "Load supply rail", "Per channel"],
    ["NO", "Load positive terminal", "Normally-Open — closes when energised"],
  ], [2200, 3200, CONTENT_W - 5400]),
  imgPlaceholder("Relay Board Wiring Photo"),

  SEC("Timer-Latch Power Hold", 3),
  SUBSEC("3.1 Why a Latch"),
  P("The system is powered through an external timer that only holds power for a short boot window. To stay alive beyond that window, the Pi energises the timer-latch relay (GPIO23) the moment it boots; the latch relay then holds its own supply on. As long as GPIO23 stays HIGH, the Pi keeps power. This is the single most safety-critical channel in Phase 3."),
  SUBSEC("3.2 Boot and Shutdown Sequence"),
  code([
    "def relay_init():",
    "    _init_gpio()",
    "    timer_latch_on()        # GPIO23 HIGH — hold power on",
    "",
    "def relay_shutdown():",
    "    ignition_off(); led_relay_off()",
    "    # Timer latch intentionally left ON. Do NOT call GPIO.cleanup() —",
    "    # it releases GPIO23 to floating input and de-energises the latch.",
  ]),
  spacer(),
  callout("Critical — Never Call GPIO.cleanup()", "Calling GPIO.cleanup() resets GPIO23 to an input/floating state, which de-energises the latch relay and instantly cuts power to the Pi. The shutdown path must release only the ignition and LED channels and leave the timer latch driven HIGH.", "C0392B", "FCEDEC"),

  SEC("Ignition & LED Control", 4),
  SUBSEC("4.1 Ignition Gating"),
  P("The ignition relay (GPIO22) is the actuator for the whole authentication system. In a full authentication it is energised only when the dual-factor decision is GRANTED, and de-energised on DENIED:"),
  code([
    "if dec == \"GRANTED\":  ignition_active = True;  relay.ignition_on()   # GPIO22 HIGH",
    "else:                 ignition_active = False; relay.ignition_off()  # GPIO22 LOW",
  ]),
  P("Passive auto-checks never enable ignition; if an auto-check returns DENIED, ignition is forced off as a safety response. Ignition can also be killed remotely via the TURN OFF command (Phase 4)."),
  dataTable(["Trigger", "Action", "GPIO22"], [
    ["Full auth → GRANTED", "ignition_on()", "HIGH (enabled)"],
    ["Full auth → DENIED", "ignition_off()", "LOW (disabled)"],
    ["Auto-check → DENIED", "ignition_off()", "LOW (disabled)"],
    ["TURN OFF (remote)", "ignition_off()", "LOW (disabled)"],
    ["Shutdown", "ignition_off()", "LOW (disabled)"],
  ], [3400, 3000, CONTENT_W - 6400]),
  spacer(),
  SUBSEC("4.2 LED Relay"),
  P("Phase 1's auto-lighting logic now drives a physical LED circuit through the active-low GPIO27 relay, with a debounce so brief shadows do not cause flicker. A manual override (SMS LED ON / LED OFF) suspends the automatic logic so the driver can force the light on or off."),
  imgPlaceholder("On-screen “IGNITION ON” Banner"),

  SEC("Module, Config & Limitations", 5),
  SUBSEC("5.1 Public API"),
  dataTable(["Function", "Purpose"], [
    ["relay_init()", "Initialise GPIO and energise the timer latch (call once at startup)"],
    ["relay_shutdown()", "Release ignition + LED; leave timer latch ON; never cleanup()"],
    ["timer_latch_on() / _off()", "Drive GPIO23 (active-high)"],
    ["led_relay_on() / _off()", "Drive GPIO27 (active-low, auto-inverted)"],
    ["ignition_on() / _off()", "Drive GPIO22 (active-high)"],
  ], [3200, CONTENT_W - 3200]),
  spacer(),
  SUBSEC("5.2 Configuration"),
  dataTable(["Constant", "Value", "Description"], [
    ["PIN_TIMER_LATCH / LED / IGNITION", "23 / 27 / 22", "BCM relay pins"],
    ["ACTIVE_LOW_PINS", "{PIN_LED_RELAY}", "Pins that energise on a LOW signal"],
    ["USE_REAL_GPIO", "True", "True = drive real GPIO via RPi.GPIO; False = simulation"],
  ], [3400, 2000, CONTENT_W - 5400]),
  spacer(),
  SUBSEC("5.3 Known Limitations"),
  bullet("The timer-latch design assumes an external boot timer; on a bench supply the latch simply holds power until de-energised."),
  bullet("Relay modules must be powered from a stable 5V rail and share a common ground with the Pi."),
  bullet("Channel polarity is board-specific; swapping relay modules may require updating ACTIVE_LOW_PINS."),
  bullet("Ignition is an enable signal only — it does not crank the engine; final vehicle wiring is outside software scope."),
  spacer(),
  SUBSEC("5.4 What Comes Next — Phase 4"),
  bullet("SIM800 GSM module on /dev/ttyAMA2 for SMS-based remote control and alerts"),
  bullet("Remote ignition kill (TURN OFF) and LED override over SMS"),
];

const doc = buildDoc({ runningTitle: "Multi-Factor Driver Authentication System  |  Phase 3 Documentation", children });
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(__dirname + "/Phase3_Documentation.docx", buf); console.log("WROTE Phase3 (" + buf.length + " bytes)"); });
