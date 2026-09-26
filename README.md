# MediaPipe Gesture Controller

Version 0.2.0 is a local Windows desktop app for hand-gesture control. The
desktop app starts with the camera off. You can keep the app in the
notification area and turn camera capture on only when you need it.

## Install

For the packaged build, run `GestureController-Setup-0.2.0-x64.exe` and open
`MediaPipe Gesture Controller` from the desktop or Start menu.

To run from source, create the project environment and install the pinned
dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Python 3.12 is recommended.

## Run the desktop app

Use the project launcher:

```powershell
.\run_controller.cmd
```

The equivalent command is:

```powershell
.\.venv\Scripts\python.exe desktop_app.py
```

The app opens its control panel without opening the camera. The panel is in
Chinese, and the gesture recognition and system status messages are shown in
the interface.

Global hotkeys work while the window is hidden or in the background. To open
the camera while the panel is hidden/minimized, first enable the unchecked
`允许后台使用相机` option yourself. Without that consent, the hotkey shows the
panel and leaves camera capture off. Camera-off always works without consent.

| Hotkey | Action |
| --- | --- |
| `Ctrl+Alt+G` | Toggle camera capture |
| `Ctrl+Alt+H` | Show the control panel |
| `Esc` in the panel | Close the camera |

Clicking the window close button (`X`) stops the camera and hides the panel in
the notification area. The tray menu can show the panel, toggle or close the
camera, and exit the application. Exiting the application releases the
camera before the process closes.

The launcher also accepts these diagnostic options:

```powershell
.\run_controller.cmd --background
.\run_controller.cmd --preview-only
.\run_controller.cmd --test-seconds 10
```

`--background` starts with the panel hidden in the tray. `--preview-only`
tracks gestures without moving the pointer, clicking, scrolling, launching
Codex, or exiting on a swipe. `--test-seconds` closes the app after the given
time.

`main.py` is retained as a legacy diagnostic runner. It opens the camera as
soon as it starts and is not the normal desktop entry point. Its `--headless`
mode is also legacy diagnostic behavior; use `desktop_app.py` or
`run_controller.cmd` for ordinary use.

## Gestures

The current controller uses one control hand:

Mouse control is experimental and **off by default**. Enable
`启用鼠标操作（实验性）` to allow pointer, click, and scroll actions. Snap-to-launch
and swipe-to-exit work without mouse control. `仅预览手势` disables all actions.

| Gesture | Action |
| --- | --- |
| Index finger only | Move the mouse pointer |
| Brief thumb-index pinch, other fingers folded | Left click |
| Thumb-middle pinch held for about 0.4 seconds, other fingers folded | Right click |
| Index and middle fingers raised, then move vertically | Scroll |
| Rapid inward middle-finger movement relative to the palm | Launch your selected `.exe` program |
| Open-palm horizontal swipe | Request application exit |

The snap detector uses visual finger motion. It does not require a sound, and
the normal desktop app does not open the microphone. Two-hand control is not
implemented.

The optional `auto-off` setting closes the camera after a successful program
launch or click. Pointer movement and continuous scrolling do not trigger
auto-off. Preview-only mode disables every operating-system action, including
the swipe exit request.

## Privacy and settings

Camera capture starts only after the start button, `Ctrl+Alt+G`, or the tray
toggle is used. Turning the camera off immediately clears the retained preview
frame and asks the worker to release the camera. The app does not record video
or use a microphone during normal operation.

The desktop app stores its settings at:

```text
%LOCALAPPDATA%\MediaPipeGestureController\settings.json
```

Saved settings include the camera index, preview-only mode, auto-off mode,
background-camera consent, and the selected executable path. Use the
`选择程序 .exe` button to choose any local Windows program. No target is
chosen automatically. Background-camera consent does not enable capture on
startup: the camera always starts off.

Minimizing without background-camera consent stops capture. The `X` button
and `关闭相机并收起` always stop capture before hiding the panel. After granting
consent, use `Ctrl+Alt+G` while the panel is hidden to open the camera without
showing a preview window. The tray icon changes to show camera activity.

## Recorded-video tuning

Two supplied clips were replayed locally through MediaPipe. The first clip
produced 5 snap events (baseline: 3); the second produced 4 swipe events
(baseline: 0) and no snap events (baseline: 1). These are event counts from
tuning clips, not a held-out accuracy score. The first clip still produced
unlabeled click events, which is why mouse actions require separate opt-in.
Private recordings and extracted landmarks are not included in the release.

`tools/replay_video.py` can replay local video files without opening a camera
or executing any desktop actions. It writes event timestamps and landmarks
to the chosen output directory.

## Build the Windows installer

The build script creates the PyInstaller bundle and invokes Inno Setup:

```powershell
.\build_windows.ps1 -InnoCompiler "C:\Path\To\ISCC.exe"
```

The bundled application is written to `dist-v0.2.0`, and the installer is
written to `dist` as `GestureController-Setup-0.2.0-x64.exe`.

## Project files

- `desktop_app.py`: Tk desktop panel, tray integration, and UI polling
- `camera_session.py`: threaded camera lifecycle and gesture dispatch
- `native_services.py`: global hotkeys, single-instance guard, and tray menu
- `hand_tracker.py`: MediaPipe hand landmark tracking
- `gesture_engine.py`: temporal gesture recognition
- `system_actions.py`: mouse actions and selected-program launching
- `run_controller.cmd`: normal source launcher
- `main.py`: legacy camera-first diagnostic runner

The upstream entry point and README are retained in
`reference_original_main.py` and `reference_original_README.md`.
