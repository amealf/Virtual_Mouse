"""Desktop control panel. Camera capture only starts after an explicit action."""
import argparse
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog

import cv2
from PIL import Image, ImageTk

from camera_session import CameraSession
from native_services import SingleInstance, HotkeyListener, TrayController, tray_image

VERSION = '0.2.0'
PROJECT_DIR = Path(__file__).resolve().parent
BG = '#f3f5f7'
SURFACE = '#ffffff'
LINE = '#d9e2e5'
SOFT = '#eaf1f0'
INK = '#172532'
MUTED = '#526273'
ACCENT = '#087969'
STATUS = {'off': '相机已关闭', 'starting': '正在打开相机…', 'on': '相机使用中',
          'stopping': '正在释放相机…', 'error': '相机异常，请查看提示'}
GESTURES = {'Tracking': '已找到手，请做手势', 'Waiting for hand': '等待手进入画面',
            'Move': '移动鼠标', 'Left click': '左键', 'Right click': '右键',
            'Scroll': '滚动', 'Snap detected': '识别到响指', 'Swipe exit': '识别到挥手'}


class DesktopApp:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.commands = queue.Queue()
        self.session = CameraSession(PROJECT_DIR / 'hand_landmarker.task')
        self.settings_path = Path(os.environ.get('LOCALAPPDATA', str(PROJECT_DIR))) / 'MediaPipeGestureController' / 'settings.json'
        settings = self._read_settings()
        self.camera_index = tk.IntVar(value=settings.get('camera_index', 0))
        self.preview_only = tk.BooleanVar(value=args.preview_only or settings.get('preview_only', False))
        self.auto_off = tk.BooleanVar(value=settings.get('auto_off', False))
        self.background_camera = tk.BooleanVar(value=settings.get('background_camera', False))
        self.mouse_enabled = tk.BooleanVar(value=settings.get('mouse_enabled', False))
        self.program_path = tk.StringVar(value=settings.get('program_path', ''))
        self.photo = None
        self.closing = False
        self.last_state = None
        self.last_event = ''
        self.last_event_time = 0.0
        self.tray_ok = True
        self.exit_watchdog = None
        self._build()
        self.hotkeys = HotkeyListener(self.commands)
        self.tray = TrayController(self.commands)
        self.hotkeys.start()
        self.tray.start()
        self.root.protocol('WM_DELETE_WINDOW', self.hide)
        self.root.bind('<Escape>', lambda _: self.turn_off())
        self.root.bind('<Unmap>', self.on_minimize)
        self.root.after(40, self.poll)
        if args.background:
            self.root.after(300, self.hide)
        if args.test_seconds:
            self.root.after(int(args.test_seconds * 1000), self.quit)

    def _read_settings(self):
        try:
            data = json.loads(self.settings_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                return {}
            camera = data.get('camera_index', 0)
            program = data.get('program_path', data.get('codex_path', ''))
            return {
                'camera_index': camera if type(camera) is int and 0 <= camera <= 9 else 0,
                'program_path': program if isinstance(program, str) else '',
                **{key: data.get(key) is True for key in ('preview_only', 'auto_off', 'background_camera', 'mouse_enabled')},
            }
        except (OSError, ValueError):
            return {}

    def save_settings(self):
        if self.args.test_seconds:
            return
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps({
                'camera_index': self.camera_index.get(), 'preview_only': self.preview_only.get(),
                'auto_off': self.auto_off.get(), 'program_path': self.program_path.get(),
                'background_camera': self.background_camera.get(),
                'mouse_enabled': self.mouse_enabled.get(),
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, tk.TclError) as exc:
            self.log(f'设置未能保存：{exc}')

    def label(self, parent, text, size=11, color=INK, **kwargs):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Microsoft YaHei UI', size), anchor='w', **kwargs)

    def scroll_page(self, notebook, title):
        page = tk.Frame(notebook, bg=SURFACE)
        notebook.add(page, text=title)
        canvas = tk.Canvas(page, bg=SURFACE, highlightthickness=0)
        bar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        content = tk.Frame(canvas, bg=SURFACE)
        item = canvas.create_window(0, 0, window=content, anchor='nw')

        def resize(_=None):
            canvas.itemconfigure(item, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox('all'))
            if content.winfo_reqheight() > canvas.winfo_height():
                bar.pack(side='right', fill='y')
            else:
                bar.pack_forget()
                canvas.yview_moveto(0)

        canvas.bind('<Configure>', resize)
        content.bind('<Configure>', resize)

        def wheel(event):
            widget = event.widget
            while widget is not None:
                if widget is page:
                    canvas.yview_scroll(round(-event.delta / 120), 'units')
                    break
                widget = getattr(widget, 'master', None)

        self.root.bind('<MouseWheel>', wheel, add='+')
        return content

    def _build(self):
        root = self.root
        root.title(f'手势控制器 · {VERSION}')
        self.app_icon = ImageTk.PhotoImage(tray_image(True))
        root.iconphoto(True, self.app_icon)
        root.configure(bg=BG)
        self.scale = max(1.0, root.winfo_fpixels('1i') / 96.0)
        p = lambda value: round(value * self.scale)
        width = min(p(1400), root.winfo_screenwidth() - p(80))
        height = min(p(920), root.winfo_screenheight() - p(100))
        root.geometry(f'{width}x{height}+40+40')
        root.minsize(min(width, p(960)), min(height, p(740)))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(p(16), p(10)),
                        background=SURFACE, foreground=INK, bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE)
        style.map('TButton', background=[('active', SOFT), ('disabled', BG)], foreground=[('disabled', '#7b898e')])
        style.configure('Accent.TButton', foreground='white', background=ACCENT,
                        font=('Microsoft YaHei UI', 12), borderwidth=0, padding=(p(16), p(14)))
        style.map('Accent.TButton', background=[('disabled', '#778993'), ('active', '#056356')],
                  foreground=[('disabled', 'white'), ('active', 'white')])
        style.configure('TCheckbutton', background=SURFACE, font=('Microsoft YaHei UI', 10),
                        padding=(0, p(6)), indicatorsize=p(15), indicatormargin=(0, 0, p(8), 0))
        style.map('TCheckbutton', background=[('active', SURFACE)], foreground=[('disabled', '#7b898e')])
        style.configure('TSpinbox', font=('Microsoft YaHei UI', 10), padding=p(5), bordercolor=LINE, arrowsize=p(14))
        style.configure('TEntry', padding=p(8), bordercolor=LINE, lightcolor=SURFACE, darkcolor=SURFACE)
        style.configure('TNotebook', background=SURFACE, borderwidth=0)
        style.configure('TNotebook.Tab', font=('Microsoft YaHei UI', 10), padding=(p(20), p(10)), background=BG)
        style.map('TNotebook.Tab', background=[('selected', SURFACE)], foreground=[('selected', ACCENT)],
                  padding=[('selected', (p(20), p(10)))])

        header = tk.Frame(root, bg=BG)
        header.pack(fill='x', padx=p(28), pady=(p(24), p(24)))
        heading = tk.Frame(header, bg=BG)
        heading.pack(side='left')
        self.label(heading, '手势控制器', 22).pack(anchor='w')
        self.label(heading, '本地识别，相机由你掌控。', 10, MUTED).pack(anchor='w', pady=(p(4), 0))
        ttk.Button(header, text='退出程序', command=self.quit).pack(side='right')
        ttk.Button(header, text='关闭相机并收起', command=self.hide).pack(side='right', padx=p(12))

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=True, padx=p(28))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        viewer = tk.Frame(body, bg=SURFACE)
        viewer.grid(row=0, column=0, sticky='nsew', padx=(0, p(20)))
        strip = tk.Frame(viewer, bg=SURFACE)
        strip.pack(fill='x', padx=p(24), pady=p(20))
        self.label(strip, '实时预览', 14).pack(side='left')
        self.state_label = self.label(strip, '●  相机已关闭', 10, MUTED)
        self.state_label.pack(side='right')
        self.canvas = tk.Canvas(viewer, bg=SOFT, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=p(16))
        self.canvas.bind('<Configure>', lambda _: self.render_empty() if self.last_state != 'on' else None)
        self.label(viewer, '识别反馈', 9, MUTED).pack(fill='x', padx=p(24), pady=(p(20), p(4)))
        self.feedback = self.label(viewer, '按 Ctrl+Alt+G 开始，使用后再按一次关闭。', 12)
        self.feedback.pack(fill='x', padx=p(24), pady=(0, p(20)))
        self.feedback.bind('<Configure>', lambda e: self.feedback.config(wraplength=e.width))

        sidebar = tk.Frame(body, bg=SURFACE, width=p(340))
        sidebar.grid(row=0, column=1, sticky='ns')
        sidebar.pack_propagate(False)
        power = tk.Frame(sidebar, bg=SURFACE)
        power.pack(fill='x', padx=p(20), pady=(p(20), p(16)))
        self.label(power, '相机控制', 14).pack(anchor='w', pady=(0, p(12)))
        self.toggle_button = ttk.Button(power, text='开启相机', style='Accent.TButton', command=self.toggle)
        self.toggle_button.pack(fill='x')
        self.label(power, 'Ctrl + Alt + G  随时开启 / 关闭', 10, MUTED).pack(anchor='w', pady=(p(10), 0))
        tabs = ttk.Notebook(sidebar)
        tabs.pack(fill='both', expand=True)
        side = self.scroll_page(tabs, '控制')
        guide = self.scroll_page(tabs, '手势速查')
        side.columnconfigure(0, weight=1)
        self.label(side, '使用方式', 11).grid(row=0, column=0, sticky='w', padx=p(20), pady=(p(20), p(4)))
        self.preview_check = ttk.Checkbutton(side, text='仅预览手势，不控制电脑', variable=self.preview_only)
        self.preview_check.grid(row=1, column=0, sticky='w', padx=p(20))
        self.auto_check = ttk.Checkbutton(side, text='响指或点击成功后关闭相机', variable=self.auto_off)
        self.auto_check.grid(row=2, column=0, sticky='w', padx=p(20))
        self.background_check = ttk.Checkbutton(side, text='允许后台使用相机', variable=self.background_camera,
                                               command=self.save_settings)
        self.background_check.grid(row=3, column=0, sticky='w', padx=p(20))
        self.mouse_check = ttk.Checkbutton(side, text='启用鼠标操作（实验性）', variable=self.mouse_enabled)
        self.mouse_check.grid(row=4, column=0, sticky='w', padx=p(20))
        options = tk.Frame(side, bg=SURFACE)
        options.grid(row=5, column=0, sticky='ew', padx=p(20), pady=p(16))
        self.label(options, '摄像头编号', 10).pack(side='left')
        self.camera_input = ttk.Spinbox(options, from_=0, to=9, width=4, textvariable=self.camera_index)
        self.camera_input.pack(side='right')
        tk.Frame(side, bg=LINE, height=1).grid(row=6, column=0, sticky='ew', padx=p(20), pady=(0, p(16)))
        self.label(side, '响指打开的程序', 11).grid(row=7, column=0, sticky='w', padx=p(20))
        self.path_entry = ttk.Entry(side, textvariable=self.program_path, font=('Microsoft YaHei UI', 9))
        self.path_entry.grid(row=8, column=0, sticky='ew', padx=p(20), pady=p(8))
        self.browse_button = ttk.Button(side, text='选择程序 .exe', command=self.choose_program)
        self.browse_button.grid(row=9, column=0, sticky='ew', padx=p(20))
        self.label(side, 'Ctrl + Alt + H  显示窗口\nEsc  关闭相机（窗口内）', 10, MUTED, justify='left').grid(row=10, column=0, sticky='w', padx=p(20), pady=p(20))

        for action, gesture in (('移动鼠标', '只伸出食指'), ('左键 / 右键', '拇指捏合食指 / 中指，其他指收起'), ('上下滚动', '食指、中指伸出，上下移动'), ('打开自选程序', '中指快速弹动，做出响指'), ('退出程序', '张开手掌，快速向左或右横扫')):
            row = tk.Frame(guide, bg=SURFACE)
            row.pack(fill='x', padx=p(20), pady=(p(16), 0))
            self.label(row, action, 11).pack(anchor='w')
            self.label(row, gesture, 10, MUTED, wraplength=p(280), justify='left').pack(anchor='w', pady=(p(4), 0))
        self.label(guide, '每次使用一只手。\n响指无需声音，挥手会退出程序。', 10, MUTED, justify='left').pack(anchor='w', padx=p(20), pady=p(20))

        footer = tk.Frame(root, bg=BG)
        footer.pack(fill='x', padx=p(28), pady=(p(16), p(20)))
        self.notice = self.label(footer, '准备就绪 · 不录音 · 不保存相机画面', 10, MUTED)
        self.notice.pack(fill='x')
        self.notice.bind('<Configure>', lambda e: self.notice.config(wraplength=e.width))

    def render_empty(self):
        self.canvas.delete('all')
        self.photo = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        s = self.scale
        self.canvas.create_rectangle(w/2-32*s, h/2-92*s, w/2+32*s, h/2-48*s, outline=MUTED, width=2*s)
        self.canvas.create_oval(w/2-12*s, h/2-82*s, w/2+12*s, h/2-58*s, outline=MUTED, width=2*s)
        self.canvas.create_text(w/2, h/2-8*s, text=STATUS.get(self.session.get_snapshot()['state'], '相机已关闭'), fill=INK, font=('Microsoft YaHei UI', 20))
        self.canvas.create_text(w/2, h/2+32*s, text='准备好时，按 Ctrl + Alt + G 打开相机', fill=MUTED, font=('Microsoft YaHei UI', 11), width=max(200,w-48*s))
        self.canvas.create_text(w/2, h/2+68*s, text='关闭后释放摄像头，不保留上一帧画面', fill=MUTED, font=('Microsoft YaHei UI', 10), width=max(200,w-48*s))

    def choose_program(self):
        path = filedialog.askopenfilename(title='选择响指要打开的程序', filetypes=[('Windows 程序', '*.exe')])
        if path:
            self.program_path.set(path)
            self.save_settings()
            self.log(f'响指将打开：{Path(path).name}')

    def toggle(self):
        if self.closing:
            return
        if self.session.is_running:
            self.turn_off()
            return
        if self.root.state() in ('withdrawn', 'iconic') and not self.background_camera.get():
            self.show()
            self.log('后台相机尚未授权。勾选「允许后台使用相机」后，可通过快捷键在后台开启。')
            return
        try:
            self.session.camera_index = self.camera_index.get()
            if not 0 <= self.session.camera_index <= 9:
                raise ValueError('camera index')
        except (tk.TclError, ValueError):
            self.log('摄像头编号需要是 0 到 9 的整数。')
            return
        self.session.program_path = Path(self.program_path.get()) if self.program_path.get() else None
        self.last_event = ''
        self.last_event_time = 0.0
        self.save_settings()
        self.session.start(preview_only=self.preview_only.get(), auto_off_after_action=self.auto_off.get(),
                           mouse_enabled=self.mouse_enabled.get())

    def turn_off(self):
        self.session.stop()
        self.photo = None
        self.last_state = None
        self.render_empty()

    def hide(self):
        self.turn_off()
        if self.tray_ok:
            self.root.withdraw()
        else:
            self.log('托盘不可用，相机已关闭。窗口保持可见。')

    def on_minimize(self, event):
        if event.widget is self.root and self.root.state() == 'iconic' and not self.background_camera.get():
            self.turn_off()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def log(self, message):
        message = {'Camera started': '相机已打开，等待手进入画面。',
                   'Snap detected': '识别到响指',
                   'Camera frame unavailable.': '无法读取相机画面，请检查设备连接后重试。',
                   'PyAutoGUI fail-safe activated. Camera stopped.': '已触发鼠标安全停止，相机正在关闭。',
                   'Horizontal swipe detected': '识别到横向挥手，正在退出。'}.get(message, message)
        if str(message).startswith('Could not open camera'):
            message = '无法打开摄像头。请检查设备编号、系统相机权限，以及设备是否被其他程序占用。'
        self.notice.config(text=str(message).replace('\n', ' ')[:150])

    def poll(self):
        while not self.commands.empty():
            command, text = self.commands.get_nowait()
            if command == 'toggle': self.toggle()
            elif command == 'off': self.turn_off()
            elif command == 'show': self.show()
            elif command == 'quit': self.quit()
            elif command == 'tray_error':
                self.tray_ok = False
                self.show()
                self.log(text)
            else: self.log(text)
        while not self.session.events.empty():
            event = self.session.events.get_nowait()
            message = event.get('message', '')
            self.log(message)
            if event.get('kind') == 'exit' and self.session.event_is_current(event): self.quit()
            if event.get('kind') == 'gesture' and self.session.event_is_current(event):
                self.last_event, self.last_event_time = message, time.monotonic()
        snap = self.session.get_snapshot()
        state = snap['state']
        if state != self.last_state:
            self.last_state = state
            self.state_label.config(text='●  ' + STATUS.get(state, state),
                                    fg=ACCENT if state == 'on' else '#a24925' if state == 'error' else MUTED)
            button_text = {'off': '开启相机', 'on': '关闭相机', 'starting': '取消开启', 'stopping': '正在关闭…', 'error': '重试打开相机'}
            self.toggle_button.config(text=button_text.get(state, '开启相机'), state='disabled' if state == 'stopping' else 'normal')
            for control in (self.camera_input,self.preview_check,self.auto_check,self.background_check,self.mouse_check,self.browse_button,self.path_entry):
                control.config(state='disabled' if state in ('starting','on','stopping') else 'normal')
            self.tray.update(state)
            if state != 'on': self.render_empty()
        image = snap.get('image')
        if state == 'on' and image is not None and self.root.state() != 'withdrawn':
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            picture = Image.fromarray(rgb)
            ratio = min(max(1, self.canvas.winfo_width()) / picture.width,
                        max(1, self.canvas.winfo_height()) / picture.height)
            picture = picture.resize((max(1, round(picture.width * ratio)),
                                      max(1, round(picture.height * ratio))), Image.Resampling.BILINEAR)
            self.photo = ImageTk.PhotoImage(picture)
            self.canvas.delete('all')
            self.canvas.create_image(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,image=self.photo)
        text = snap.get('status') or 'Waiting for hand'
        if state == 'on' and time.monotonic() - self.last_event_time < 1.2:
            text = self.last_event
        feedback = GESTURES.get(text, text)
        if state == 'on':
            if self.preview_only.get():
                feedback += '（仅预览）'
            elif not self.mouse_enabled.get() and text in ('Move', 'Left click', 'Right click', 'Scroll'):
                feedback += '（鼠标操作未启用）'
        self.feedback.config(text=feedback if state == 'on' else '按 Ctrl+Alt+G 开始，使用后再按一次关闭。')
        if snap.get('error'): self.log(snap['error'])
        if self.closing and not self.session.is_running:
            self.tray.close()
            self.hotkeys.close()
            if self.exit_watchdog:
                self.exit_watchdog.cancel()
            self.root.destroy()
            return
        self.root.after(40, self.poll)

    def quit(self):
        if self.closing: return
        self.closing = True
        # A stalled camera driver must not keep the application alive after
        # the user explicitly exits. Windows then closes its device handles.
        self.exit_watchdog = threading.Timer(8.0, lambda: os._exit(0))
        self.exit_watchdog.daemon = True
        self.exit_watchdog.start()
        self.save_settings()
        self.turn_off()
        self.log('正在关闭设备并退出…')

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--preview-only', action='store_true')
    parser.add_argument('--test-seconds', type=float, default=0)
    parser.add_argument('--check-model', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_model:
        import numpy as np
        from hand_tracker import HandTracker
        tracker = HandTracker(PROJECT_DIR / 'hand_landmarker.task')
        try:
            tracker.process(np.zeros((240, 320, 3), dtype=np.uint8), 0, draw=False)
        finally:
            tracker.close()
        return
    guard = SingleInstance()
    if guard.already_running:
        ctypes_message = __import__('ctypes').windll.user32.MessageBoxW
        ctypes_message(None, '程序已在运行。按 Ctrl+Alt+H 显示窗口。', '手势控制器', 0)
        guard.close()
        return
    try:
        root = tk.Tk()
        DesktopApp(root,args)
        root.mainloop()
    finally:
        guard.close()


if __name__ == '__main__':
    run()
