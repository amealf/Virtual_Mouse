# Release notes — 0.2.0

## Added

- Added a Chinese Tk desktop control panel that starts with camera capture off.
- Added global `Ctrl+Alt+G` camera toggle and `Ctrl+Alt+H` panel show hotkeys.
- Added a notification-area tray menu for showing the panel, toggling or
  closing the camera, and exiting the application.
- Added a threaded camera session that owns `VideoCapture` and MediaPipe
  cleanup, clears the retained preview frame when capture stops, and reports
  camera errors to the UI.
- Added user-selected `.exe` launch targets and settings persistence under
  `%LOCALAPPDATA%\MediaPipeGestureController\settings.json`.
- Added optional camera auto-off after a successful snap launch or click.
- Added explicit, default-off consent for opening the camera while the panel
  is hidden or minimized. Startup always leaves camera capture off.
- Refined the desktop layout, high-DPI spacing, always-visible camera switch,
  and scrollable control/gesture tabs for smaller windows.
- Added preview-only mode for gesture observation without desktop actions.
- Added a separate experimental mouse-control switch, off by default. Snap
  launch and swipe exit remain available without mouse control.

## Changed

- Changed `run_controller.cmd` to start `desktop_app.py`, the normal desktop
  entry point.
- Closing the panel with its window close button (`X`) now stops the camera and
  hides the app in the tray. Exiting the app waits for camera cleanup.
- Snap launch uses visual middle-finger motion; microphone input is not needed
  and is not opened by the desktop app.
- Camera capture uses one control hand. Two-hand control is not included in
  this release.
- `main.py` remains available for camera-first diagnostics. It is no longer
  the recommended launcher, and its `--headless` option is legacy diagnostic
  behavior.

## Gesture behavior

The desktop app retains the existing gesture actions: index-finger pointer
movement, thumb-index left click, thumb-middle right click, two-finger vertical
scroll, visual snap to launch a selected program, and open-palm horizontal swipe to request
application exit. Preview-only mode suppresses all system actions, including
the swipe exit request.

Two local tuning clips produced 5 snap events in the first clip and 4 swipe
events in the second; the second clip's prior snap false positive was removed.
These counts are calibration results, not independently measured accuracy.
Click ambiguity remains in the mixed-action clip; mouse control requires
explicit opt-in. No private video, preview image, or landmark data is shipped.
