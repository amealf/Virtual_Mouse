"""Windows hotkeys and notification-area menu; callbacks never touch Tk."""
import ctypes
from ctypes import wintypes
import queue
import threading

from PIL import Image, ImageDraw
import pystray


class SingleInstance:
    def __init__(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, False, 'Local\\MediaPipeGestureControllerDesktop')
        self.already_running = ctypes.get_last_error() == 183

    def close(self):
        if self.handle:
            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class HotkeyListener:
    def __init__(self, commands: queue.Queue):
        self.commands = commands
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        registered = []
        try:
            for key_id, key, command in ((1, 'G', 'toggle'), (2, 'H', 'show')):
                if user.RegisterHotKey(None, key_id, 0x4003, ord(key)):
                    registered.append(key_id)
                else:
                    self.commands.put(('error', f'Ctrl+Alt+{key} 已被占用，可使用界面按钮。'))
            msg = wintypes.MSG()
            while not self.stop_event.wait(0.02):
                while user.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 1):
                    if msg.wParam in registered:
                        self.commands.put(('toggle' if msg.wParam == 1 else 'show', ''))
        finally:
            for key_id in registered:
                user.UnregisterHotKey(None, key_id)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=1)


def tray_image(active=False):
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = '#087969' if active else '#526273'
    draw.rounded_rectangle((4, 12, 60, 54), radius=10, fill=color)
    draw.rectangle((18, 6, 38, 16), fill=color)
    draw.ellipse((20, 23, 44, 47), outline='white', width=5)
    return image


class TrayController:
    def __init__(self, commands):
        self.commands = commands
        self.state = 'off'
        self.icon = pystray.Icon('GestureController', tray_image(), '手势控制器 · 相机已关闭', menu=pystray.Menu(
            pystray.MenuItem('显示窗口  Ctrl+Alt+H', lambda *_: commands.put(('show', '')), default=True),
            pystray.MenuItem('切换相机  Ctrl+Alt+G', lambda *_: commands.put(('toggle', ''))),
            pystray.MenuItem('关闭相机', lambda *_: commands.put(('off', ''))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', lambda *_: commands.put(('quit', ''))),
        ))
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            self.icon.run()
        except Exception as exc:
            self.commands.put(('tray_error', f'托盘未能启动：{exc}'))

    def start(self):
        self.thread.start()

    def update(self, state):
        if state != self.state:
            self.state = state
            self.icon.icon = tray_image(state in ('on', 'starting', 'stopping'))
            label = {'off': '相机已关闭', 'starting': '正在打开相机', 'on': '相机使用中',
                     'stopping': '正在释放相机', 'error': '相机异常'}
            self.icon.title = '手势控制器 · ' + label.get(state, state)

    def close(self):
        self.icon.stop()
