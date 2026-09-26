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

VERSION = '0.2.1'
PROJECT_DIR = Path(__file__).resolve().parent
BG = '#f3f5f7'
SURFACE = '#ffffff'
LINE = '#d9e2e5'
SOFT = '#eaf1f0'
INK = '#172532'
MUTED = '#526273'
ACCENT = '#087969'
THEMES = {
    'light': {
        'bg': '#f3f5f7', 'sidebar': '#edf3f3', 'surface': '#ffffff',
        'canvas': '#eaf1f0', 'input': '#ffffff', 'line': '#d9e2e5',
        'soft': '#e2efed', 'ink': '#172532', 'muted': '#526273',
        'accent': '#087969', 'accent_active': '#056356',
        'on_accent': '#ffffff', 'danger': '#a24925', 'disabled': '#7b898e',
    },
    'dark': {
        'bg': '#131a1d', 'sidebar': '#182326', 'surface': '#1e292d',
        'canvas': '#1a2529', 'input': '#202f33', 'line': '#344348',
        'soft': '#263b3d', 'ink': '#e6eeee', 'muted': '#a7b7ba',
        'accent': '#41b9a4', 'accent_active': '#63cbb8',
        'on_accent': '#10201e', 'danger': '#efae99', 'disabled': '#708186',
    },
}
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
        self.theme_var = tk.StringVar(value=settings.get('theme', 'light'))
        self.theme_name = self.theme_var.get() if self.theme_var.get() in THEMES else 'light'
        self.palette = dict(THEMES[self.theme_name])
        self._theme_widgets = {}
        self._setting_traces = []
        self.photo = None
        self.closing = False
        self.last_state = None
        self.last_event = ''
        self.last_event_time = 0.0
        self.tray_ok = True
        self.exit_watchdog = None
        self._build()
        for setting in (self.camera_index, self.preview_only, self.auto_off,
                        self.background_camera, self.mouse_enabled, self.program_path,
                        self.theme_var):
            self._setting_traces.append(setting.trace_add('write', self._setting_changed))
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
            saved_theme = data.get('theme')
            return {
                'camera_index': camera if type(camera) is int and 0 <= camera <= 9 else 0,
                'program_path': program if isinstance(program, str) else '',
                'theme': saved_theme if isinstance(saved_theme, str) and saved_theme in THEMES else 'light',
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
                'theme': self.theme_name,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, tk.TclError) as exc:
            self.log(f'设置未能保存：{exc}')

    def _theme_widget(self, widget, bg_role=None, fg_role=None):
        """Register a Tk widget so a theme change updates it in place."""
        self._theme_widgets[widget] = (bg_role, fg_role)
        self._apply_widget_theme(widget, bg_role, fg_role)
        return widget

    def _apply_widget_theme(self, widget, bg_role=None, fg_role=None):
        try:
            options = {}
            if bg_role:
                options['bg'] = self.palette[bg_role]
            if fg_role:
                options['fg'] = self.palette[fg_role]
            if isinstance(widget, tk.Button):
                options.update(activebackground=self.palette['soft'],
                               activeforeground=self.palette['ink'],
                               disabledforeground=self.palette['disabled'])
            if options:
                widget.configure(**options)
        except (tk.TclError, RuntimeError):
            pass

    def label(self, parent, text, size=11, color=None, bg_role='surface', fg_role=None, **kwargs):
        if fg_role is None:
            if color in (MUTED, self.palette.get('muted')):
                fg_role = 'muted'
            elif color in (self.palette.get('accent'), ACCENT):
                fg_role = 'accent'
            else:
                fg_role = 'ink'
        widget = tk.Label(parent, text=text, bg=self.palette[bg_role], fg=self.palette[fg_role],
                          font=('Microsoft YaHei UI', size), anchor='w', **kwargs)
        return self._theme_widget(widget, bg_role, fg_role)

    def wrap_label(self, widget):
        widget.bind('<Configure>', lambda e: widget.configure(wraplength=max(1, e.width - self._u(4))))
        return widget

    def _is_descendant(self, widget, ancestor):
        while widget is not None:
            if widget is ancestor:
                return True
            widget = getattr(widget, 'master', None)
        return False

    def scroll_page(self, page):
        """Create a scrollable content area without a notebook or duplicate page."""
        canvas = tk.Canvas(page, bg=self.palette['bg'], highlightthickness=0)
        bar = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        content = tk.Frame(canvas, bg=self.palette['bg'])
        self._theme_widget(canvas, 'bg')
        self._theme_widget(content, 'bg')
        item = canvas.create_window(0, 0, window=content, anchor='nw')

        def resize(_=None):
            canvas.itemconfigure(item, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox('all'))

        canvas.bind('<Configure>', resize)
        content.bind('<Configure>', resize)

        def wheel(event):
            if self._is_descendant(event.widget, page):
                delta = round(-event.delta / 120) or (-1 if event.delta > 0 else 1)
                canvas.yview_scroll(delta, 'units')

        self.root.bind_all('<MouseWheel>', wheel, add='+')
        return content

    def _configure_styles(self):
        """Apply the current semantic palette to ttk widgets."""
        c = self.palette
        p = self._u
        style = self.style
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(p(14), p(9)),
                        background=c['surface'], foreground=c['ink'], bordercolor=c['line'],
                        lightcolor=c['surface'], darkcolor=c['surface'], focusthickness=0)
        style.map('TButton', background=[('active', c['soft']), ('disabled', c['bg'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('Accent.TButton', foreground=c['on_accent'], background=c['accent'],
                        font=('Microsoft YaHei UI', 12), borderwidth=0, padding=(p(16), p(12)),
                        focusthickness=0)
        style.map('Accent.TButton', background=[('disabled', c['disabled']), ('active', c['accent_active'])],
                  foreground=[('disabled', c['on_accent']), ('active', c['on_accent'])])
        style.configure('TCheckbutton', background=c['surface'], foreground=c['ink'],
                        font=('Microsoft YaHei UI', 10), padding=(0, p(6)), indicatorsize=p(15),
                        indicatormargin=(0, 0, p(8), 0))
        style.map('TCheckbutton', background=[('active', c['surface']), ('disabled', c['surface'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('Settings.TCheckbutton', background=c['bg'], foreground=c['ink'],
                        font=('Microsoft YaHei UI', 10), padding=(0, p(6)), indicatorsize=p(15),
                        indicatormargin=(0, 0, p(8), 0))
        style.map('Settings.TCheckbutton', background=[('active', c['bg']), ('disabled', c['bg'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('Theme.TRadiobutton', background=c['bg'], foreground=c['ink'],
                        font=('Microsoft YaHei UI', 10), padding=(0, p(5)), indicatorsize=p(15))
        style.map('Theme.TRadiobutton', background=[('active', c['bg'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('TSpinbox', font=('Microsoft YaHei UI', 10), padding=p(5), bordercolor=c['line'],
                        fieldbackground=c['input'], foreground=c['ink'], arrowsize=p(14),
                        insertcolor=c['ink'])
        style.map('TSpinbox', fieldbackground=[('disabled', c['soft'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('TEntry', padding=p(8), bordercolor=c['line'], lightcolor=c['input'],
                        darkcolor=c['input'], fieldbackground=c['input'], foreground=c['ink'])
        style.map('TEntry', fieldbackground=[('disabled', c['soft'])],
                  foreground=[('disabled', c['disabled'])])
        style.configure('TScrollbar', background=c['line'], troughcolor=c['bg'], bordercolor=c['bg'],
                        arrowcolor=c['muted'], lightcolor=c['line'], darkcolor=c['line'])

    def _u(self, value):
        return round(value * self.scale)

    def _setting_changed(self, *_):
        if self.closing:
            return
        if self.theme_var.get() in THEMES and self.theme_var.get() != self.theme_name:
            self.apply_theme(self.theme_var.get(), save=False)
        if hasattr(self, 'program_summary'):
            self._update_program_summary()
        self.save_settings()

    def apply_theme(self, name=None, save=True):
        """Switch palette in place; CameraSession, tray and hotkeys are untouched."""
        name = name or self.theme_var.get()
        if name not in THEMES:
            name = 'light'
        self.theme_name = name
        self.palette = dict(THEMES[name])
        self._configure_styles()
        try:
            self.root.configure(bg=self.palette['bg'])
            for widget, (bg_role, fg_role) in tuple(self._theme_widgets.items()):
                if widget.winfo_exists():
                    self._apply_widget_theme(widget, bg_role, fg_role)
        except (tk.TclError, RuntimeError):
            pass
        self._update_nav_buttons()
        if hasattr(self, 'state_label'):
            state = self.last_state or 'off'
            state_color = self.palette['accent'] if state == 'on' else self.palette['danger'] if state == 'error' else self.palette['muted']
            state_text = '●  ' + STATUS.get(state, state)
            self.state_label.config(text=state_text, fg=state_color)
            if hasattr(self, 'nav_state_label'):
                self.nav_state_label.config(text=state_text, fg=state_color)
        if hasattr(self, 'program_summary'):
            self._update_program_summary()
        if hasattr(self, 'canvas') and self.last_state != 'on' and self.current_page == 'home':
            self.render_empty()
        if save:
            self.save_settings()

    def _new_frame(self, parent, role='surface', **kwargs):
        return self._theme_widget(tk.Frame(parent, bg=self.palette[role], **kwargs), role)

    def _new_separator(self, parent, role='line', **kwargs):
        return self._theme_widget(tk.Frame(parent, bg=self.palette[role], height=1, **kwargs), role)

    def _build(self):
        root = self.root
        root.title(f'手势控制器 · {VERSION}')
        self.app_icon = ImageTk.PhotoImage(tray_image(True))
        root.iconphoto(True, self.app_icon)
        self.scale = max(1.0, root.winfo_fpixels('1i') / 96.0)
        p = self._u
        root.configure(bg=self.palette['bg'])
        width = min(p(1280), root.winfo_screenwidth() - p(72))
        height = min(p(820), root.winfo_screenheight() - p(88))
        root.geometry(f'{width}x{height}+36+36')
        root.minsize(min(p(1000), width), min(p(720), height))
        self.style = ttk.Style(root)
        self.style.theme_use('clam')
        self._configure_styles()

        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, minsize=p(184), weight=0)
        root.grid_columnconfigure(1, weight=1)
        sidebar = self._new_frame(root, 'sidebar', width=p(184))
        sidebar.grid(row=0, column=0, sticky='nsew')
        sidebar.pack_propagate(False)
        main = self._new_frame(root, 'bg')
        main.grid(row=0, column=1, sticky='nsew')
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        brand = self._new_frame(sidebar, 'sidebar')
        brand.pack(fill='x', padx=p(20), pady=(p(28), p(34)))
        brand_line = self._new_frame(brand, 'sidebar')
        brand_line.pack(fill='x')
        self.label(brand_line, '◉', 18, fg_role='accent', bg_role='sidebar').pack(side='left', padx=(0, p(8)))
        self.label(brand_line, '手势控制器', 12, fg_role='ink', bg_role='sidebar').pack(side='left')
        self.label(brand, '本地运行 · 隐私可控', 9, fg_role='muted', bg_role='sidebar').pack(anchor='w', pady=(p(8), 0))

        self.nav_buttons = {}
        for key, text in (('home', '控制台'), ('guide', '手势指南'), ('settings', '设置')):
            button = tk.Button(sidebar, text=text, anchor='w', relief='flat', bd=0,
                               highlightthickness=0, font=('Microsoft YaHei UI', 10),
                               padx=p(18), pady=p(10), command=lambda page=key: self.show_page(page))
            button.pack(fill='x', padx=p(10), pady=p(2))
            self._theme_widget(button, 'sidebar', 'ink')
            self.nav_buttons[key] = button

        nav_bottom = self._new_frame(sidebar, 'sidebar')
        nav_bottom.pack(side='bottom', fill='x', padx=p(10), pady=(p(10), p(20)))
        self._new_separator(nav_bottom, 'line').pack(fill='x', pady=(0, p(12)))
        self.nav_state_label = self.label(nav_bottom, '●  相机已关闭', 9,
                                          fg_role='muted', bg_role='sidebar')
        self.nav_state_label.pack(anchor='w', padx=p(8), pady=(0, p(8)))
        tray_button = tk.Button(nav_bottom, text='关闭相机并收起', anchor='w', relief='flat', bd=0,
                                highlightthickness=0, font=('Microsoft YaHei UI', 9),
                                padx=p(8), pady=p(8), command=self.hide)
        tray_button.pack(fill='x')
        self._theme_widget(tray_button, 'sidebar', 'muted')
        quit_button = tk.Button(nav_bottom, text='退出程序', anchor='w', relief='flat', bd=0,
                                highlightthickness=0, font=('Microsoft YaHei UI', 9),
                                padx=p(8), pady=p(8), command=self.quit)
        quit_button.pack(fill='x')
        self._theme_widget(quit_button, 'sidebar', 'muted')

        self.page_container = self._new_frame(main, 'bg')
        self.page_container.grid(row=0, column=0, sticky='nsew')
        self.page_container.grid_rowconfigure(0, weight=1)
        self.page_container.grid_columnconfigure(0, weight=1)
        self.pages = {}

        home = self._new_frame(self.page_container, 'bg')
        home.grid(row=0, column=0, sticky='nsew', padx=p(32), pady=p(28))
        home.grid_rowconfigure(1, weight=1)
        home.grid_columnconfigure(0, weight=1)
        self.pages['home'] = home
        top = self._new_frame(home, 'bg')
        top.grid(row=0, column=0, sticky='ew', pady=(0, p(20)))
        self.label(top, '控制台', 22, bg_role='bg').pack(side='left')
        self.state_label = self.label(top, '●  相机已关闭', 10, fg_role='muted', bg_role='bg')
        self.state_label.pack(side='right', pady=p(8))

        preview_outer = self._new_frame(home, 'line')
        preview_outer.grid(row=1, column=0, sticky='nsew')
        preview = self._new_frame(preview_outer, 'surface')
        preview.pack(fill='both', expand=True, padx=1, pady=1)
        self.canvas = self._theme_widget(tk.Canvas(preview, bg=self.palette['canvas'], highlightthickness=0), 'canvas')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.render_empty() if self.last_state != 'on' else None)

        action = self._new_frame(home, 'bg')
        action.grid(row=2, column=0, sticky='ew', pady=(p(20), 0))
        action.grid_columnconfigure(1, weight=1)
        self.toggle_button = ttk.Button(action, text='开启相机', style='Accent.TButton', command=self.toggle)
        self.toggle_button.grid(row=0, column=0, sticky='w')
        self.wrap_label(self.label(action, 'Ctrl + Alt + G  开启 / 关闭相机', 10, fg_role='muted', bg_role='bg')).grid(
            row=0, column=1, sticky='ew', padx=p(16))
        self.feedback = self.label(action, '准备好时按 Ctrl + Alt + G 开始。', 11, bg_role='bg')
        self.feedback.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(p(14), 0))
        self.wrap_label(self.feedback)
        summary = self._new_frame(action, 'bg')
        summary.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(p(10), 0))
        ttk.Button(summary, text='进入设置', command=lambda: self.show_page('settings')).pack(side='right', padx=(p(16), 0))
        self.program_summary = self.label(summary, '', 10, fg_role='muted', bg_role='bg', width=1)
        self.program_summary.pack(side='left', fill='x', expand=True)
        self.program_summary.bind('<Configure>', lambda _: self._update_program_summary())

        settings = self._new_frame(self.page_container, 'bg')
        settings.grid(row=0, column=0, sticky='nsew')
        self.pages['settings'] = settings
        settings_content = self.scroll_page(settings)
        pad = p(32)
        title = self.label(settings_content, '设置', 22, bg_role='bg')
        title.pack(fill='x', padx=pad, pady=(p(28), p(6)))
        self.wrap_label(self.label(settings_content, '选项自动保存。相机运行时，设备和操作设置锁定；外观仍可切换。', 10,
                   fg_role='muted', bg_role='bg', justify='left')).pack(fill='x', padx=pad, pady=(0, p(22)))

        def section(title_text, description):
            block = self._new_frame(settings_content, 'bg')
            block.pack(fill='x', padx=pad, pady=(0, p(26)))
            self.label(block, title_text, 14, bg_role='bg').pack(anchor='w')
            self.wrap_label(self.label(block, description, 10, fg_role='muted', bg_role='bg', justify='left')).pack(fill='x', pady=(p(5), p(12)))
            self._new_separator(block, 'line').pack(fill='x', pady=(0, p(16)))
            return block

        program_section = section('响指启动程序', '响指识别不依赖声音。选择一个 .exe，识别到响指后启动它。')
        program_row = self._new_frame(program_section, 'bg')
        program_row.pack(fill='x')
        program_row.grid_columnconfigure(0, weight=1)
        self.path_entry = ttk.Entry(program_row, textvariable=self.program_path)
        self.path_entry.grid(row=0, column=0, sticky='ew', padx=(0, p(12)))
        self.browse_button = ttk.Button(program_row, text='选择程序 .exe', command=self.choose_program)
        self.browse_button.grid(row=0, column=1, sticky='e')

        camera_section = section('相机与隐私', '相机只在你明确开启后使用；关闭相机或退出后释放设备。')
        camera_row = self._new_frame(camera_section, 'bg')
        camera_row.pack(fill='x', pady=(0, p(10)))
        self.label(camera_row, '摄像头编号', 10, bg_role='bg').pack(side='left')
        self.camera_input = ttk.Spinbox(camera_row, from_=0, to=9, width=4, textvariable=self.camera_index)
        self.camera_input.pack(side='left', padx=(p(12), 0))
        self.background_check = ttk.Checkbutton(camera_section, text='允许后台快捷键开启相机', variable=self.background_camera,
                                                 style='Settings.TCheckbutton')
        self.background_check.pack(anchor='w')
        self.auto_check = ttk.Checkbutton(camera_section, text='响指或点击成功后自动关闭相机', variable=self.auto_off,
                                          style='Settings.TCheckbutton')
        self.auto_check.pack(anchor='w')
        self.settings_lock_label = self.label(camera_section, '关闭相机后可修改设置。', 10, fg_role='muted', bg_role='bg')
        self.settings_lock_label.pack(anchor='w', pady=(p(9), 0))

        debug_section = section('调试与鼠标', '这些选项只影响运行方式，不会改变本地模型或保存相机画面。')
        self.preview_check = ttk.Checkbutton(debug_section, text='仅预览手势，不控制电脑', variable=self.preview_only,
                                             style='Settings.TCheckbutton')
        self.preview_check.pack(anchor='w')
        self.mouse_check = ttk.Checkbutton(debug_section, text='启用鼠标操作（实验性）', variable=self.mouse_enabled,
                                           style='Settings.TCheckbutton')
        self.mouse_check.pack(anchor='w')

        appearance_section = section('外观', '切换界面颜色，不会重启程序，也不会开启或关闭相机。')
        theme_row = self._new_frame(appearance_section, 'bg')
        theme_row.pack(fill='x')
        self.label(theme_row, '主题', 10, bg_role='bg').pack(side='left', padx=(0, p(18)))
        ttk.Radiobutton(theme_row, text='浅色', value='light', variable=self.theme_var,
                        style='Theme.TRadiobutton').pack(side='left', padx=(0, p(18)))
        ttk.Radiobutton(theme_row, text='深色', value='dark', variable=self.theme_var,
                        style='Theme.TRadiobutton').pack(side='left')

        guide = self._new_frame(self.page_container, 'bg')
        guide.grid(row=0, column=0, sticky='nsew')
        self.pages['guide'] = guide
        guide_content = self.scroll_page(guide)
        self.label(guide_content, '手势指南', 22, bg_role='bg').pack(fill='x', padx=pad, pady=(p(28), p(6)))
        self.wrap_label(self.label(guide_content, '当前使用一只手识别。鼠标操作需在设置中启用；「仅预览」会暂停全部电脑操作。', 10,
                   fg_role='muted', bg_role='bg', justify='left')).pack(fill='x', padx=pad, pady=(0, p(22)))
        gestures = (
            ('移动鼠标', '只伸出食指，在画面内移动手指。'),
            ('左键 / 右键', '收起其他手指，拇指与食指短暂捏合为左键；拇指与中指捏合并保持约 0.4 秒为右键。'),
            ('上下滚动', '伸出食指和中指，上下移动手部。'),
            ('打开自选程序', '中指做一次快速弹动，形成响指动作；不要求麦克风声音。'),
            ('退出程序', '张开手掌，快速向左或向右横扫。'),
        )
        for index, (action_name, how) in enumerate(gestures):
            row = self._new_frame(guide_content, 'bg')
            row.pack(fill='x', padx=pad, pady=(0, p(16)))
            self.label(row, action_name, 12, bg_role='bg').pack(anchor='w')
            self.wrap_label(self.label(row, how, 10, fg_role='muted', bg_role='bg', justify='left')).pack(fill='x', pady=(p(5), p(10)))
            if index < len(gestures) - 1:
                self._new_separator(row, 'line').pack(fill='x')
        self.wrap_label(self.label(guide_content, '快捷键：Ctrl + Alt + G 开启 / 关闭相机；Ctrl + Alt + H 显示窗口；Esc 在窗口内关闭相机。',
                   10, fg_role='muted', bg_role='bg', justify='left')).pack(fill='x', padx=pad, pady=(0, p(30)))

        footer = self._new_frame(main, 'bg')
        footer.grid(row=1, column=0, sticky='ew', padx=p(32), pady=(p(6), p(18)))
        self.notice = self.label(footer, '准备就绪 · 不录音 · 不保存相机画面', 10, fg_role='muted', bg_role='bg')
        self.notice.pack(fill='x')
        self.notice.bind('<Configure>', lambda e: self.notice.config(wraplength=e.width))
        self.current_page = 'home'
        self.show_page('home')
        self._update_program_summary()

    def _update_nav_buttons(self):
        if not hasattr(self, 'nav_buttons'):
            return
        for key, button in self.nav_buttons.items():
            selected = key == getattr(self, 'current_page', 'home')
            bg = self.palette['soft'] if selected else self.palette['sidebar']
            fg = self.palette['accent'] if selected else self.palette['ink']
            try:
                button.configure(bg=bg, fg=fg, activebackground=bg,
                                 activeforeground=fg)
            except tk.TclError:
                pass

    def show_page(self, page):
        """Raise one existing page; no session or camera lifecycle changes."""
        if page not in self.pages:
            return
        self.current_page = page
        self.pages[page].tkraise()
        self._update_nav_buttons()
        if page == 'home' and self.last_state != 'on':
            self.render_empty()

    def _update_program_summary(self):
        if not hasattr(self, 'program_summary'):
            return
        path = self.program_path.get().strip()
        name = Path(path).name if path else ''
        text = f'响指打开：{name or "未选择程序"}'
        available = self.program_summary.winfo_width() - self._u(8)
        if available > 0:
            from tkinter.font import Font
            font = Font(font=self.program_summary.cget('font'))
            if font.measure(text) > available:
                while text and font.measure(text + '…') > available:
                    text = text[:-1]
                text += '…'
        self.program_summary.config(text=text)

    def _set_settings_enabled(self, state):
        locked = state in ('starting', 'on', 'stopping')
        controls = (self.camera_input, self.preview_check, self.auto_check,
                    self.background_check, self.mouse_check, self.browse_button,
                    self.path_entry)
        for control in controls:
            try:
                control.configure(state='disabled' if locked else 'normal')
            except tk.TclError:
                pass
        if hasattr(self, 'settings_lock_label'):
            self.settings_lock_label.config(
                text='相机运行中，关闭相机后可修改设置。' if locked else '设置会自动保存。')

    def render_empty(self):
        if not hasattr(self, 'canvas') or not self.canvas.winfo_exists():
            return
        self.canvas.delete('all')
        self.photo = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        s = self.scale
        c = self.palette
        self.canvas.create_rectangle(w/2-32*s, h/2-92*s, w/2+32*s, h/2-48*s,
                                     outline=c['muted'], width=max(1, round(2*s)))
        self.canvas.create_oval(w/2-12*s, h/2-82*s, w/2+12*s, h/2-58*s,
                                outline=c['muted'], width=max(1, round(2*s)))
        self.canvas.create_text(w/2, h/2-8*s,
                                text=STATUS.get(self.session.get_snapshot()['state'], '相机已关闭'),
                                fill=c['ink'], font=('Microsoft YaHei UI', 20))
        self.canvas.create_text(w/2, h/2+32*s, text='准备好时，按 Ctrl + Alt + G 打开相机',
                                fill=c['muted'], font=('Microsoft YaHei UI', 11),
                                width=max(200, w-48*s))
        self.canvas.create_text(w/2, h/2+68*s, text='关闭后释放摄像头，不保留上一帧画面',
                                fill=c['muted'], font=('Microsoft YaHei UI', 10),
                                width=max(200, w-48*s))

    def choose_program(self):
        path = filedialog.askopenfilename(title='选择响指要打开的程序', filetypes=[('Windows 程序', '*.exe')])
        if path:
            self.program_path.set(path)
            self._update_program_summary()
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
            self.log('后台相机尚未授权。请到「设置」勾选「允许后台快捷键开启相机」。')
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
            state_color = self.palette['accent'] if state == 'on' else self.palette['danger'] if state == 'error' else self.palette['muted']
            state_text = '●  ' + STATUS.get(state, state)
            self.state_label.config(text=state_text, fg=state_color)
            self.nav_state_label.config(text=state_text, fg=state_color)
            button_text = {'off': '开启相机', 'on': '关闭相机', 'starting': '取消开启', 'stopping': '正在关闭…', 'error': '重试打开相机'}
            self.toggle_button.config(text=button_text.get(state, '开启相机'), state='disabled' if state == 'stopping' else 'normal')
            self._set_settings_enabled(state)
            self.tray.update(state)
            if state != 'on':
                self.render_empty()
        image = snap.get('image')
        if state == 'on' and image is not None and self.current_page == 'home' and self.root.state() not in ('withdrawn', 'iconic'):
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
