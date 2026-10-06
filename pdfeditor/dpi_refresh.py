"""Refresh Qt and native rendering together after a screen-density change."""
from PyQt5.QtCore import QObject, QEvent, QTimer
from PyQt5.QtWidgets import QWidget


class DpiRefreshController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.handle = None
        self.screen = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
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
                self.handle.screenChanged.disconnect(self.screen_changed)
            except (RuntimeError, TypeError):
                pass
        self.handle = handle
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
        self.timer.start()

    def refresh(self):
        if not self.window.isVisible():
            return
        for index in range(self.window._tabs.count()):
            tab = self.window._tabs.widget(index)
            refresh = getattr(tab.view, "refresh_display_density", None)
            if refresh is not None:
                refresh()
            tab._schedule_thumbs()
        widgets = [self.window, *self.window.findChildren(QWidget)]
        for widget in widgets:
            layout = QWidget.layout(widget)
            if layout is not None:
                layout.invalidate()
                layout.activate()
            widget.updateGeometry()
            widget.update()
        if self.handle is not None:
            self.handle.requestUpdate()
        # QWidget.update() alone need not invalidate native child HWNDs.
        # Let Windows queue repaint of the frame and every child as well.
        import sys
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            redraw = ctypes.windll.user32.RedrawWindow
            redraw.argtypes = [wintypes.HWND, ctypes.c_void_p,
                               wintypes.HANDLE, wintypes.UINT]
            redraw.restype = wintypes.BOOL
            redraw(int(self.window.winId()), None, None, 0x0485)
