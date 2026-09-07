# MediaPipe Gesture Controller

A local Windows gesture controller based on the upstream Virtual_Mouse project.

## Controls

| Gesture | Action |
| --- | --- |
| Index finger only | Move the mouse pointer |
| Hold thumb and index finger together briefly | Left click |
| Hold thumb and middle finger together for 0.4 seconds | Right click |
| Raise index and middle fingers, then move the hand vertically | Scroll |
| Perform a finger snap with thumb and middle finger | Launch Codex |
| Move an open palm quickly left or right | Exit this controller |
| Press `Esc` or `Q`, or move the pointer to the top-left corner | Emergency stop |

Finger snapping uses both the visible finger motion and a short microphone transient. This prevents ordinary hand motion or a random sound from launching Codex by itself.

## Install

Python 3.12 is recommended.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

Double-click `run_controller.cmd` to start with a camera preview. Command-line arguments can also be passed to it.

The equivalent PowerShell command is:

```powershell
.\.venv\Scripts\python.exe main.py
```

Run in the background after calibration:

```powershell
.\.venv\Scripts\python.exe main.py --headless

run_controller.cmd --headless
```

Use another camera when needed:

```powershell
.\.venv\Scripts\python.exe main.py --camera 1
```

## Files

- `main.py`: camera loop and action dispatch
- `hand_tracker.py`: MediaPipe hand landmark tracking
- `gesture_engine.py`: temporal gesture state machine
- `audio_snap.py`: microphone transient detector for snap confirmation
- `system_actions.py`: mouse control and Codex launching
- `utils.py`: hand geometry helpers

The original upstream entry point and README are retained in `reference_original_main.py` and `reference_original_README.md`.
