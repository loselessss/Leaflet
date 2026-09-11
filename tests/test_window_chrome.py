import os
import unittest

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QApplication, QTabBar, QWidget

from pdfeditor.window_chrome import DocumentTabs, resize_hit_test


class WindowChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_stack_order_selection_and_close_follow_detached_bar(self):
        tabs = DocumentTabs(QTabBar())
        a, b, c = QWidget(), QWidget(), QWidget()
        tabs.addTab(a, "a")
        tabs.addTab(b, "b")
        tabs.insertTab(1, c, "c")
        self.assertIs(tabs.currentWidget(), a)
        tabs.tabBar().setCurrentIndex(2)
        self.assertIs(tabs.currentWidget(), b)
        tabs.tabBar().moveTab(2, 0)
        self.assertEqual([tabs.widget(i) for i in range(3)], [b, a, c])
        self.assertIs(tabs.currentWidget(), b)
        self.assertEqual(tabs.tabBar().currentIndex(), 0)
        tabs.removeTab(0)
        self.assertIs(tabs.currentWidget(), a)
        self.assertEqual(tabs.tabText(0), "a")
        tabs.removeTab(0)
        tabs.removeTab(0)
        self.assertEqual(tabs.currentIndex(), -1)
        self.assertEqual(tabs.tabBar().count(), 0)
        for widget in (tabs.tabBar(), tabs, a, b, c):
            widget.deleteLater()

    def test_native_resize_edges(self):
        for point, expected in (((1, 1), 13), ((99, 1), 14), ((50, 1), 12),
                                ((1, 99), 16), ((99, 99), 17), ((50, 99), 15),
                                ((1, 50), 10), ((99, 50), 11), ((50, 50), None)):
            self.assertEqual(resize_hit_test(*point, 100, 100, 5), expected)

    def test_only_standalone_workspace_has_caption_tabs(self):
        from pdfeditor.app import AppWindow
        embedded = AppWindow()
        reader = AppWindow(workspace_mode="reader")
        try:
            reader.show()
            self.app.processEvents()
            self.assertIsNone(embedded._window_chrome)
            self.assertFalse(embedded.windowFlags() & Qt.FramelessWindowHint)
            self.assertTrue(reader.windowFlags() & Qt.FramelessWindowHint)
            self.assertIs(reader.menuWidget(), reader._window_chrome)
            self.assertIs(reader._tabs.tabBar().parentWidget(), reader._window_chrome.caption)
            self.assertEqual(reader._window_chrome.caption_divider.width(),
                             reader._window_chrome.width())
            self.assertEqual(reader._window_chrome.caption_divider.height(), 1)
            self.assertLess(reader._window_chrome.caption.mapTo(reader, QPoint()).y(),
                            reader.menuBar().mapTo(reader, QPoint()).y())
            reader._window_chrome.toggle_maximized()
            self.assertTrue(reader.isMaximized())
            reader._window_chrome.toggle_maximized()
            self.assertFalse(reader.isMaximized())
        finally:
            reader.close()
            embedded.close()
