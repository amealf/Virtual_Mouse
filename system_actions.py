from pathlib import Path
import os
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
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
        for candidate in (
            root / "OpenAI" / "Codex" / "bin" / "codex.exe",
            root / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
        ):
            if candidate.is_file():
                return candidate
    return None


def launch_program(executable: Path | None) -> tuple[bool, str]:
    if executable is None:
        return False, "请先在控制界面选择要打开的程序。"
    if executable.suffix.lower() != '.exe' or not executable.is_file():
        return False, "程序路径无效，请重新选择 .exe 文件。"
    try:
        subprocess.Popen([str(executable)], cwd=str(executable.parent), close_fds=True)
        return True, f"已打开 {executable.name}"
    except OSError as exc:
        return False, f"程序未能打开：{exc}"


def launch_codex(executable: Path | None = None) -> tuple[bool, str]:
    """Legacy command-line runner; the desktop panel uses launch_program."""
    return launch_program(executable or find_codex_executable())
