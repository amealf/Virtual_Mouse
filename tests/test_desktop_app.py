import json
import queue
import unittest
from unittest.mock import Mock

from desktop_app import DesktopApp


class DesktopPrivacyTests(unittest.TestCase):
    def panel(self, running=False):
        panel = DesktopApp.__new__(DesktopApp)
        panel.closing = False
        panel.root = Mock()
        panel.root.state.return_value = 'withdrawn'
        panel.session = Mock()
        panel.session.is_running = running
        panel.background_camera = Mock()
        panel.background_camera.get.return_value = False
        panel.show = Mock()
        panel.log = Mock()
        panel.turn_off = Mock()
        return panel

    def test_hidden_camera_requires_consent(self):
        panel = self.panel()
        panel.toggle()
        panel.session.start.assert_not_called()
        panel.show.assert_called_once()

    def test_camera_off_does_not_require_consent(self):
        panel = self.panel(running=True)
        panel.toggle()
        panel.turn_off.assert_called_once()
        panel.show.assert_not_called()

    def test_malformed_setting_values_are_safe(self):
        panel = self.panel()
        panel.settings_path = Mock()
        panel.settings_path.read_text.return_value = '{"camera_index":"bad","background_camera":"true","program_path":25,"theme":[]}'
        settings = panel._read_settings()
        self.assertEqual(settings['camera_index'], 0)
        self.assertEqual(settings['program_path'], '')
        self.assertFalse(settings['background_camera'])
        self.assertEqual(settings['theme'], 'light')

    def test_theme_switch_preserves_active_camera_and_saves_choice(self):
        panel = self.panel(running=True)
        panel._configure_styles = Mock()
        panel._theme_widgets = {}
        panel._update_nav_buttons = Mock()
        panel.last_state = 'on'
        panel.theme_var = Mock()
        panel.theme_var.get.return_value = 'dark'
        panel.args = Mock(test_seconds=0)
        panel.settings_path = Mock()
        for name, value in (('camera_index', 0), ('preview_only', False),
                            ('auto_off', True), ('mouse_enabled', False),
                            ('program_path', 'C:/Apps/example.exe')):
            variable = Mock()
            variable.get.return_value = value
            setattr(panel, name, variable)
        panel.apply_theme('dark')
        self.assertEqual(panel.theme_name, 'dark')
        panel.session.start.assert_not_called()
        panel.session.stop.assert_not_called()
        saved = json.loads(panel.settings_path.write_text.call_args.args[0])
        self.assertEqual(saved['theme'], 'dark')
        self.assertTrue(saved['auto_off'])
        self.assertFalse(saved['background_camera'])

    def test_page_navigation_leaves_camera_running(self):
        panel = self.panel(running=True)
        panel.pages = {'home': Mock(), 'settings': Mock(), 'guide': Mock()}
        panel.last_state = 'on'
        panel._update_nav_buttons = Mock()
        panel.render_empty = Mock()
        for page in ('settings', 'guide', 'home'):
            panel.show_page(page)
            self.assertEqual(panel.current_page, page)
            panel.pages[page].tkraise.assert_called_once()
        panel.session.start.assert_not_called()
        panel.session.stop.assert_not_called()
        panel.render_empty.assert_not_called()

    def test_auto_off_clears_preview_while_settings_page_is_visible(self):
        panel = self.panel()
        panel.commands = queue.Queue()
        panel.session.events = queue.Queue()
        panel.session.get_snapshot.return_value = {'state': 'off'}
        panel.last_state = 'on'
        panel.current_page = 'settings'
        panel.palette = {'muted': '#526273'}
        for name in ('state_label', 'nav_state_label', 'toggle_button',
                     '_set_settings_enabled', 'tray', 'render_empty', 'feedback'):
            setattr(panel, name, Mock())
        panel.poll()
        panel.render_empty.assert_called_once()


if __name__ == '__main__':
    unittest.main()
