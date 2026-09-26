# Release notes — 0.2.1

## Changed

- Reworked the desktop UI into three pages: `控制台`, `手势指南`, and `设置`.
- Reduced the console page to camera preview, camera switch, current feedback,
  and a summary of the selected program.
- Moved program selection, background-camera authorization, mouse control,
  preview-only mode, auto-off, and camera index to the settings page.
- Added `设置 → 外观` with `浅色` and `深色` themes. The selected theme is
  remembered, applies without a restart, and does not change camera state.
- Kept camera capture off on every launch and background-camera authorization
  off by default. Mouse control starts off for first-time or unconfigured
  users and retains a saved enabled choice on later launches.
- Preserved existing user settings when upgrading from earlier versions.
- Updated the Windows build and installer outputs to version 0.2.1.

## Unchanged

- Camera lifecycle, gesture recognition, one-hand control, hotkeys, tray
  behavior, and gesture-to-action semantics remain unchanged.
- `Ctrl+Alt+G` still toggles the camera and `Ctrl+Alt+H` still shows the panel.
- The window close button still stops the camera before hiding the app in the
  notification area.
