# Driver-Authentication

A multi-factor driver authentication system for commercial vehicles, built on a Raspberry Pi. It combines face recognition and fingerprint verification to gate ignition, drives relay-controlled hardware (LED, timer latch, ignition), and is fully monitorable and controllable remotely over SMS via a GSM module.

---

## ✨ Features

- **Multi-pose face registration** — guided 5-step capture (straight, right, left, up, down), each in normal and simulated low-light conditions
- **LBPH face recognition** — robust to minor lighting and pose variation
- **Fingerprint verification (R307S)** — second authentication factor required after face match
- **Strict authentication-mode detection** — high `minNeighbors` and minimum face size to reject false positives
- **Debounced LED relay control** — hysteresis window prevents flickering from transient brightness changes
- **Relay-controlled ignition** — energised only after both factors pass; remote `TURN OFF` kill switch over SMS
- **Full SMS command interface** — registration, status, logs, password/reset, and ignition control all driven by text message; no keyboard required
- **Persistent GSM polling** — long-lived serial connection to the SIM800C with auto-reconnect, replacing slow per-cycle AT-command handshakes
- **CSV event logging** — every authentication attempt, LED state change, relay action, and SMS command is timestamped and recorded
- **Fullscreen display UI** — status-only OpenCV interface (1280×720) for in-vehicle display

---

## 🧩 Hardware

| Component | Interface |
|---|---|
| Raspberry Pi 4B (Raspberry Pi OS Bookworm) | — |
| Pi Camera Module | CSI ribbon (Picamera2/libcamera) |
| R307S fingerprint sensor | `/dev/ttyAMA0` (GPIO 14/15) |
| SIM800C GSM module | `/dev/ttyAMA2` (GPIO 0/1, `dtoverlay=uart2`) |
| 3-channel relay board | GPIO 23 Timer Latch · GPIO 27 LED (active-low) · GPIO 22 Ignition |
| 3" display | Fullscreen OpenCV UI, 1280×720 |

---

## 📋 Requirements

- Python 3.7+
- OpenCV with contrib modules
- NumPy
- `lgpio` (relay control on Raspberry Pi)
- `pyserial` (fingerprint sensor + GSM module)

```bash
pip install opencv-contrib-python numpy lgpio pyserial
```

> `opencv-contrib-python` is required for LBPH and conflicts with `opencv-python` — uninstall the latter first.

---

## 🚀 Usage

```bash
python Code/Main.py
```

The system is display-only — there is no keyboard interaction. All control happens over SMS sent to the number in the GSM module.

---

## 📱 SMS Commands

| Command | Action |
|---|---|
| `AUTH` | Trigger authentication |
| `REGISTER FACE` | Start face registration (requires physical presence at the device) |
| `REGISTER FP` | Start fingerprint registration (requires physical presence) |
| `REGISTER PHONE <10digits>` | Set the alert/notification phone number |
| `SET PASSWORD <pwd>` | Set or change the admin password |
| `STATUS` | Request current system status |
| `LOG` | Request the last 5 log entries |
| `RESET` → `RESET CONFIRM <pwd>` | Two-step full data wipe (confirmation expires after 120s) |
| `TURN OFF` | Kill ignition remotely |
| `LED ON` / `LED OFF` | Manual LED override |
| `WAKE UP` | Wake the display from sleep |
| `HELP` | Reply with the full command list |

Every command receives a confirmation SMS in response. Read messages are deleted from the SIM after processing.

---

## 🔐 Registration Process

Face registration follows an iPhone Face ID–style flow, capturing samples under normal and simulated low-light conditions for each pose:

| Step | Instruction |
|------|-------------|
| 1 | Look straight at the camera |
| 2 | Slowly turn head **right** |
| 3 | Slowly turn head **left** |
| 4 | Tilt head **up** |
| 5 | Tilt head **down** |

Fingerprint registration is handled separately by the R307S sensor via `REGISTER FP`. Both factors must be enrolled and must both pass for authentication (`AUTH`) to succeed and ignition to be energised.

---

## ⚙️ Configuration

Key tunable parameters (`Code/FaceDetection.py`, `Code/Main.py`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MATCH_THRESHOLD` | `75` | Max LBPH confidence for a match (lower = stricter) |
| `SAMPLES_PER_STEP` | `20` | Frames captured per lighting sub-pass per pose |
| `BRIGHTNESS_LOW` | `80` | Pixel brightness below which LED turns ON |
| `BRIGHTNESS_OK` | `100` | Pixel brightness above which LED turns OFF |
| `LED_CONFIRM_SECS` | `5.0` | Seconds brightness must stay stable before LED switches |
| `DETECT_MIN_NEIGHBORS` | `8` | Haar Cascade strictness in authentication mode |
| `DETECT_MIN_SIZE` | `(100, 100)` | Minimum face bounding box (rejects background noise) |
| `RELAY_LED_HARDWARE` | `False` | Set `True` to enable GPIO relay output for LED |
| `RESET_CONFIRM_TIMEOUT` | `120.0` | Seconds before a pending `RESET` expires |
| `USE_REAL_GPIO` (`relay_controller.py`) | `True` | Set `False` to run relays in simulation mode without hardware |

---

## 📊 Event Log

All events are appended to `Data/auth_log.csv`:

```
Timestamp,Event,Detail,Result
2026-06-20 14:32:07,SYSTEM_STARTED,N/A,N/A
2026-06-20 14:32:15,DRIVER_REGISTERED,Face: 200 samples 5 poses x2 lighting,SUCCESS
2026-06-20 14:33:01,FACE_MATCH,conf=42.3,GRANTED
2026-06-20 14:33:04,FINGERPRINT_MATCH,id=1,GRANTED
2026-06-20 14:33:05,IGNITION,Both factors passed,ON
2026-06-20 14:35:22,FACE_NO_MATCH,conf=91.7,DENIED
2026-06-20 14:36:10,LED_RELAY,Low brightness confirmed,ON
2026-06-20 14:40:00,SMS_COMMAND,TURN OFF,EXECUTED
```

---

## 🗂️ Project Structure

```
├── Code/
│   ├── Main.py                # State machine, fullscreen UI, SMS command dispatcher
│   ├── FaceDetection.py        # LBPH face registration/recognition
│   ├── fingerprint_sim.py      # R307S fingerprint sensor interface
│   ├── sms_alert.py            # GSM send/receive, persistent serial poller (GsmPoller)
│   ├── relay_controller.py     # GPIO relay control via lgpio
│   ├── logger.py               # CSV session logging
│   ├── first_boot.py           # First-boot setup flag management
│   └── Test/                   # Standalone hardware test scripts
├── Data/
│   └── auth_log.csv            # Event log (generated on first run)
├── Documentation/              # Per-phase build docs + final report
└── README.md
```

---

## 🔭 Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Face detection, registration, authentication, LED control |
| Phase 2 | ✅ Complete | Fingerprint sensor (second factor) |
| Phase 3 | ✅ Complete | Relay module for ignition and timer-latch power |
| Phase 4 | ✅ Complete | GSM SMS remote control (registration, status, logs, reset, ignition kill) |
| Phase 5 | 🔧 In progress | System integration & deployment — hardware validation in progress |

---

## ⚠️ Known Limitations / Open Issues

- **Camera not detected** (`list index out of range` from libcamera) — needs hardware diagnosis: reseat the CSI ribbon cable, verify `camera_auto_detect=1` and `gpu_mem=128` in `/boot/firmware/config.txt`
- **SIM800C voltage mismatch** under investigation — module logic is 2.8V vs. the Pi's 3.3V output; VMCU pin must tie to Pi 3.3V, a level shifter may be required
- End-to-end SMS send/receive validation pending the hardware fixes above
- Haar Cascade detection can struggle with head angles beyond ~45° — mitigated by relaxed parameters during registration
- Only one driver profile supported
- Do **not** call `GPIO.cleanup()` — it de-energises the timer latch relay; relay state is managed exclusively via `lgpio`
- GPIO 17 is reserved for the fingerprint sensor's TOUCH pin
- `dtoverlay=disable-bt` is required to free `/dev/ttyAMA0` for the fingerprint sensor
- All UI strings must be ASCII-only — OpenCV fonts can't render Unicode/special characters
- Kiosk/autostart on a fresh OS image (`~/.config/labwc/autostart`, with startup delay for Wayland) not yet finalized
- Re-register if the lighting environment changes substantially from when the model was trained

---

## 📄 License

This project is for educational and prototype purposes.
