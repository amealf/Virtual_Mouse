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
        panel.settings_path.read_text.return_value = '{"camera_index":"bad","background_camera":"true","program_path":25}'
        settings = panel._read_settings()
        self.assertEqual(settings['camera_index'], 0)
        self.assertEqual(settings['program_path'], '')
        self.assertFalse(settings['background_camera'])


if __name__ == '__main__':
    unittest.main()
