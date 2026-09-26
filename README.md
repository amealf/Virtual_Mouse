# MediaPipe Gesture Controller

Version 0.2.1 is a local Windows desktop app for hand-gesture control. This
release reorganizes the interface into three pages while keeping the camera,
gesture, and background behavior unchanged.

## Install

For the packaged build, run `GestureController-Setup-0.2.1-x64.exe` and open
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

The app opens with camera capture disabled. For first-time or unconfigured
users, mouse control also starts disabled; after you enable and save it, that
choice is retained on later launches. The Chinese desktop window has three pages:

- `控制台`: camera preview, camera switch, current feedback, and a short
  summary of the selected program.
- `手势指南`: the available gestures and their actions.
- `设置`: selected `.exe` program, background-camera authorization, mouse
  control, preview-only mode, auto-off, camera index, and appearance theme.

Global hotkeys work while the window is hidden or in the background. To open
the camera while the panel is hidden or minimized, enable `允许后台快捷键开启相机`
in `设置` first. The consent option is off by default; without it, the hotkey
shows the panel and leaves camera capture off. Camera-off always works without
consent.

| Hotkey | Action |
| --- | --- |
| `Ctrl+Alt+G` | Toggle camera capture |
| `Ctrl+Alt+H` | Show the control panel |
| `Esc` in the panel | Close the camera |

Clicking `关闭相机并收起` (`X`) stops the camera and hides the panel in the
notification area. The tray menu can show the panel, toggle or close the
camera, and exit the application. Exiting the application releases the camera
before the process closes.

The launcher also accepts these diagnostic options:

```powershell
.\run_controller.cmd --background
.\run_controller.cmd --preview-only
.\run_controller.cmd --test-seconds 10
```

`--background` starts with the panel hidden in the tray. `--preview-only`
tracks gestures without moving the pointer, clicking, scrolling, launching a
program, or exiting on a swipe. `--test-seconds` closes the app after the given
time.

`main.py` is retained as a legacy diagnostic runner. It opens the camera as
soon as it starts and is not the normal desktop entry point. Its `--headless`
mode is also legacy diagnostic behavior; use `desktop_app.py` or
`run_controller.cmd` for ordinary use.

## Gestures

The current controller uses one control hand. Mouse control is experimental.
For first-time or unconfigured users it starts off; enable and save
`启用鼠标操作（实验性）` in `设置` to allow pointer,
click, and scroll actions. Snap-to-launch and swipe-to-exit remain separate
gesture actions. `仅预览手势` disables all operating-system actions.

| Gesture | Action |
| --- | --- |
| Index finger only | Move the mouse pointer |
| Brief thumb-index pinch, other fingers folded | Left click |
| Thumb-middle pinch held for about 0.4 seconds, other fingers folded | Right click |
| Index and middle fingers raised, then move vertically | Scroll |
| Rapid inward middle-finger movement relative to the palm | Launch the selected `.exe` program |
| Open-palm horizontal swipe | Request application exit |

The snap detector uses visual finger motion. It does not require a sound, and
the normal desktop app does not open the microphone. Two-hand control is not
implemented.

The optional `auto-off` setting closes the camera after a successful program
launch or click. Pointer movement and continuous scrolling do not trigger
auto-off. Preview-only mode disables every operating-system action, including
the swipe exit request.

## Privacy and settings

Camera capture starts off on every launch and only starts after the start
button, `Ctrl+Alt+G`, or the tray toggle is used. Mouse control starts off for
first-time or unconfigured users and retains a saved enabled choice on later
launches. Background-camera authorization is off by default. Turning the camera off
clears the retained preview frame and asks the worker to release the camera.
The app does not record video or use a microphone during normal operation.

The desktop app stores its settings at:

```text
%LOCALAPPDATA%\MediaPipeGestureController\settings.json
```

Existing user settings are retained when upgrading. The settings page stores
the selected camera index, preview-only mode, auto-off mode, background-camera
authorization, mouse-control switch, selected executable path, and appearance
theme. Choose `浅色` or `深色` under `设置 → 外观`. The choice is remembered
for the next launch. Switching themes takes effect without restarting the app
and does not change the camera state. No program is selected automatically; use
`选择程序 .exe` to choose a local Windows program for the snap gesture.

Minimizing without background-camera authorization stops capture. The
`关闭相机并收起` (`X`) button always stops capture before hiding the panel. After
granting authorization, `Ctrl+Alt+G` can open the camera while the panel is
hidden, without showing a preview window.

## Build the Windows installer

The build script creates the PyInstaller bundle and invokes Inno Setup:

```powershell
.\build_windows.ps1 -InnoCompiler "C:\Path\To\ISCC.exe"
```

The bundled application is written to `dist-v0.2.1`, and the installer is
written to `dist` as `GestureController-Setup-0.2.1-x64.exe`.

## Project files

- `desktop_app.py`: Tk desktop panel, three-page UI, tray integration, and UI polling
- `camera_session.py`: threaded camera lifecycle and gesture dispatch
- `native_services.py`: global hotkeys, single-instance guard, and tray menu
- `hand_tracker.py`: MediaPipe hand landmark tracking
- `gesture_engine.py`: temporal gesture recognition
- `system_actions.py`: mouse actions and selected-program launching
- `run_controller.cmd`: normal source launcher
- `main.py`: legacy camera-first diagnostic runner

The upstream entry point and README are retained in
`reference_original_main.py` and `reference_original_README.md`.
