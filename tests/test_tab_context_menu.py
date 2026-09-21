import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QContextMenuEvent
from PyQt5.QtWidgets import QApplication, QAction, QMainWindow, QTabWidget, QWidget
from pdfeditor.app import TransferTabBar


class TabContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_targets_clicked_document_without_switching(self):
        shell = QMainWindow()
        shell._tabs = QTabWidget(shell)
        bar = TransferTabBar(shell._tabs)
        shell._tabs.setTabBar(bar)
        shell.setCentralWidget(shell._tabs)
        first, second = QWidget(), QWidget()
        first._tab_context_actions = (QAction("first", first),)
        second._tab_context_actions = (QAction("second", second),)
        shell._tabs.addTab(first, "First")
        shell._tabs.addTab(second, "Second")
        try:
            event = QContextMenuEvent(QContextMenuEvent.Mouse,
                                      bar.tabRect(1).center())
            with patch("pdfeditor.app.QMenu") as menu:
                bar.contextMenuEvent(event)
                menu.return_value.addAction.assert_called_once_with(
                    second._tab_context_actions[0])
                menu.return_value.exec_.assert_called_once()
            self.assertIs(shell._tabs.currentWidget(), first)
            with patch("pdfeditor.app.QMenu") as menu:
                bar.contextMenuEvent(QContextMenuEvent(
                    QContextMenuEvent.Mouse, QPoint(-10, -10)))
                menu.assert_not_called()
        finally:
            shell.close()
