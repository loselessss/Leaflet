import os
import unittest
from unittest.mock import patch


class SystemThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        from pdfeditor.theme import apply_theme_colors
        apply_theme_colors(self.app, False)

    def test_palette_icons_and_reader_surround_follow_theme(self):
        from PyQt5.QtGui import QPalette
        from pdfeditor.icons import fluent_icon
        from pdfeditor.theme import apply_theme_colors, reader_background
        icon = fluent_icon('sidebar_left')
        fixed = fluent_icon('open', '#ffffff')
        frames = []
        for dark in (False, True):
            apply_theme_colors(self.app, dark)
            self.assertEqual(self.app.palette().color(QPalette.Window).lightness() < 128, dark)
            self.assertEqual(reader_background().lightness() < 128, dark)
            image = icon.pixmap(24, 24).toImage()
            self.assertFalse(image.isNull())
            pixels = [image.pixelColor(x, y) for x in range(image.width())
                      for y in range(image.height()) if image.pixelColor(x, y).alpha() > 100]
            self.assertTrue(pixels)
            frames.append(sum(p.lightness() for p in pixels) / len(pixels))
            white = fixed.pixmap(24, 24).toImage()
            self.assertTrue(any(white.pixelColor(x, y).red() > 240
                for x in range(white.width()) for y in range(white.height())))
        self.assertGreater(frames[1], frames[0] + 100)

    def test_controller_refreshes_existing_and_new_dialogs(self):
        from PyQt5.QtWidgets import QDialog
        from pdfeditor.system_theme import SystemThemeController
        controller = SystemThemeController(self.app)
        dialog = QDialog()
        try:
            with patch('pdfeditor.system_theme.windows_dark_mode', return_value=True), \
                    patch('pdfeditor.windows_integration.apply_window_dark_mode') as title:
                controller.refresh()
                dialog.show()
                self.app.processEvents()
                self.assertTrue(self.app.property('leafletDark'))
                self.assertTrue(any(call.args == (dialog, True) for call in title.call_args_list))
            with patch('pdfeditor.system_theme.windows_dark_mode', return_value=False):
                controller.refresh()
                self.assertFalse(self.app.property('leafletDark'))
        finally:
            dialog.close()
            self.app.removeEventFilter(controller)
            self.app.removeNativeEventFilter(controller.native_filter)
            controller.deleteLater()

    def test_dark_stylesheet_keeps_accent_text_and_balanced_rules(self):
        from pdfeditor.theme import DARK_STYLESHEET
        self.assertEqual(DARK_STYLESHEET.count('{'), DARK_STYLESHEET.count('}'))
        self.assertIn('selection-color: #ffffff;', DARK_STYLESHEET)
        self.assertIn('color: #f3f3f3;', DARK_STYLESHEET)
        self.assertNotIn('WHITE_TEXT', DARK_STYLESHEET)
