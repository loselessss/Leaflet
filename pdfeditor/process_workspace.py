"""Nonblocking local IPC between independently owned sPDF GUI processes.

No QProcess parent lifetime, shared PDF handles, GUI objects, or waitFor* calls.
A disconnected editor continues editing/recovering and never exits with a reader.
The protocol carries paths and view state, never passwords or document bytes.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication

from .document_snapshot import DocumentSnapshot, file_revision
from .i18n import localize

MAX_MESSAGE = 65536
TIMEOUT = 15.0


def process_python_executable():
    """Return a Python executable whose Popen handle owns the real process."""
    from .paths import is_frozen
    if (not is_frozen() and os.name == "nt" and sys.prefix != sys.base_prefix
            and getattr(sys, "_base_executable", None)):
        return sys._base_executable
    return sys.executable


def process_environment():
    environment = os.environ.copy()
    if process_python_executable() != sys.executable:
        # Preserve the active venv while bypassing the Windows redirector
        # executable, which otherwise leaves Popen tracking a proxy PID.
        environment["__PYVENV_LAUNCHER__"] = sys.executable
    return environment


def process_command(mode, endpoint, token, request_id):
    from .paths import is_frozen
    base = ([sys.executable] if is_frozen() else
            [process_python_executable(), str(Path(__file__).resolve().parents[1] / "run.py")])
    return base + ["--workspace", mode, "--peer", endpoint, "--peer-token", token,
                   "--peer-request", request_id]


@dataclass
class EditorProcess:
    process: object
    path: str
    mode: str
    request: dict
    channel: object = None
    status: str = "starting"
    last_seen: float = 0
    runtime_pid: object = None

    @property
    def pid(self):
        # Some Windows Python launchers remain as a small proxy process.  The
        # authenticated handshake reports the GUI process that actually owns
        # the workspace and its recovery data.
        return self.runtime_pid or self.process.pid


class Channel(QObject):
    def __init__(self, bridge, socket, token, outgoing=False, request_id=None):
        super().__init__(bridge)
        self.bridge, self.socket, self.token = bridge, socket, token
        self.outgoing = outgoing
        self.request_id = request_id
        self.authenticated = False
        self.buffer = bytearray()
        self.last_seen = time.monotonic()
        self.last_sequence = 0
        self.sequence = 0
        self.peer = None
        socket.setParent(self)
        socket.setReadBufferSize(MAX_MESSAGE + 1)
        socket.readyRead.connect(self.read)
        socket.disconnected.connect(self.disconnected)
        if outgoing:
            socket.connected.connect(lambda: self.send(
                "hello", token=token, pid=os.getpid(), request_id=request_id))

    def send(self, kind, **payload):
        if self.socket.state() != QLocalSocket.ConnectedState:
            return
        self.sequence += 1
        data = json.dumps(dict(payload, kind=kind, sequence=self.sequence), ensure_ascii=False).encode("utf-8") + b"\n"
        if len(data) > MAX_MESSAGE or self.socket.bytesToWrite() > MAX_MESSAGE:
            self.socket.abort()
            return
        self.socket.write(data)

    def read(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        if len(self.buffer) > MAX_MESSAGE:
            self.socket.abort()
            return
        # Bounded messages and work per event; never call a peer synchronously.
        while b"\n" in self.buffer:
            raw, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            try:
                message = json.loads(raw)
                sequence = message["sequence"]
                if not isinstance(sequence, int) or sequence <= self.last_sequence:
                    continue
                self.last_sequence = sequence
                if not self.authenticated:
                    if message.get("kind") != "hello" or message.get("token") != self.token:
                        raise ValueError("Invalid IPC handshake")
                    self.authenticated = True
                    if not self.outgoing:
                        self.send("hello", token=self.token, pid=os.getpid())
                    self.bridge.connected(self, message.get("pid"), message.get("request_id"))
                else:
                    self.bridge.received(self, message)
                self.last_seen = time.monotonic()
                if self.peer:
                    self.peer.last_seen = self.last_seen
            except (ValueError, TypeError, KeyError):
                self.socket.abort()
                return

    def disconnected(self):
        if self.peer and self.peer.status != "exited":
            self.peer.status = "disconnected"
            self.peer.channel = None
        self.bridge.report(localize(
            "Workspace connection closed. Reading and editing can continue independently.",
            "작업 창 연결이 끊겼습니다. 읽기와 편집은 각각 계속할 수 있습니다."))


class WorkspaceBridge(QObject):
    copy_finished = pyqtSignal(object, object, object, object)

    def __init__(self, application):
        super().__init__(application)
        self.token = uuid.uuid4().hex
        self.endpoint = "spdf-" + uuid.uuid4().hex
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        if not self.server.listen(self.endpoint):
            raise OSError(self.server.errorString())
        self.server.newConnection.connect(self.accept)
        self.channels = []
        self.children = []
        self.pending = {}
        self.handoffs = {}
        self.seen = []
        self.refreshing = {}
        self.copying = set()
        self.refresh_latest = {}
        self.copy_finished.connect(self.finish_refresh)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def connect_parent(self, endpoint, token, request_id=None):
        socket = QLocalSocket()
        channel = Channel(self, socket, token, outgoing=True, request_id=request_id)
        self.channels.append(channel)
        socket.connectToServer(endpoint)

    def accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            channel = Channel(self, socket, self.token)
            self.channels.append(channel)

    def connected(self, channel, pid, request_id=None):
        for child in self.children:
            request_matches = (isinstance(request_id, str)
                               and child.request.get("request_id") == request_id)
            pid_matches = child.process.pid == pid or child.runtime_pid == pid
            if (request_matches or pid_matches) and child.process.poll() is None:
                if isinstance(pid, int) and pid > 0:
                    child.runtime_pid = pid
                channel.peer = child
                child.channel = channel
                child.status = "connected"
                channel.send("open", **child.request)
                break

    def launch(self, shell, source=None, mode="editor", recovery=False,
               handoff_source=False):
        if source is None:
            source = shell._tabs.currentWidget()
        path = os.path.abspath(source.doc.path) if source is not None and source.doc else None
        state = source.capture_view_state() if path else None
        request = dict(request_id=uuid.uuid4().hex, path=path, view=state, recovery=bool(recovery))
        for child in self.children:
            if (child.mode == mode and child.path == path and child.process.poll() is None
                    and child.status not in ("unresponsive", "disconnected", "exited")):
                if child.channel is not None and child.status in ("opened", "open_failed", "open_timeout"):
                    child.request = request
                    self.pending[request["request_id"]] = time.monotonic()
                    if handoff_source and source is not None and path:
                        self.handoffs[request["request_id"]] = (shell, source)
                    child.channel.send("open", **request)
                return child
        args = process_command(mode, self.endpoint, self.token, request["request_id"])
        if not shell.updates_enabled:
            args.append("--no-updates")
        # Popen is deliberately NOT a Qt child process: closing a window or
        # QApplication must not terminate an editor or wait for its shutdown.
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                   close_fds=True, env=process_environment())
        child = EditorProcess(process, path, mode, request, last_seen=time.monotonic())
        self.children.append(child)
        self.pending[request["request_id"]] = time.monotonic()
        if handoff_source and source is not None and path:
            self.handoffs[request["request_id"]] = (shell, source)
        self.report(localize("Opening a separate workspace process…", "별도 작업 프로세스를 여는 중…"))
        return child

    def received(self, channel, message):
        kind = message.get("kind")
        if kind == "open":
            self.open_requested(channel, message)
        elif kind == "opened":
            request_id = message.get("request_id")
            if request_id not in self.pending:
                return  # Expired or superseded completion.
            del self.pending[request_id]
            handoff = self.handoffs.pop(request_id, None)
            opened = bool(message.get("ok"))
            if channel.peer:
                channel.peer.status = "opened" if opened else "open_failed"
            self.report(localize("Workspace opened.", "작업 창을 열었습니다.") if opened else
                        localize("Document could not be opened in the workspace.", "작업 창에서 문서를 열지 못했습니다."))
            if opened and handoff is not None:
                shell, source = handoff
                QTimer.singleShot(
                    0, lambda owner=shell, tab=source:
                    owner._complete_workspace_handoff(tab))
        elif kind == "saved":
            event = message.get("event")
            path, revision = message.get("path"), message.get("revision")
            if not isinstance(event, str) or event in self.seen or not isinstance(path, str):
                return
            if not isinstance(revision, list) or len(revision) != 4 or not all(isinstance(v, int) for v in revision):
                return
            self.seen = (self.seen + [event])[-256:]
            self.refresh_readers(path, revision)
            for other in self.channels:
                if other is not channel and other.authenticated:
                    other.send("saved", event=event, path=path, revision=revision)

    def open_requested(self, channel, message):
        from .app import _app_windows
        from . import settings
        request_id = message.get("request_id")
        path = message.get("path")
        if not isinstance(request_id, str) or (path is not None and not isinstance(path, str)):
            return
        windows = [w for w in _app_windows if w.workspace_mode is not None]
        if not windows:
            return
        shell = windows[0]
        shell.showNormal() if shell.isMinimized() else shell.show()
        shell.raise_()
        shell.activateWindow()
        if message.get("recovery"):
            QTimer.singleShot(0, shell.show_recovery)
        if not path:
            channel.send("opened", request_id=request_id, ok=True, pid=os.getpid())
            return
        existing = shell._find_open_tab(path)
        tab = shell.open_in_tab(path)
        if existing is not None and existing.doc:
            channel.send("opened", request_id=request_id, ok=True, pid=os.getpid())
            return
        state = settings._clean_reading_position(message.get("view"))
        if state:
            tab._pending_view_state = state
        tab.load_finished.connect(lambda ok: channel.send("opened", request_id=request_id, ok=ok, pid=os.getpid()))

    def saved(self, path, revision):
        event = uuid.uuid4().hex
        self.seen = (self.seen + [event])[-256:]
        self.refresh_readers(path, revision)
        for channel in self.channels:
            if channel.authenticated:
                channel.send("saved", event=event, path=os.path.abspath(path), revision=revision)

    def refresh_readers(self, path, revision):
        from .app import _app_windows
        target = os.path.normcase(os.path.realpath(path))
        for shell in list(_app_windows):
            if shell.workspace_mode != "reader":
                continue
            for index in range(shell._tabs.count()):
                tab = shell._tabs.widget(index)
                if (tab.doc is None or getattr(tab, "_closing_doc", False)
                        or os.path.normcase(os.path.realpath(tab.doc.path)) != target):
                    continue
                if getattr(tab.doc, "_source_revision", None) == revision:
                    continue
                if tab in self.copying:
                    self.refresh_latest[tab] = (path, revision)
                    continue
                token = uuid.uuid4().hex
                self.copying.add(tab)
                self.refreshing[tab] = (token, tab.doc, time.monotonic())
                def copy(tab=tab, token=token, path=path, revision=revision):
                    snapshot = None
                    try:
                        snapshot = DocumentSnapshot(path)
                        if snapshot.revision != revision:
                            raise OSError("Stale save notification")
                        self.copy_finished.emit(tab, token, snapshot, None)
                    except Exception as error:
                        if snapshot:
                            snapshot.close()
                        self.copy_finished.emit(tab, token, None, str(error))
                threading.Thread(target=copy, daemon=True).start()

    def finish_refresh(self, tab, token, snapshot, error):
        from .core import Document
        self.copying.discard(tab)
        latest = self.refresh_latest.pop(tab, None)
        if latest and not getattr(tab, "_closing_doc", False):
            QTimer.singleShot(0, lambda: self.refresh_readers(*latest))
        pending = self.refreshing.get(tab)
        if (pending is None or pending[0] != token or tab.doc is not pending[1]
                or getattr(tab, "_closing_doc", False)):
            if snapshot:
                snapshot.close()
            return
        del self.refreshing[tab]
        if error:
            self.report(localize("Reader refresh skipped; the last good document is still open. ",
                                 "리더 갱신을 건너뛰었습니다. 마지막 정상 문서를 유지합니다. ") + error)
            return
        old = tab.doc
        try:
            if file_revision(old.path) != snapshot.revision:
                snapshot.close()
                return
            document = Document(old.path, old._password, read_only=True,
                                annotations_enabled=False, snapshot=snapshot)
            # Validate what the UI needs while the previous document is intact.
            if document.page_count < 1:
                raise ValueError("Empty document")
            document.bookmarks()
            document.render(min(tab.page_index, document.page_count - 1), 0.1)
        except Exception as exception:
            if "document" in locals():
                document.close()
            else:
                snapshot.close()
            self.report(str(exception))
            return
        state = tab.capture_view_state()  # Capture at completion, not copy start.
        try:
            tab.view.stop_rendering()
            tab._cache.clear()
            tab._reset_textsel()
            tab._reset_annots()
            tab._pending_view_state = state
            tab._set_document(document, old.path)
        except Exception as exception:
            tab._pending_view_state = state
            tab._set_document(old, old.path)
            document.close()
            self.report(str(exception))
        else:
            old.close()

    def tick(self):
        from .document_snapshot import cleanup_snapshots
        cleanup_snapshots()
        now = time.monotonic()
        for channel in list(self.channels):
            if channel.socket.state() == QLocalSocket.UnconnectedState:
                self.channels.remove(channel)
                channel.deleteLater()
                continue
            if not channel.authenticated and now - channel.last_seen > TIMEOUT:
                channel.socket.abort()
            elif channel.authenticated:
                channel.send("heartbeat")
        for child in self.children:
            if child.process.poll() is not None:
                child.status = "exited"
            elif now - child.last_seen > TIMEOUT and child.status not in ("unresponsive", "disconnected"):
                child.status = "unresponsive"
                self.report(localize("The other workspace is not responding. The current window remains available; retry the mode switch to start a new process.",
                                     "다른 작업 창이 응답하지 않습니다. 현재 창은 계속 사용할 수 있으며 모드 전환을 다시 시도하면 새 프로세스로 엽니다."))
        # Retain only a small diagnostic history; dropping old Popen instances
        # also releases their Windows process handles.
        ended = [child for child in self.children if child.status == "exited"]
        self.children = [child for child in self.children if child.status != "exited"] + ended[-16:]
        for request, started in list(self.pending.items()):
            if now - started > TIMEOUT:
                del self.pending[request]
                self.handoffs.pop(request, None)
                for child in self.children:
                    if (child.request.get("request_id") == request and child.status not in
                            ("exited", "disconnected", "unresponsive")):
                        child.status = "open_timeout"
                        self.report(localize("Opening the document timed out. The current window is unchanged; you can retry.",
                                             "문서 열기 시간이 초과되었습니다. 현재 창은 유지되며 다시 시도할 수 있습니다."))
        for tab, (token, doc, started) in list(self.refreshing.items()):
            if now - started > TIMEOUT:
                del self.refreshing[tab]
                self.report(localize("Reader refresh timed out; keeping the last good document.", "리더 갱신 시간이 초과되어 마지막 정상 문서를 유지합니다."))

    @staticmethod
    def report(message):
        from .app import _app_windows
        for shell in _app_windows:
            if shell.workspace_mode is not None:
                tab = shell._tabs.currentWidget()
                (tab or shell).statusBar().showMessage(message, 8000)


def application_bridge():
    application = QApplication.instance()
    bridge = getattr(application, "_spdf_workspace_bridge", None)
    if bridge is None:
        bridge = WorkspaceBridge(application)
        application._spdf_workspace_bridge = bridge
    return bridge
