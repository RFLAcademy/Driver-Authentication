# Driver-Authentication

A computer vision–based driver authentication system built with OpenCV. Phase 1 implements iPhone-style face registration, real-time face recognition, and automatic LED lighting control — designed for use in commercial vehicles to prevent unauthorized access.

---

## ✨ Features

- **Multi-pose face registration** — guided 5-step capture (straight, right, left, up, down), each in normal and simulated low-light conditions (200 samples total)
- **LBPH face recognition** — robust to minor lighting and pose variation
- **Strict authentication-mode detection** — centre-zone only, high `minNeighbors` to reject false positives
- **Multiple face alert** — access blocked with a red banner if more than one person is in frame
- **Debounced LED relay control** — 5-second hysteresis prevents flickering from transient brightness changes
- **CSV event logging** — every authentication attempt, LED state change, and system event is timestamped and recorded

---

## 📋 Requirements

- Python 3.7+
- OpenCV with contrib modules
- NumPy

```bash
pip install opencv-python opencv-contrib-python numpy
```

> **Hardware (optional):** USB or CSI camera. For physical LED relay control on Raspberry Pi, set `RELAY_LED_HARDWARE = True` and add your `GPIO.output()` calls.

---

## 🚀 Usage

```bash
python driver_auth_phase1.py
```

| Key | Action |
|-----|--------|
| `R` | Start driver registration |
| `Q` | Quit and save log |

---

## 🔐 Registration Process

Registration follows an iPhone Face ID–style flow. For each of the 5 poses, the system captures 20 frames under normal lighting and 20 under simulated low light:

| Step | Instruction |
|------|-------------|
| 1 | Look straight at the camera |
| 2 | Slowly turn head **right** |
| 3 | Slowly turn head **left** |
| 4 | Tilt head **up** |
| 5 | Tilt head **down** |

The trained LBPH model is saved to `driver1_face.npy` and loaded automatically on the next run.

---

## ⚙️ Configuration

All tunable parameters are at the top of the script:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MATCH_THRESHOLD` | `75` | Max LBPH confidence for a match (lower = stricter) |
| `SAMPLES_PER_STEP` | `20` | Frames captured per lighting sub-pass per pose |
| `BRIGHTNESS_LOW` | `60` | Pixel brightness below which LED turns ON |
| `BRIGHTNESS_OK` | `80` | Pixel brightness above which LED turns OFF |
| `LED_CONFIRM_SECS` | `5.0` | Seconds brightness must stay stable before LED switches |
| `DETECT_MIN_NEIGHBORS` | `8` | Haar Cascade strictness in authentication mode |
| `DETECT_MIN_SIZE` | `(100, 100)` | Minimum face bounding box (rejects background noise) |
| `RELAY_LED_HARDWARE` | `False` | Set `True` to enable GPIO relay output |

---

## 📊 Event Log

All events are appended to `auth_log.csv`:

```
Timestamp,Event,Detail,Result
2025-05-18 14:32:07,SYSTEM_STARTED,N/A,N/A
2025-05-18 14:32:15,DRIVER_1_REGISTERED,200 samples 5 poses x2 lighting,SUCCESS
2025-05-18 14:33:01,FACE_MATCH,conf=42.3,GRANTED
2025-05-18 14:35:22,FACE_NO_MATCH,conf=91.7,DENIED
2025-05-18 14:36:10,LED_RELAY,Low brightness confirmed,ON
```

---

## 🗂️ Project Structure

```
├── driver_auth_phase1.py   # Main script (Phase 1)
├── driver1_face.npy        # Saved LBPH model (generated after registration)
├── auth_log.csv            # Event log (generated on first run)
└── README.md
```

---

## 🔭 Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Face detection, registration, authentication, LED control |
| Phase 2 | 🔜 Planned | Fingerprint sensor (second factor) + SD card hardware logging |
| Phase 3 | 🔜 Planned | Relay module for vehicle ignition, multi-driver support |

---

## ⚠️ Known Limitations

- Haar Cascade detection can struggle with head angles beyond ~45° — mitigated by relaxed parameters during registration
- Only one driver profile supported in Phase 1
- LED control is software-only by default (`RELAY_LED_HARDWARE = False`)
- Re-register if the lighting environment changes substantially from when the model was trained

---

## 📄 License

This project is for educational and prototype purposes.
