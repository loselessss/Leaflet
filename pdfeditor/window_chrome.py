"""Compact standalone window chrome; embedded windows retain native frames."""

import sys

from PyQt5.QtCore import QEvent, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (QHBoxLayout, QLabel, QStackedWidget, QStyle,
                             QToolButton, QVBoxLayout, QWidget)

from .i18n import localize


class DocumentTabs(QStackedWidget):
    """Document stack whose tab bar can live in the window caption."""

    tabCloseRequested = pyqtSignal(int)

    def __init__(self, bar, parent=None):
        super().__init__(parent)
        self._bar = bar
        bar.currentChanged.connect(self.setCurrentIndex)
        self.currentChanged.connect(bar.setCurrentIndex)
        bar.tabCloseRequested.connect(self.tabCloseRequested)
        bar.tabMoved.connect(self._move_tab)

    def tabBar(self):
        return self._bar

    def setTabsClosable(self, enabled):
        self._bar.setTabsClosable(enabled)

    def setMovable(self, enabled):
        self._bar.setMovable(enabled)

    def setDocumentMode(self, enabled):
        self._bar.setDocumentMode(enabled)

    def addTab(self, widget, title):
        return self.insertTab(self.count(), widget, title)

    def insertTab(self, index, widget, title):
        # Signals must see the bar and stack in the same order, including the
        # first tab and a tab arriving from another window.
        previous = self.currentWidget()
        self.blockSignals(True)
        self._bar.blockSignals(True)
        try:
            index = self.insertWidget(index, widget)
            self._bar.insertTab(index, title)
            self._bar.setCurrentIndex(self.currentIndex())
        finally:
            self._bar.blockSignals(False)
            self.blockSignals(False)
        if previous is not self.currentWidget():
            self.currentChanged.emit(self.currentIndex())
        return index

    def removeTab(self, index):
        widget = self.widget(index)
        if widget is None:
            return
        self.blockSignals(True)
        self._bar.blockSignals(True)
        try:
            self.removeWidget(widget)
            widget.hide()
            self._bar.removeTab(index)
            self._bar.setCurrentIndex(self.currentIndex())
        finally:
            self._bar.blockSignals(False)
            self.blockSignals(False)
        self.currentChanged.emit(self.currentIndex())

    def _move_tab(self, source, target):
        active = self.currentWidget()
        widget = self.widget(source)
        self.blockSignals(True)
        try:
            self.removeWidget(widget)
            self.insertWidget(target, widget)
            self.setCurrentWidget(active)
        finally:
            self.blockSignals(False)
        self.currentChanged.emit(self.currentIndex())

    def tabText(self, index):
        return self._bar.tabText(index)

    def setTabText(self, index, text):
        self._bar.setTabText(index, text)

    def setTabToolTip(self, index, text):
        self._bar.setTabToolTip(index, text)


class CaptionButton(QToolButton):
    """Small single-stroke controls, independent of the system icon theme."""

    def __init__(self, kind, parent):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(36, 30)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#ffffff" if self.kind == "close" and self.underMouse()
                                  else "#42464d"), 1.0))
        painter.translate(self.width() / 2 - 4.5, self.height() / 2 - 4.5)
        if self.kind == "minimize":
            painter.drawLine(0, 5, 9, 5)
        elif self.kind == "close":
            painter.drawLine(0, 0, 9, 9)
            painter.drawLine(9, 0, 0, 9)
        elif self.kind == "restore":
            painter.drawRect(QRectF(2, 0, 7, 7))
            painter.fillRect(QRectF(0, 2, 7, 7), QColor("#e9edf2"))
            painter.drawRect(QRectF(0, 2, 7, 7))
        else:
            painter.drawRect(QRectF(0, 0, 9, 9))


class WindowChrome(QWidget):
    def __init__(self, window, bar):
        super().__init__(window)
        self.owner = window
        self.bar = bar
        self.menubar = None
        self.setObjectName("windowChrome")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.caption = QWidget(self)
        self.caption.setObjectName("windowCaption")
        row = QHBoxLayout(self.caption)
        row.setContentsMargins(8, 4, 0, 0)
        row.setSpacing(0)
        self.brand = QLabel("sPDF", self.caption)
        self.brand.setContentsMargins(4, 0, 12, 0)
        self.brand.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.brand)
        bar.setExpanding(False)
        bar.setElideMode(Qt.ElideMiddle)
        bar.setUsesScrollButtons(True)
        bar.setObjectName("captionTabs")
        row.addWidget(bar, 1)
        self.drag_space = QWidget(self.caption)
        self.drag_space.setFixedWidth(48)
        row.addWidget(self.drag_space)
        self.minimize = self._button("minimize",
                                    localize("Minimize", "최소화"), window.showMinimized)
        self.maximize = self._button("maximize",
                                    localize("Maximize", "최대화"), self.toggle_maximized)
        self.close_button = self._button("close",
                                        localize("Close", "닫기"), window.close)
        self.close_button.setObjectName("captionClose")
        for button in (self.minimize, self.maximize, self.close_button):
            row.addWidget(button)
        self.layout.addWidget(self.caption)
        self.caption_divider = QWidget(self)
        self.caption_divider.setObjectName("captionDivider")
        self.caption_divider.setFixedHeight(1)
        self.layout.addWidget(self.caption_divider)
        self.caption.installEventFilter(self)
        self.drag_space.installEventFilter(self)
        bar.installEventFilter(self)
        window.installEventFilter(self)
        self.setStyleSheet("""
            QWidget#windowCaption { background: #e9edf2; }
            QWidget#captionDivider { background: #c9ced6; }
            QTabBar#captionTabs { background: transparent; }
            QTabBar#captionTabs::tab { min-width: 90px; max-width: 290px;
                min-height: 30px; font-weight: normal; }
            QToolButton { border: 0; border-radius: 0; background: transparent; }
            QToolButton:hover { background: #dce1e7; }
            QToolButton#captionClose:hover { background: #e45b60; }
        """)

    def _button(self, kind, text, callback):
        button = CaptionButton(kind, self.caption)
        button.setToolTip(text)
        button.setAccessibleName(text)
        button.clicked.connect(callback)
        return button

    def set_menubar(self, menubar):
        if self.menubar is menubar:
            return
        if self.menubar is not None:
            self.layout.removeWidget(self.menubar)
            self.menubar.hide()
            self.menubar.setParent(None)
        self.menubar = menubar
        self.layout.addWidget(menubar)
        menubar.show()

    def toggle_maximized(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() == QEvent.WindowStateChange:
            maximized = self.owner.isMaximized()
            self.maximize.kind = "restore" if maximized else "maximize"
            self.maximize.update()
            self.maximize.setToolTip(localize("Restore", "이전 크기로") if maximized
                                     else localize("Maximize", "최대화"))
        if watched in (self.caption, self.drag_space, self.bar):
            empty = watched is not self.bar or (
                hasattr(event, "pos") and self.bar.tabAt(event.pos()) < 0)
            if empty and event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                self.toggle_maximized()
                return True
            if empty and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                handle = self.owner.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                return True
        return super().eventFilter(watched, event)


def resize_hit_test(x, y, width, height, border):
    """Win32 non-client edge constants, in physical pixels."""
    left, right = x < border, x >= width - border
    top, bottom = y < border, y >= height - border
    if top:
        return 13 if left else 14 if right else 12
    if bottom:
        return 16 if left else 17 if right else 15
    return 10 if left else 11 if right else None


def native_frame_event(window, message):
    if sys.platform != "win32" or window.isFullScreen():
        return None
    import ctypes
    from ctypes import wintypes
    msg = wintypes.MSG.from_address(int(message))
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    if msg.message == 0x84 and not window.isMaximized():  # WM_NCHITTEST
        rect = wintypes.RECT()
        if not user32.GetWindowRect(msg.hWnd, ctypes.byref(rect)):
            return None
        x = ctypes.c_short(msg.lParam & 0xffff).value - rect.left
        y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value - rect.top
        return resize_hit_test(x, y, rect.right - rect.left, rect.bottom - rect.top,
                               max(4, round(5 * window.devicePixelRatioF())))
    if msg.message == 0x24:  # WM_GETMINMAXINFO: don't cover the taskbar.
        class MonitorInfo(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                        ("work", wintypes.RECT), ("flags", wintypes.DWORD)]
        class MinMaxInfo(ctypes.Structure):
            _fields_ = [(name, wintypes.POINT) for name in
                        ("reserved", "max_size", "max_position", "min_track", "max_track")]
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        monitor = user32.MonitorFromWindow(msg.hWnd, 2)
        info = MonitorInfo()
        info.size = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            bounds = MinMaxInfo.from_address(msg.lParam)
            bounds.max_position.x = info.work.left - info.monitor.left
            bounds.max_position.y = info.work.top - info.monitor.top
            bounds.max_size.x = info.work.right - info.work.left
            bounds.max_size.y = info.work.bottom - info.work.top
            ratio = window.devicePixelRatioF()
            bounds.min_track.x = round(window.minimumWidth() * ratio)
            bounds.min_track.y = round(window.minimumHeight() * ratio)
            return 0
    return None
