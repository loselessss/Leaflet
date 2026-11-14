"""Visible-first, bounded RAM previews; PDF work never runs on the GUI thread."""
import base64
from collections import OrderedDict
from functools import partial
import json
import os
from pathlib import Path
import sys
import tempfile

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal
from PyQt5.QtGui import QImage

from .home_preview_worker import MAX_EDGE, MAX_HEIGHT, MAX_REPLY


def _cleanup_directory(resources):
    temporary = resources.get("temporary")
    if temporary is not None:
        try:
            temporary.cleanup()
        except OSError:
            return
        resources["temporary"] = None


def _dispose_worker(process, resources, *_args):
    process.kill()
    if process.state() != QProcess.NotRunning:
        process.waitForFinished(1000)
    _cleanup_directory(resources)


class HomePreviews(QObject):
    changed = pyqtSignal()
    MAX_BYTES = 16 * 1024 * 1024
    MAX_ENTRIES = 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache = OrderedDict()
        self._retained = None
        self._bytes = 0
        self._pending = []
        self._active = None
        self._stopping = False
        self._buffer = bytearray()
        self._resources = {"temporary": None}
        self._process = QProcess(self)
        self._process.setStandardErrorFile(QProcess.nullDevice())
        self._process.started.connect(self._send)
        self._process.readyReadStandardOutput.connect(self._read)
        self._process.finished.connect(self._exited)
        self._process.errorOccurred.connect(self._error)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._timeout)
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(500)
        self._watchdog.timeout.connect(self._check_memory)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self.stop)
        self.destroyed.connect(partial(_dispose_worker, self._process, self._resources))

    def lookup(self, path):
        entry = self._cache.get(path)
        if entry is None:
            return None, "pending"
        self._cache.move_to_end(path)
        return entry[1], entry[2]

    @staticmethod
    def _revision(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size
        except OSError:
            return None

    def request(self, paths):
        # Replace the queue on every scroll: off-screen files do not build up.
        pending = []
        for path in dict.fromkeys(paths):
            revision = self._revision(path)
            entry = self._cache.get(path)
            if entry is not None and entry[0] == revision:
                continue
            if entry is not None:
                self._discard(path)
            key = (path, revision)
            if key != self._active:
                pending.append(key)
        self._pending = pending
        self._start_next()

    def retain(self, paths):
        self._retained = set(paths)
        for path in list(self._cache):
            if path not in self._retained:
                self._discard(path)
        self._pending = [key for key in self._pending if key[0] in self._retained]

    def _start_next(self):
        if self._active is not None or self._stopping:
            return
        if not self._pending:
            self._idle.start(5000)
            return
        self._idle.stop()
        self._active = self._pending.pop(0)
        self._buffer.clear()
        self._deadline.start(15000)
        self._watchdog.start()
        if self._process.state() == QProcess.NotRunning:
            if self._resources["temporary"] is None:
                try:
                    self._resources["temporary"] = tempfile.TemporaryDirectory(prefix="leaflet-home-")
                except OSError:
                    self._complete(None, "unavailable")
                    return
            from .process_workspace import process_environment, process_python_executable
            environment = QProcessEnvironment()
            for key, value in process_environment().items():
                environment.insert(key, value)
            environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
            self._process.setProcessEnvironment(environment)
            command = ([sys.executable] if getattr(sys, "frozen", False) else
                       [process_python_executable(), str(Path(__file__).resolve().parents[1] / "run.py")])
            self._process.start(command[0], command[1:] + ["--home-preview-worker",
                                self._resources["temporary"].name])
        elif self._process.state() == QProcess.Running:
            self._send()

    def _send(self):
        if self._active:
            self._process.write((json.dumps({"path": self._active[0]}) + "\n").encode())

    def _read(self):
        self._buffer.extend(bytes(self._process.readAllStandardOutput()))
        if len(self._buffer) > MAX_REPLY:
            self._timeout()
            return
        if b"\n" not in self._buffer or self._active is None:
            return
        image, status = None, "unavailable"
        try:
            result = json.loads(bytes(self._buffer))
            status = result["status"]
            if status == "ready":
                image = QImage.fromData(base64.b64decode(result["png"], validate=True), "PNG")
                if image.isNull() or image.width() > MAX_EDGE + 1 or image.height() > MAX_HEIGHT + 1:
                    raise ValueError("Invalid home preview")
            elif status not in ("locked", "unavailable"):
                raise ValueError("Invalid home preview status")
        except (ValueError, KeyError, TypeError):
            image, status = None, "unavailable"
        self._complete(image, status)

    def _discard(self, path):
        old = self._cache.pop(path, None)
        if old and old[1] is not None:
            self._bytes -= old[1].sizeInBytes()

    def _complete(self, image, status):
        self._deadline.stop()
        self._watchdog.stop()
        if self._active is None:
            return
        path, revision = self._active
        self._active = None
        self._buffer.clear()
        self._discard(path)
        if self._retained is None or path in self._retained:
            self._cache[path] = (revision, image, status)
            if image is not None:
                self._bytes += image.sizeInBytes()
        while self._bytes > self.MAX_BYTES or len(self._cache) > self.MAX_ENTRIES:
            self._discard(next(iter(self._cache)))
        self.changed.emit()
        QTimer.singleShot(0, self._start_next)

    def _timeout(self):
        # Wait for process exit before dispatching the next request.
        self._process.kill()

    def _check_memory(self):
        pid = int(self._process.processId())
        if not pid:
            return
        try:
            import psutil
            if psutil.Process(pid).memory_info().rss > 512 * 1024 * 1024:
                self._timeout()
        except (ImportError, OSError):
            pass
        except psutil.Error:
            pass

    def _error(self, error):
        if error == QProcess.FailedToStart:
            self._exited()

    def _exited(self, *_args):
        self._stopping = False
        self._deadline.stop()
        self._watchdog.stop()
        self._buffer.clear()
        _cleanup_directory(self._resources)
        if self._active:
            self._complete(None, "unavailable")
        elif self._pending:
            QTimer.singleShot(0, self._start_next)

    def stop(self):
        self._pending.clear()
        self._active = None
        self._buffer.clear()
        self._deadline.stop()
        self._watchdog.stop()
        self._idle.stop()
        self._stopping = self._process.state() != QProcess.NotRunning
        self._process.kill()
        if not self._stopping:
            _cleanup_directory(self._resources)
