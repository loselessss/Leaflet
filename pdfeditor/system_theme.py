"""Windows app-theme notifications, without polling or changing OS settings."""
import sys
from PyQt5.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QTimer, Qt, pyqtSignal


def windows_dark_mode():
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] == 0
    except OSError:
        return False


class _WindowsThemeEvents(QAbstractNativeEventFilter):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and bytes(event_type) in (
                b'windows_generic_MSG', b'windows_dispatcher_MSG'):
            from ctypes import wintypes
            import ctypes
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message in (0x001a, 0x031a):  # WM_SETTINGCHANGE / WM_THEMECHANGED
                self.controller.timer.start()
        return False, 0


class SystemThemeController(QObject):
    appearance_changed = pyqtSignal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.dark = None
        self.mode = None
        self.document_night = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.refresh)
        self.native_filter = _WindowsThemeEvents(self)
        if sys.platform == 'win32':
            app.installNativeEventFilter(self.native_filter)
        app.installEventFilter(self)

    def refresh(self):
        from .theme import apply_theme_colors
        from .settings import theme_mode, document_night
        mode = theme_mode()
        dark = windows_dark_mode() if mode == 'system' else mode == 'dark'
        document = document_night()
        if dark == self.dark and mode == self.mode and document == self.document_night:
            return
        self.mode = mode
        self.dark = dark
        self.document_night = document
        apply_theme_colors(self.app, dark)
        for widget in self.app.topLevelWidgets():
            self._titlebar(widget)
            widget.update()
        self.appearance_changed.emit()

    def _titlebar(self, widget):
        if widget.isWindow() and widget.testAttribute(Qt.WA_WState_Created):
            from .windows_integration import apply_window_dark_mode
            apply_window_dark_mode(widget, self.dark)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show and hasattr(watched, 'isWindow') and watched.isWindow():
            self._titlebar(watched)
        return False
