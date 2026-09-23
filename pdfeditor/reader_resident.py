"""Opt-in, document-free reader residency and per-user launch forwarding."""

import hashlib
import json
import os
import sys

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import settings
from .i18n import localize
from .icons import fluent_icon

MAX_REQUEST_BYTES = 32768


def server_name():
    # Separate installations / development interpreters and Windows users.
    identity = os.path.abspath(settings.PATH) + "|" + os.path.abspath(sys.executable)
    return "spdf-reader-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def forward_to_resident(path=None):
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(200):
        return False
    request = json.dumps({"path": os.path.abspath(path) if path else None}).encode("utf-8") + b"\n"
    if len(request) > MAX_REQUEST_BYTES:
        socket.abort()
        return False
    socket.write(request)
    socket.flush()
    socket.waitForBytesWritten(200)
    received = bytes(socket.readAll())
    if not received and socket.waitForReadyRead(800):
        received = bytes(socket.readAll())
    socket.disconnectFromServer()
    return received.startswith(b"OK\n")


class ReaderResident(QObject):
    def __init__(self, app, *, updates_enabled):
        super().__init__(app)
        self.app = app
        self.updates_enabled = updates_enabled
        self.quitting = False
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.tray = QSystemTrayIcon(app.windowIcon() if not app.windowIcon().isNull()
                                   else fluent_icon("open"), self)
        self.tray.setToolTip(localize("Leaflet reader", "Leaflet 리더"))
        menu = QMenu()
        menu.addAction(localize("Open reader", "리더 열기"), self.restore)
        menu.addSeparator()
        menu.addAction(localize("Exit", "완전히 종료"), self.quit)
        self.tray.setContextMenu(menu)
        self._menu = menu
        self.tray.activated.connect(lambda reason: self.restore() if reason in
            (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        app.aboutToQuit.connect(self.stop)

    def start(self):
        if self.server.isListening():
            return True
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        # Do not remove another reader's live endpoint.
        if not self.server.listen(server_name()):
            return False
        self.tray.show()
        return True

    def stop(self):
        self.server.close()
        self.tray.hide()

    def park(self, window):
        if self.quitting or window.workspace_mode != "reader" or not settings.reader_resident():
            return False
        if not self.start():
            return False
        from .app import _app_windows
        if any(w is not window and w.isVisible() for w in _app_windows):
            return False
        window.hide()
        # Keep only Python/Qt/native modules. Release documents, render targets,
        # caches and file locks; never keep OCR workers on standby.
        while window._tabs.count():
            window._remove_tab(window._tabs.widget(0))
        return True

    def restore(self, path=None):
        from .app import new_window
        window = new_window(path, updates_enabled=self.updates_enabled, workspace_mode="reader")
        window.showNormal() if window.isMinimized() else window.show()
        window.raise_()
        window.activateWindow()

    def quit(self):
        from .app import _app_windows
        self.quitting = True
        for window in list(_app_windows):
            if not window.close():
                self.quitting = False
                return
        self.stop()
        self.app.quit()

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.setReadBufferSize(MAX_REQUEST_BYTES + 1)
            buffer = bytearray()

            def consume(s=socket, pending=buffer):
                pending.extend(bytes(s.readAll()))
                if len(pending) > MAX_REQUEST_BYTES:
                    s.abort()
                    return
                if b"\n" not in pending:
                    return
                try:
                    request = json.loads(bytes(pending).split(b"\n", 1)[0])
                    path = request["path"]
                    if path is not None and not isinstance(path, str):
                        raise ValueError("Invalid path")
                except (ValueError, KeyError, TypeError):
                    s.abort()
                    return
                s.write(b"OK\n")
                s.flush()
                s.disconnectFromServer()
                QTimer.singleShot(0, lambda p=path: self.restore(p))

            socket.readyRead.connect(consume)
            socket.disconnected.connect(socket.deleteLater)
            # Bound idle/partial requests without blocking the GUI thread.
            timeout = QTimer(socket)
            timeout.setSingleShot(True)
            timeout.timeout.connect(socket.abort)
            timeout.start(2000)
            consume()


def configure_residency(enabled, *, updates_enabled=True):
    app = QApplication.instance()
    if app is None or not getattr(app, "_spdf_standalone_reader", False):
        return False
    resident = getattr(app, "_spdf_reader_resident", None)
    if not enabled:
        if resident is not None:
            resident.stop()
            from .app import _app_windows
            if not any(w.isVisible() for w in _app_windows):
                resident.quit()
        return True
    if resident is None:
        resident = ReaderResident(app, updates_enabled=updates_enabled)
        app._spdf_reader_resident = resident
    return resident.start()
