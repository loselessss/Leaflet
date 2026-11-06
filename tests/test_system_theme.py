import os
import unittest
from unittest.mock import patch


class SystemThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.enterContext(patch('pdfeditor.settings.theme_mode', return_value='system'))

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


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        from pathlib import Path
        from pdfeditor import settings
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.enterContext(patch.object(settings, 'PATH', str(Path(self.directory.name)/'settings.json')))
        self.enterContext(patch.object(settings, '_OLD_PATH', str(Path(self.directory.name)/'absent.json')))
        self.windows = self.enterContext(patch('pdfeditor.system_theme.windows_dark_mode', return_value=False))
        self.buttons = []
        controller = getattr(self.app, '_leaflet_theme_controller', None)
        if controller is not None:
            controller.dark = controller.mode = None
            controller.refresh()

    def tearDown(self):
        from PyQt5.QtCore import QEvent
        from pdfeditor.theme import apply_theme_colors
        for button in self.buttons:
            button.close()
            button.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        apply_theme_colors(self.app, False)

    def button(self):
        from pdfeditor.appearance import ThemeButton
        button = ThemeButton()
        self.buttons.append(button)
        return button

    def test_ribbon_toggle_updates_all_buttons_and_system_menu_restores_following(self):
        from pdfeditor import settings
        first, second = self.button(), self.button()
        self.assertFalse(first.isChecked())
        first.click()
        self.assertEqual(settings.theme_mode(), 'dark')
        self.assertTrue(self.app.property('leafletDark'))
        self.assertTrue(second.isChecked())
        self.assertTrue(second.mode_actions['dark'].isChecked())
        second.click()
        self.windows.return_value = True
        second.controller.refresh()
        self.assertEqual(settings.theme_mode(), 'light')
        self.assertFalse(self.app.property('leafletDark'))
        self.assertFalse(first.isChecked())
        first.mode_actions['system'].trigger()
        self.assertEqual(settings.theme_mode(), 'system')
        self.assertTrue(self.app.property('leafletDark'))
        self.assertTrue(second.isChecked())
        self.assertTrue(second.mode_actions['system'].isChecked())

    def test_saved_dark_choice_is_used_by_a_new_controller(self):
        from pdfeditor import settings
        from pdfeditor.system_theme import SystemThemeController
        settings.set_theme_mode('dark')
        controller = SystemThemeController(self.app)
        try:
            controller.refresh()
            self.assertTrue(controller.dark)
            self.assertTrue(self.app.property('leafletDark'))
        finally:
            self.app.removeEventFilter(controller)
            self.app.removeNativeEventFilter(controller.native_filter)
            controller.deleteLater()

    def test_moon_right_click_opens_appearance_without_toggling_or_hiding(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QContextMenuEvent
        button = self.button()
        checked = button.isChecked()
        event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(5, 5), QPoint(10, 10))
        with patch.object(button.appearance_menu, 'exec_') as popup:
            self.app.sendEvent(button, event)
            popup.assert_called_once_with(QPoint(10, 10))
        self.assertTrue(event.isAccepted())
        self.assertEqual(button.isChecked(), checked)
        self.assertIn('dark', button.mode_actions)
        self.assertIn('dark_ui', button.mode_actions)

    def test_view_menu_and_ribbon_keep_the_same_appearance_settings(self):
        from PyQt5.QtWidgets import QMenu
        from pdfeditor.appearance import add_appearance_menu
        from pdfeditor import settings
        button = self.button()
        view = QMenu()
        try:
            menu = add_appearance_menu(view)
            self.assertIsNone(button.menu())
            menu.mode_actions['dark'].trigger()
            self.assertTrue(button.isChecked())
            button.click()
            self.assertTrue(menu.mode_actions['light'].isChecked())
            menu.mode_actions['dark_ui'].trigger()
            self.assertFalse(settings.document_night())
            self.assertTrue(button.mode_actions['dark_ui'].isChecked())
            self.assertTrue(button.isChecked())
        finally:
            view.deleteLater()

    def test_document_colors_follow_theme_and_remember_inclusion_across_toggles(self):
        from pdfeditor import settings
        from pdfeditor.reader_view import ReaderPageView
        first, second = self.button(), self.button()
        self.assertTrue(settings.document_night())
        reader = ReaderPageView(use_opengl=False, document_colors=True)
        try:
            self.assertFalse(reader._document_night_enabled)
            first.click()
            self.assertTrue(reader._document_night_enabled)
            first.mode_actions['dark_ui'].trigger()
            self.assertTrue(self.app.property('leafletDark'))
            self.assertFalse(reader._document_night_enabled)
            self.assertTrue(second.mode_actions['dark_ui'].isChecked())
            second.click()
            first.click()
            self.assertFalse(reader._document_night_enabled)
            first.mode_actions['dark'].trigger()
            self.assertTrue(reader._document_night_enabled)
            first.mode_actions['system'].trigger()
            self.assertFalse(reader._document_night_enabled)
            self.windows.return_value = True
            first.controller.refresh()
            self.assertTrue(reader._document_night_enabled)
            self.windows.return_value = False
            first.controller.refresh()
            self.assertFalse(reader._document_night_enabled)
        finally:
            reader.close()
            reader.deleteLater()

    def test_invalid_theme_values_keep_system_default_and_preserve_settings(self):
        from pdfeditor import settings
        settings._save({'theme_mode': 'invalid', 'recent': ['keep.pdf']})
        self.assertEqual(settings.theme_mode(), 'system')
        self.assertFalse(settings.set_theme_mode('invalid'))
        self.assertEqual(settings._load()['recent'], ['keep.pdf'])
        settings.set_theme_mode('light')
        self.assertEqual(settings.theme_mode(), 'light')
        self.assertEqual(settings._load()['recent'], ['keep.pdf'])
