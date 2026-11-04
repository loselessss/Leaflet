"""Cancellable layout copy job; never load the AI runtime in the Qt process."""
import json
from pathlib import Path
import sys
import tempfile
import time

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, pyqtSignal


class LayoutCopyJob(QObject):
    completed = pyqtSignal(str, str)  # text, error

    def __init__(self, document, page, words=None, parent=None):
        super().__init__(parent)
        self._temporary = tempfile.TemporaryDirectory(prefix="leaflet-layout-")
        self._root = Path(self._temporary.name)
        self._done = False
        self._error = ""
        self._process = QProcess(self)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._process_error)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_limits)
        try:
            pdf = self._root / "page.pdf"
            page = document.write_gpu_page_snapshot(page, str(pdf))
            request = dict(pdf=str(pdf), page=page, words=words)
            (self._root / "request.json").write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8")
        except Exception:
            self._temporary.cleanup()
            raise

    def start(self):
        if self._done:
            return
        # Bypass the Windows venv proxy so cancellation owns the actual PID.
        from .process_workspace import process_python_executable, process_environment
        command = ([sys.executable] if getattr(sys, "frozen", False) else
                   [process_python_executable(), str(Path(__file__).resolve().parents[1] / "run.py")])
        environment = QProcessEnvironment()
        for key, value in process_environment().items():
            environment.insert(key, value)
        environment.insert("PYINSTALLER_RESET_ENVIRONMENT", "1")
        self._process.setProcessEnvironment(environment)
        # Libraries may log during model loading; do not accumulate pipe data.
        self._process.setStandardOutputFile(QProcess.nullDevice())
        self._process.setStandardErrorFile(str(self._root / "error.log"))
        self._started = time.monotonic()
        self._timer.start()
        self._process.start(command[0], command[1:] + ["--pdf-layout-worker",
            str(self._root / "request.json"), str(self._root / "result.json")])

    def cancel(self):
        if self._done:
            return
        self._error = "cancelled"
        self._process.kill()
        if self._process.state() != QProcess.NotRunning:
            self._process.waitForFinished(1000)
        if self._process.state() == QProcess.NotRunning:
            self._finish("", "cancelled")

    def _check_limits(self):
        if time.monotonic() - self._started >= 60:
            self._error = "Analysis timed out (60 s)"
        else:
            try:
                import psutil
                if psutil.Process(int(self._process.processId())).memory_info().rss > 1536 * 1048576:
                    self._error = "Analysis exceeded its memory limit (1.5 GiB)"
            except ImportError:
                pass
            except (OSError, psutil.Error):
                pass
        if self._error:
            self._process.kill()

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._finish("", self._process.errorString())

    def _finished(self, code, status):
        if self._done:
            return
        text, error = "", self._error
        if not error:
            try:
                path = self._root / "result.json"
                if path.stat().st_size > 16 * 1024 * 1024:
                    raise ValueError("Layout result is too large")
                result = json.loads(path.read_text(encoding="utf-8"))
                text, error = result.get("text", ""), result.get("error", "")
                if code != 0 or status != QProcess.NormalExit:
                    error = error or "Layout analysis failed"
            except (OSError, ValueError) as failure:
                error = str(failure)
        self._finish(text, error)

    def _finish(self, text, error):
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self._temporary.cleanup()
        self.completed.emit(text, error)
        self.deleteLater()
