from pathlib import Path
import os
import shutil
import subprocess

import numpy as np
import pyautogui


class DesktopController:
    def __init__(self, smoothing: float = 5.0, frame_margin: float = 0.15) -> None:
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0
        self.screen_width, self.screen_height = pyautogui.size()
        self.smoothing = smoothing
        self.frame_margin = frame_margin
        current_x, current_y = pyautogui.position()
        self._cursor_x = float(current_x)
        self._cursor_y = float(current_y)

    def move_cursor(self, point: tuple[float, float]) -> None:
        x, y = point
        target_x = float(np.interp(x, (self.frame_margin, 1.0 - self.frame_margin), (0, self.screen_width - 1)))
        target_y = float(np.interp(y, (self.frame_margin, 1.0 - self.frame_margin), (0, self.screen_height - 1)))
        self._cursor_x += (target_x - self._cursor_x) / self.smoothing
        self._cursor_y += (target_y - self._cursor_y) / self.smoothing
        pyautogui.moveTo(self._cursor_x, self._cursor_y, duration=0)

    @staticmethod
    def left_click() -> None:
        pyautogui.click()

    @staticmethod
    def right_click() -> None:
        pyautogui.rightClick()

    @staticmethod
    def scroll(amount: int) -> None:
        pyautogui.scroll(amount)


def find_codex_executable() -> Path | None:
    command = shutil.which("codex")
    if command:
        return Path(command)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe"
        if candidate.is_file():
            return candidate
    return None


def launch_codex() -> tuple[bool, str]:
    executable = find_codex_executable()
    if executable is None:
        return False, "Codex executable was not found."
    try:
        subprocess.Popen([str(executable)], close_fds=True)
        return True, f"Codex launched from {executable}"
    except OSError as exc:
        return False, f"Could not launch Codex: {exc}"
