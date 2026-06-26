// Phase 4 — GSM / SMS Remote Control (RFL Academy template)
const fs = require("fs");
const { Packer } = require("docx");
const T = require("../_assets/rfl_template.js");
const { SEC, SUBSEC, P, bullet, callout, code, dataTable, imgPlaceholder, titleBlock, spacer, buildDoc, CONTENT_W } = T;

const children = [
  ...titleBlock("GSM / SMS Remote Control", "Multi-Factor Driver Authentication System  ·  Phase 4"),

  SEC("Overview", 1),
  P("Phase 4 makes the system remotely operable over the cellular network. A SIM800 GSM module lets the owner control and monitor the vehicle entirely by SMS — triggering authentication, killing the ignition, toggling lights, checking status, and reading logs — and pushes alerts back to a registered phone whenever access is granted or denied."),
  SUBSEC("1.1 Project Context"),
  P("Earlier phases all assume someone is physically at the vehicle. Phase 4 removes that assumption: commands arrive as text messages, are parsed into structured actions, and drive the same state machine and relays built in Phases 1–3. The GSM link is also the system's outbound channel — every important event can be reported to the owner in real time, with no internet connection required."),
  SUBSEC("1.2 Key Features"),
  bullet("SIM800 GSM module on UART /dev/ttyAMA2 at 115200 baud, in SMS text mode (AT+CMGF=1)"),
  bullet("Persistent background poller (GsmPoller) that reads new SMS every 1.5 seconds"),
  bullet("Outbound SMS on separate short-lived connections, so sending never blocks polling"),
  bullet("Structured command parser supporting single- and two-word commands"),
  bullet("Registered owner phone (10-digit, +91) persisted to disk for alerts"),
  bullet("Automatic alerts on GRANTED / DENIED authentication and ignition changes"),
  bullet("Password-protected remote data reset"),
  spacer(),
  callout("Active Hardware Status", "As of this writing the SIM800 module is the system's main open hardware issue: it may not respond to AT commands until a logic-level concern on the module's UART (≈2.8 V) versus the Pi (3.3 V) is resolved. See Section 5 (Troubleshooting) before assuming a software fault.", "C0392B", "FCEDEC"),

  SEC("GSM Hardware & Architecture", 2),
  SUBSEC("2.1 Serial Link"),
  P("The system uses a SIM800-series GSM module (SIM800C / SIM800L) on /dev/ttyAMA2 (a UART2 overlay), separate from the fingerprint UART, so both peripherals can run at once."),
  dataTable(["Setting", "Value", "Notes"], [
    ["Serial port", "/dev/ttyAMA2", "UART2 overlay — separate from the R307S port"],
    ["Baud rate", "115200", "SIM800 default for AT over UART"],
    ["Mode", "SMS text (AT+CMGF=1)", "Human-readable SMS, not PDU mode"],
    ["SIM storage", "AT+CPMS=\"SM\"", "Read / delete messages from the SIM"],
    ["Country code", "+91", "Prepended to the stored 10-digit number"],
  ], [2100, 2600, CONTENT_W - 4700]),
  spacer(),
  callout("Health-Check AT Commands", "Before trusting the link, confirm: AT+CPIN? (SIM ready), AT+CSQ (signal 0–31; 99 = no signal), and AT+CREG? (network registration — expect +CREG: 0,1 or 0,5). Test/GSM_test.py runs exactly this sequence and then sends a test SMS."),
  spacer(),
  SUBSEC("2.2 Send / Receive Split"),
  bullet("Receiving — a single GsmPoller thread holds the port open permanently and polls for new messages."),
  bullet("Sending — each outbound message opens its own short-lived serial connection in a background thread, so a slow send can never stall the poll loop."),
  spacer(),
  callout("Why Messages Are Deleted Immediately", "Every message returned by AT+CMGL=\"ALL\" is still on the SIM, so it is either new or a leftover. Each is deleted with AT+CMGD as soon as it is read. SIM slot indices get reused, so a persistent “seen” set would cause reused slots to be skipped forever and the SIM storage to fill up — dropping future incoming SMS."),

  SEC("Command Protocol & Reference", 3),
  SUBSEC("3.1 Parsing"),
  P("Incoming message bodies are normalised and split into a command word and arguments. A fixed set of two-word commands (REGISTER FACE, TURN OFF, LED ON…) is recognised first; otherwise the first word is the command and the remainder is its argument. Unknown commands are logged and ignored. Commands are dispatched on the main thread only, and each replies to its sender."),
  SUBSEC("3.2 SmsCommand Structure"),
  dataTable(["Field", "Description"], [
    ["cmd", "Uppercase command, e.g. \"AUTH\", \"TURN OFF\""],
    ["args", "Remainder after the command word (e.g. the phone number)"],
    ["sender", "Originating number, e.g. \"+919876543210\""],
    ["raw_body", "Original message text as received"],
    ["index", "SIM storage slot index"],
  ], [2000, CONTENT_W - 2000]),
  spacer(),
  SUBSEC("3.3 Command Reference"),
  dataTable(["Command", "Effect / Reply"], [
    ["AUTH", "Run full dual-factor authentication (requires face + fingerprint enrolled)"],
    ["REGISTER FACE / FP", "Start guided face registration / fingerprint enrollment"],
    ["REGISTER PHONE <num>", "Save a 10-digit owner number for alerts"],
    ["SET PASSWORD <pwd>", "Change the admin password (min 4 chars)"],
    ["STATUS", "Reply with face/FP/phone/ignition/LED/state summary"],
    ["LOG", "Reply with the last 5 log entries"],
    ["TURN OFF", "Kill the ignition relay"],
    ["LED ON / LED OFF", "Manually override the lighting relay"],
    ["WAKE UP", "Wake the system from sleep"],
    ["RESET / RESET CONFIRM <pwd>", "Begin / confirm a full data reset"],
    ["HELP", "Reply with the full command list"],
  ], [3000, CONTENT_W - 3000]),
  imgPlaceholder("Phone Screenshot — Commands & Replies"),

  SEC("Alerts", 4),
  SUBSEC("4.1 Send API"),
  dataTable(["Function", "Purpose"], [
    ["send_alert(message)", "Non-blocking send to the registered owner number"],
    ["send_alert_sync(message)", "Blocking send; returns True/False on success"],
    ["send_reply(to_number, msg)", "Non-blocking reply to any sender"],
  ], [3200, CONTENT_W - 3200]),
  spacer(),
  SUBSEC("4.2 Send Sequence"),
  P("A send opens the port, puts the module in text mode, addresses the recipient, writes the body terminated by Ctrl+Z, and confirms success by looking for +CMGS: in the response."),
  code([
    "AT / ATE0 / AT+CMGF=1          # link check, echo off, text mode",
    "AT+CMGS=\"+91XXXXXXXXXX\"         # recipient",
    "<message text> + Ctrl+Z         # 0x1A terminates the body",
    "# success if reply contains  +CMGS:",
  ]),

  SEC("Configuration & Troubleshooting", 5),
  SUBSEC("5.1 Configuration"),
  dataTable(["Constant", "Value", "Description"], [
    ["GSM_PORT", "/dev/ttyAMA2", "Serial port for the SIM800 module"],
    ["BAUD_RATE", "115200", "Serial baud rate"],
    ["USE_REAL_GSM", "True", "True = real module; False = print-only simulation"],
    ["POLL_INTERVAL", "1.5", "Seconds between inbound SMS polls"],
  ], [2600, 2400, CONTENT_W - 5000]),
  spacer(),
  SUBSEC("5.2 Module Not Responding to AT (hardware first)"),
  bullet("Logic levels — the SIM800 UART may idle around 2.8 V while the Pi expects 3.3 V; a level shifter on TX/RX may be required for reliable AT responses."),
  bullet("Power — confirm a supply that can hold under ~2 A transmit bursts; brownouts drop the module mid-command."),
  bullet("Wiring — verify TX↔RX are crossed correctly and that the Pi and module share a common ground."),
  bullet("Port — confirm the UART2 overlay is enabled and /dev/ttyAMA2 exists; the serial login shell must be disabled."),
  spacer(),
  SUBSEC("5.3 No Signal / Not Sending"),
  bullet("AT+CSQ returns 99 — no antenna or no coverage; fit a proper antenna."),
  bullet("AT+CREG? not 0,1 / 0,5 — not registered on the network; check SIM activation and signal."),
  bullet("AT+CPIN? not READY — SIM missing, locked, or seated poorly."),
  spacer(),
  P("Test/GSM_test.py is the first-line check: it runs AT, ATE0, AT+CPIN?, AT+CSQ, AT+CREG?, AT+CMGF=1 and then attempts a test SMS, printing every response so the failing step is obvious."),
  imgPlaceholder("GSM_test.py Output (AT responses)"),
];

const doc = buildDoc({ runningTitle: "Multi-Factor Driver Authentication System  |  Phase 4 Documentation", children });
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(__dirname + "/Phase4_Documentation.docx", buf); console.log("WROTE Phase4 (" + buf.length + " bytes)"); });
