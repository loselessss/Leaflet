import os
import unittest
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget

from pdfeditor.dpi_refresh import DpiRefreshController, refresh_widget_layout


class DpiRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def test_resize_refresh_preserves_actual_geometry(self):
        class ResizeWidget(QWidget):
            def resizeEvent(self, event):
                self.resizes.append((event.oldSize(), event.size()))
                super().resizeEvent(event)
        widget = ResizeWidget()
        widget.resizes = []
        widget.setGeometry(20, 40, 300, 200)
        geometry = widget.geometry()
        try:
            for _ in range(3):
                refresh_widget_layout(widget)
            self.assertEqual(widget.geometry(), geometry)
            self.assertEqual(len(widget.resizes), 3)
            for before, after in widget.resizes:
                self.assertEqual(before, after)
                self.assertEqual(after, geometry.size())
        finally:
            widget.deleteLater()

    def test_schedule_restarts_both_passes_during_repeated_transitions(self):
        window = QMainWindow()
        controller = DpiRefreshController(window)
        try:
            for _ in range(3):
                controller.schedule()
                self.assertTrue(controller.timer.isActive())
                self.assertTrue(controller.settle_timer.isActive())
            self.assertGreater(controller.settle_timer.interval(), controller.timer.interval())
        finally:
            window.deleteLater()

    def test_layout_refresh_precedes_surface_refresh(self):
        window = QMainWindow()
        window._tabs = QTabWidget()
        window.setCentralWidget(window._tabs)
        tab = QWidget()
        tab.view = Mock()
        window._tabs.addTab(tab, "Document")
        window.show()
        self.app.processEvents()
        controller = DpiRefreshController(window)
        order = []
        tab.view.refresh_display_density.side_effect = lambda: order.append("surface")
        try:
            with patch("pdfeditor.dpi_refresh.refresh_widget_layout",
                       side_effect=lambda _widget: order.append("layout")), \
                    patch("pdfeditor.dpi_refresh.sys.platform", "linux"):
                controller.refresh()
            self.assertEqual(order[-1], "surface")
            self.assertTrue(all(item == "layout" for item in order[:-1]))
            self.assertGreater(len(order), 1)
        finally:
            window.close()
            window.deleteLater()

    def test_native_dpi_message_schedules_without_consuming_geometry(self):
        import ctypes
        from ctypes import wintypes
        window = QMainWindow()
        controller = DpiRefreshController(window)
        message = wintypes.MSG()
        try:
            with patch("pdfeditor.dpi_refresh.sys.platform", "win32"), \
                    patch.object(controller, "schedule") as schedule:
                message.message = 0x000F
                controller.native_dpi_changed(ctypes.addressof(message))
                schedule.assert_not_called()
                message.message = 0x02E0
                self.assertIsNone(controller.native_dpi_changed(ctypes.addressof(message)))
                schedule.assert_called_once_with()
        finally:
            window.deleteLater()
