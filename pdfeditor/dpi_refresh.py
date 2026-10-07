"""Refresh Qt and native rendering together after a screen-density change."""
import sys

from PyQt5.QtCore import QObject, QEvent, QTimer, Qt
from PyQt5.QtGui import QResizeEvent
from PyQt5.QtWidgets import QApplication, QWidget


def refresh_widget_layout(widget):
    """Replay resize refresh without changing size or calculating positions."""
    layout = QWidget.layout(widget)
    if layout is not None:
        layout.invalidate()
    widget.updateGeometry()
    size = widget.size()
    QApplication.sendEvent(widget, QResizeEvent(size, size))


class DpiRefreshController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.handle = None
        self.screen = None
        self._density = window.devicePixelRatioF()
        self._remap_pending = False
        self._in_size_move = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.setInterval(250)
        self.settle_timer.timeout.connect(self.refresh_settled)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Show, QEvent.WinIdChange):
            self.attach()
        return False

    def attach(self):
        handle = self.window.windowHandle()
        if handle is None or handle is self.handle:
            return
        if self.handle is not None:
            try:
                self.handle.removeEventFilter(self)
                self.handle.screenChanged.disconnect(self.screen_changed)
            except (RuntimeError, TypeError):
                pass
        self.handle = handle
        handle.installEventFilter(self)
        handle.screenChanged.connect(self.screen_changed)
        self.screen_changed(handle.screen())

    def screen_changed(self, screen):
        if self.screen is not None:
            try:
                self.screen.logicalDotsPerInchChanged.disconnect(self.schedule)
            except (RuntimeError, TypeError):
                pass
        self.screen = screen
        if screen is not None:
            screen.logicalDotsPerInchChanged.connect(self.schedule)
        self.schedule()

    def schedule(self, *_args):
        # Qt must apply its own DPI geometry first. Never rescale document zoom.
        density = self.window.devicePixelRatioF()
        if density != self._density:
            self._remap_pending = True
            self._density = density
        self.timer.start()
        self.settle_timer.start()

    def native_dpi_changed(self, message):
        """Observe WM_DPICHANGED without consuming Qt's suggested geometry."""
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == 0x02E0:
            self._remap_pending = True
            self.schedule()
        elif msg.message == 0x0231:  # WM_ENTERSIZEMOVE
            self._in_size_move = True
        elif msg.message == 0x0232:  # WM_EXITSIZEMOVE
            self._in_size_move = False
            if self._remap_pending:
                self.settle_timer.start()

    def refresh_settled(self):
        """Remap the complete widget tree, not only the PDF swap chain.

        Synthetic resize events do not remap Qt's native children/backing store.
        Hide/show asks Qt and Windows to refresh those surfaces at the new DPI.
        Do not interrupt the native move loop or restore stale pixel geometry.
        """
        window = self.window
        if self._in_size_move or not window.isVisible() or window.isMinimized():
            return
        if self._remap_pending:
            self._remap_pending = False
            self._density = window.devicePixelRatioF()
            focus = window.focusWidget()
            active = window.isActiveWindow()
            no_activate = window.testAttribute(Qt.WA_ShowWithoutActivating)
            try:
                window.setAttribute(Qt.WA_ShowWithoutActivating, True)
                window.hide()
                window.show()
            finally:
                window.setAttribute(Qt.WA_ShowWithoutActivating, no_activate)
            if active:
                window.activateWindow()
                if focus is not None:
                    focus.setFocus(Qt.OtherFocusReason)
        self.refresh()

    def refresh(self):
        if not self.window.isVisible():
            return
        widgets = [self.window, *self.window.findChildren(QWidget)]
        for widget in widgets:
            if not widget.isWindow() or widget is self.window:
                refresh_widget_layout(widget)
        for widget in widgets:
            layout = QWidget.layout(widget)
            if layout is not None:
                layout.activate()
        # Recreate native rendering only after Qt's resize/layout refresh.
        for index in range(self.window._tabs.count()):
            tab = self.window._tabs.widget(index)
            refresh = getattr(getattr(tab, "view", None), "refresh_display_density", None)
            if refresh is not None:
                refresh()
            schedule_thumbs = getattr(tab, "_schedule_thumbs", None)
            if schedule_thumbs is not None:
                schedule_thumbs()
        for widget in widgets:
            widget.update()
        if self.handle is not None:
            self.handle.requestUpdate()
        # QWidget.update() alone need not invalidate native child HWNDs.
        # Let Windows queue repaint of the frame and every child as well.
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            redraw = ctypes.windll.user32.RedrawWindow
            redraw.argtypes = [wintypes.HWND, ctypes.c_void_p,
                               wintypes.HANDLE, wintypes.UINT]
            redraw.restype = wintypes.BOOL
            redraw(int(self.window.winId()), None, None, 0x0485)
