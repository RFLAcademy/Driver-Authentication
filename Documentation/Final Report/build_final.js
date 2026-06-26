// Combined Final Report — all 5 phases, RFL Academy template.
const fs = require("fs");
const path = require("path");
const { Packer, Paragraph, TextRun, AlignmentType, TableOfContents, HeadingLevel } = require("docx");
const T = require("../_assets/rfl_template.js");
const { P, bullet, callout, code, dataTable, steps, imgPlaceholder, oneUp, twoUp, greenHeading, spacer, pb, buildDoc, CONTENT_W, GREEN, TITLE_K, GREY } = T;

const IMGDIR = path.join(__dirname, "..", "_assets", "phase1_images");
const img = (n) => fs.readFileSync(path.join(IMGDIR, `img_${String(n).padStart(2, "0")}.png`));

// report heading hierarchy: PART = H1, SEC = H2(+rule), SUB = H3
const PART = (label, title) => ([
  new Paragraph({ pageBreakBefore: true, spacing: { before: 2400, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: label, bold: true, color: GREEN, size: 30, font: "Arial" })] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, alignment: AlignmentType.CENTER, spacing: { before: 120, after: 200 },
    children: [new TextRun({ text: title, bold: true, color: TITLE_K, size: 52, font: "Arial" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, border: { bottom: { style: require("docx").BorderStyle.SINGLE, size: 12, color: GREEN, space: 6 } }, children: [] }),
  pb(),
]);
const SEC = (t, n) => greenHeading(`${n}. ${t}`, 2, true);
const SUB = (t) => greenHeading(t, 3, false);

const cover = [
  new Paragraph({ spacing: { before: 1200, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Multi-Factor Driver", bold: true, color: TITLE_K, size: 60, font: "Arial" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 },
    children: [new TextRun({ text: "Authentication System", bold: true, color: TITLE_K, size: 60, font: "Arial" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 },
    children: [new TextRun({ text: "Complete Technical Report", italics: true, bold: true, color: GREEN, size: 36, font: "Arial" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 360 },
    children: [new TextRun({ text: "Phases 1 – 5", bold: true, color: "404040", size: 30, font: "Arial" })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [new TextRun({ text: "Face Detection · Fingerprint · Relay & Ignition · GSM/SMS · Integration", color: "404040", size: 22, font: "Arial" })] }),
  imgPlaceholder("Full Assembled System Photo"),
  pb(),
  greenHeading("Table of Contents", 1, true),
  new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  pb(),
  greenHeading("Executive Summary", 1, true),
  P("This report consolidates the full technical documentation of the Multi-Factor Driver Authentication System — a Raspberry Pi-based unit that secures a vehicle's ignition behind two biometric factors and is fully operable by SMS. The work is organised into five phases, each delivering an independently testable subsystem:"),
  bullet("Phase 1 — Face Detection: Haar detection, multi-pose registration, LBPH recognition, and auto-lighting."),
  bullet("Phase 2 — Fingerprint Authentication: R307S enrollment, verification, and the dual-factor decision."),
  bullet("Phase 3 — Relay & Ignition Control: 3-channel relay, timer-latch power hold, and ignition gating."),
  bullet("Phase 4 — GSM/SMS Remote Control: SIM800 command/alert layer over the cellular network."),
  bullet("Phase 5 — System Integration & Deployment: the Main.py state machine, kiosk UI, and lifecycle."),
  spacer(),
  P("Each part below corresponds to one phase. Phase 1 includes the captured screenshots; remaining placeholders are provided for additional photos."),
];

const phase1 = [
  ...PART("Phase 1", "Face Detection"),
  SEC("Overview", 1),
  P("Phase 1 implements the core computer-vision pipeline: face detection, driver registration, real-time face recognition, and automatic LED lighting control. It is software-only and runs on a standard PC or Raspberry Pi with an attached camera."),
  SUB("1.1 Key Features"),
  bullet("Strict Haar Cascade face detection (centre-zone only, high confidence)"),
  bullet("iPhone-style multi-pose registration — 5 poses × 2 lighting × 20 samples = 200 samples"),
  bullet("LBPH face recognizer; multiple-face alert; debounced LED control; CSV logging"),
  SEC("System Architecture", 2),
  dataTable(["Module", "Responsibility"], [
    ["Face Detection", "Centre-zone Haar detection (minNeighbors=8, minSize=100×100)."],
    ["Registration", "5 poses × 2 lighting × 20 frames; trains LBPH."],
    ["Authentication", "Compares live ROI to the LBPH model against a confidence threshold."],
    ["LED Controller", "Central-ROI brightness with a debounced relay."],
  ], [2400, CONTENT_W - 2400]),
  ...oneUp(img(1), "System flow diagram — the full authentication pipeline", 360),
  SEC("Face Detection", 3),
  dataTable(["Constant", "Value", "Description"], [
    ["DETECT_SCALE", "1.1", "Image-pyramid scale factor"],
    ["DETECT_MIN_NEIGHBORS", "8", "Higher = fewer false positives"],
    ["DETECT_MIN_SIZE", "(100, 100)", "Minimum face size in pixels"],
    ["DETECT_ZONE_X / Y", "80 / 60 px", "Detection-zone edge insets"],
  ], [3000, 1700, CONTENT_W - 4700]),
  twoUp(img(2), "Single face — normal detection", img(3), "Multiple-face alert — access blocked"),
  P("During registration, detection is relaxed (minNeighbors=4, minSize=60×60) to allow angled poses."),
  SEC("Driver Registration", 4),
  callout("Sample Count", "5 poses × 2 lighting × 20 samples = 200 training samples stored in driver1_face.npy.", GREEN, "EAF7EF"),
  spacer(),
  steps([
    ["Look straight at the camera", "Baseline frontal view — normal + low light"],
    ["Turn head RIGHT / LEFT", "Profile variations"],
    ["Tilt head UP / DOWN", "Gaze variations"],
  ]),
  twoUp(img(4), "Step 1 — normal light", img(5), "Step 1 — low light"),
  twoUp(img(6), "Step 2 — turn right", img(7), "Step 3 — turn left"),
  twoUp(img(8), "Step 4 — tilt up", img(9), "Step 5 — tilt down"),
  ...oneUp(img(10), "Registration complete — “Driver 1 Registered!”", 340),
  SEC("Authentication", 5),
  P("LBPH returns a confidence value; lower is a better match. MATCH_THRESHOLD = 75: granted if label == 1 and confidence < 75."),
  twoUp(img(11), "Access granted — green box", img(12), "Access denied — red box"),
  SEC("LED Auto-Lighting & Logging", 6),
  P("Brightness is measured in a central ROI; the LED relay debounces with a 5-second confirmation (ON < 60, OFF > 80). All events are logged to auth_log.csv."),
  twoUp(img(13), "LED ON — low light", img(14), "LED OFF — good light"),
  ...oneUp(img(15), "auth_log.csv — timestamped event log", 520),
];

const phase2 = [
  ...PART("Phase 2", "Fingerprint Authentication"),
  SEC("Overview", 1),
  P("Phase 2 adds fingerprint authentication as a second factor. Face recognition is combined with a live R307S optical fingerprint scan, so the vehicle is only authorised when both factors agree."),
  SUB("1.1 Key Features"),
  bullet("R307S over UART (/dev/ttyAMA0, 57600 baud) via pyfingerprint"),
  bullet("Two-scan guided enrollment; on-sensor template at slot #1 with a disk flag"),
  bullet("Dual-factor decision: GRANTED only when face AND fingerprint match"),
  bullet("Scan states WAITING / SCANNING / LIFT / DONE; simulation mode for development"),
  SEC("Hardware & Wiring", 2),
  dataTable(["Wire", "Signal", "Pi Pin"], [
    ["Red / Black", "VCC / GND", "Pin 4 (5V) / Pin 6 (GND)"],
    ["Yellow / Green", "TXD / RXD", "Pin 10 (RX) / Pin 8 (TX)"],
    ["Blue", "TOUCH", "Pin 11 (GPIO17, active-low)"],
    ["White", "WAKEUP", "Leave floating"],
  ], [2000, 2400, CONTENT_W - 4400]),
  callout("Serial Setup", "raspi-config → Serial Port: login shell = No, hardware = Yes, reboot. Sensor port /dev/ttyAMA0."),
  SEC("Enrollment & Verification", 3),
  callout("Enroll Once, Verify Forever", "The template lives at sensor slot #1 and fingerprint_enrolled.flag is written to disk, surviving restarts.", GREEN, "EAF7EF"),
  spacer(),
  steps([
    ["Place finger on the sensor", "First scan into CharBuffer 1"],
    ["Place the SAME finger again", "Second scan confirms the first"],
    ["Template created and stored", "Stored at slot #1; flag saved"],
  ]),
  code([
    "result = f.searchTemplate(); slot, score = result[0], result[1]",
    "if slot == -1: return False, conf           # no match",
    "confidence = round(min(99.9, score/2.0),1)  # MATCH",
  ]),
  SEC("Dual-Factor Decision", 4),
  code(["final = \"GRANTED\" if (face_matched and fp_matched) else \"DENIED\""]),
  callout("Face-Only Auto-Check", "A passive auto-check decides on the face alone for presence detection — never to grant ignition. Full authentication always requires both factors."),
];

const phase3 = [
  ...PART("Phase 3", "Relay & Ignition Control"),
  SEC("Overview", 1),
  P("Phase 3 connects the authentication logic to hardware through a 3-channel relay: a timer-latch relay that keeps the Pi powered, the LED relay, and the ignition relay enabled only on a dual-factor GRANTED decision."),
  SEC("Relay Channels", 2),
  dataTable(["Channel", "BCM Pin", "Polarity", "Purpose"], [
    ["Timer Latch", "GPIO23", "Active-HIGH", "Self-holding power latch energised on boot"],
    ["LED Light", "GPIO27", "Active-LOW", "Cabin / sensor lighting (auto-brightness)"],
    ["Ignition", "GPIO22", "Active-HIGH", "Ignition enable, gated on GRANTED"],
  ], [1900, 1500, 1900, CONTENT_W - 5300]),
  callout("Per-Pin Polarity", "ACTIVE_LOW_PINS = {PIN_LED_RELAY}; only the LED channel energises on LOW. _set_pin() inverts the level automatically."),
  SEC("Timer-Latch Power Hold", 3),
  P("The Pi energises GPIO23 on boot; the latch then holds its own supply on, keeping the Pi powered past the external boot-timer window."),
  code([
    "def relay_init(): _init_gpio(); timer_latch_on()   # GPIO23 HIGH",
    "def relay_shutdown(): ignition_off(); led_relay_off()",
    "# latch left ON; never GPIO.cleanup() (would cut power)",
  ]),
  callout("Critical — Never Call GPIO.cleanup()", "cleanup() floats GPIO23, de-energising the latch and instantly cutting power. Shutdown releases only ignition + LED.", "C0392B", "FCEDEC"),
  SEC("Ignition & LED", 4),
  dataTable(["Trigger", "Action", "GPIO22"], [
    ["Full auth → GRANTED", "ignition_on()", "HIGH"],
    ["DENIED / auto-check DENIED", "ignition_off()", "LOW"],
    ["TURN OFF (remote)", "ignition_off()", "LOW"],
  ], [3400, 3000, CONTENT_W - 6400]),
  P("The LED auto-lighting now drives the active-low GPIO27 relay, with an SMS LED ON / LED OFF override."),
];

const phase4 = [
  ...PART("Phase 4", "GSM / SMS Remote Control"),
  SEC("Overview", 1),
  P("Phase 4 makes the system remotely operable over the cellular network. A SIM800 GSM module lets the owner control and monitor the vehicle entirely by SMS, and pushes alerts back on every access decision."),
  callout("Active Hardware Status", "The SIM800 is the main open hardware issue: it may not respond to AT commands until a 2.8 V (module) vs 3.3 V (Pi) UART logic-level concern is resolved. See Troubleshooting.", "C0392B", "FCEDEC"),
  SEC("Hardware & Architecture", 2),
  dataTable(["Setting", "Value", "Notes"], [
    ["Serial port", "/dev/ttyAMA2", "UART2 overlay (separate from R307S)"],
    ["Baud / Mode", "115200 / text", "AT+CMGF=1 SMS text mode"],
    ["Country code", "+91", "Prepended to the 10-digit number"],
  ], [2100, 2600, CONTENT_W - 4700]),
  P("A persistent GsmPoller thread holds the port open and polls every 1.5 s; outbound sends use separate short-lived connections so they never block polling."),
  callout("Why Messages Are Deleted Immediately", "Each SMS from AT+CMGL is deleted with AT+CMGD as soon as it is read — SIM slot indices get reused, so a 'seen' set would skip reused slots and fill storage."),
  SEC("Command Reference", 3),
  dataTable(["Command", "Effect"], [
    ["AUTH", "Run full dual-factor authentication"],
    ["REGISTER FACE / FP / PHONE", "Enroll face / fingerprint / owner number"],
    ["STATUS / LOG / HELP", "Status summary / last 5 logs / command list"],
    ["TURN OFF", "Kill the ignition relay"],
    ["LED ON / OFF, WAKE UP", "Lighting override; wake from sleep"],
    ["RESET / RESET CONFIRM <pwd>", "Begin / confirm a password-protected data reset"],
  ], [3200, CONTENT_W - 3200]),
  SEC("Troubleshooting (hardware first)", 4),
  bullet("Logic levels — SIM800 UART ≈2.8 V vs Pi 3.3 V; a level shifter on TX/RX may be needed."),
  bullet("Power — hold under ~2 A transmit bursts; brownouts drop the module mid-command."),
  bullet("Signal — AT+CPIN? READY, AT+CSQ not 99, AT+CREG? 0,1 or 0,5. Test/GSM_test.py runs the full sequence."),
];

const phase5 = [
  ...PART("Phase 5", "System Integration & Deployment"),
  SEC("Overview", 1),
  P("Phase 5 ties every subsystem from Phases 1–4 into a single always-on application driven by a state machine and presented as a full-screen kiosk. Main.py is the orchestrator: camera, UI, state, and SMS routing."),
  SEC("Architecture & Threading", 2),
  dataTable(["Module", "Role", "Phase"], [
    ["FaceDetection / fingerprint_sim", "Recognition + fingerprint", "1 / 2"],
    ["relay_controller / sms_alert", "Relays + GSM SMS", "3 / 4"],
    ["logger / first_boot", "Logs + setup wizard", "1–5 / 5"],
    ["Main.py", "State machine, UI, lifecycle, dispatch", "5"],
  ], [3200, CONTENT_W - 4800, 1600]),
  P("The main thread runs the render loop, state machine, and SMS handling (all shared-state mutation here); workers and the GsmPoller run in the background."),
  SEC("State Machine", 3),
  dataTable(["State", "Meaning"], [
    ["IDLE / SLEEPING", "Live preview / dimmed after inactivity (SMS still active)"],
    ["FIRST_BOOT", "Guided setup wizard over SMS"],
    ["REG_FACE / REG_FP", "Registration / enrollment in progress"],
    ["AUTHING / RESULT", "Authentication running / showing the outcome"],
    ["RESETTING", "Data reset being executed"],
  ], [2600, CONTENT_W - 2600]),
  SEC("First-Boot, Kiosk & Lifecycle", 4),
  dataTable(["Setup Step", "Required?", "Completed By"], [
    ["password / face / fingerprint", "Required", "SET PASSWORD / REGISTER FACE / REGISTER FP"],
    ["phone", "Optional", "REGISTER PHONE <num>"],
  ], [3000, 1800, CONTENT_W - 4800]),
  P("The UI is one full-screen OpenCV window, display-only, auto-detecting the GTK/Wayland/X11 backend. On boot relay_init() energises the timer latch; on exit relay_shutdown() releases ignition + LED but leaves the latch ON."),
  callout("Power-Safe Lifecycle", "The timer latch is energised first on boot and left on through shutdown, guaranteeing stable power for the entire run.", GREEN, "EAF7EF"),
  spacer(),
  code([
    "pip install opencv-contrib-python numpy picamera2 \\",
    "            pyfingerprint pyserial RPi.GPIO --break-system-packages",
    "python3 Main.py",
  ]),
  P("The in-app kiosk is implemented; OS-level autostart at session start (Wayland/labwc) is the final commissioning step."),
  spacer(),
  P("With Phase 5 the system is functionally complete: a single Raspberry Pi unit that recognises a driver's face and fingerprint, gates ignition through a relay, holds its own power, and is fully operable by SMS — an unattended full-screen kiosk documented end to end across the five phases."),
];

const children = [...cover, ...phase1, ...phase2, ...phase3, ...phase4, ...phase5];
const doc = buildDoc({ runningTitle: "Multi-Factor Driver Authentication System  |  Complete Technical Report", children });
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(__dirname + "/MultiFactor_Driver_Auth_Full_Report.docx", buf); console.log("WROTE Full Report (" + buf.length + " bytes)"); });
