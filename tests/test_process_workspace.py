import gc
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import fitz
from PyQt5.QtCore import QCoreApplication, QEvent, QTimer
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from pdfeditor import app, settings
from pdfeditor.process_workspace import (EditorProcess, WorkspaceBridge,
                                         process_environment, process_python_executable)


class ProcessIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        # Release test-owned QObject cycles while QApplication is still alive,
        # not during Python's unordered interpreter shutdown.
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        cls.application.processEvents()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "source.pdf"
        with fitz.open() as pdf:
            for index in range(3):
                pdf.new_page(width=280, height=400).insert_text((40, 60), "Reader page %s" % index)
            pdf.save(self.path)
        self.original = self.path.read_bytes()
        self._reports = {}
        self.bridge = WorkspaceBridge(self.application)
        self.patchers = [patch.object(app, "_app_windows", []),
                         patch.object(settings, "PATH", str(self.root / "settings.json")),
                         patch.object(settings, "_OLD_PATH", str(self.root / "absent")),
                         patch.object(self.application, "_spdf_workspace_bridge", self.bridge, create=True),
                         patch.dict(os.environ, {"SPDF_PROCESS_TEST_DIR": str(self.root)}),
                         patch("pdfeditor.process_workspace.process_command", self.command)]
        for patcher in self.patchers:
            patcher.start()
        self.reader = app.new_window(str(self.path), workspace_mode="reader")
        self.wait(lambda: self.reader._tabs.currentWidget().doc is not None)
        self.tab = self.reader._tabs.currentWidget()
        self.sequence = 0
        self.ticks = 0
        self.timer = QTimer()
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.count_tick)
        self.timer.start()

    def count_tick(self):
        self.ticks += 1

    def command(self, mode, endpoint, token, request_id):
        return [process_python_executable(), str(Path(__file__).with_name("workspace_process_fixture.py")),
                "--workspace", mode, "--peer", endpoint, "--peer-token", token,
                "--peer-request", request_id]

    def tearDown(self):
        self.timer.stop()
        # ONLY Popen handles created by this test are ever terminated.
        for child in self.bridge.children:
            if child.process.poll() is None:
                child.process.kill()
            child.process.wait(timeout=10)
        self.bridge.timer.stop()
        for channel in list(self.bridge.channels):
            channel.socket.abort()
        self.bridge.server.close()
        for window in list(app._app_windows):
            window.close()
        QTest.qWait(50)
        self.bridge.deleteLater()
        QTest.qWait(10)
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.directory.cleanup()

    def wait(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QTest.qWait(20)
            if predicate():
                return
        failures = []
        for child in self.bridge.children:
            log = self.root / str(child.pid) / "failure.log"
            failures.append((child.pid, child.status, child.process.poll(),
                             self.report(child), log.read_text() if log.exists() else ""))
        self.fail("Timed out waiting for test-owned workspace: %r" % failures)

    def report(self, child):
        path = self.root / str(child.pid) / "report.json"
        if not path.exists() and child.runtime_pid is None:
            # A Windows venv launcher may be a proxy whose PID differs from
            # the real Python GUI process.  Find the unclaimed authenticated
            # fixture report so direct-process tests observe the real owner.
            claimed = {item.runtime_pid for item in self.bridge.children
                       if item is not child and item.runtime_pid is not None}
            candidates = []
            for report_path in self.root.glob("[0-9]*/report.json"):
                try:
                    pid = int(report_path.parent.name)
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if pid not in claimed and report.get("pid") == pid:
                    candidates.append((report_path.stat().st_mtime_ns, pid, report))
            if candidates:
                _, child.runtime_pid, report = max(candidates)
                self._reports[child.pid] = report
                return report
            path = self.root / str(child.pid) / "report.json"
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if child.runtime_pid is None and report.get("pid") == child.process.pid:
                child.runtime_pid = report["pid"]
            self._reports[child.pid] = report
            return report
        except (OSError, ValueError):
            # A Windows atomic replace may briefly deny the observer a handle.
            # Keep the last complete report; command IDs still require a fresh
            # acknowledgement before a test can move on.
            return self._reports.get(child.pid, {})

    def send(self, child, op, wait=True, **extra):
        self.sequence += 1
        data = dict(extra, op=op, id=self.sequence)
        path = self.root / str(child.pid) / "command.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, path)
        if wait:
            self.wait(lambda: self.report(child).get("command") == self.sequence)
        return self.report(child)

    def launch(self):
        child = self.bridge.launch(self.reader, self.tab)
        self.assertNotEqual(child.pid, os.getpid())
        self.wait(lambda: child.status == "opened" and self.report(child).get("document"))
        report = self.report(child)
        self.assertEqual(report["mode"], "editor")
        self.assertFalse(report["overview"])
        self.assertFalse(report["updates"])
        print("Process isolation: reader PID=%s, editor PID=%s" % (os.getpid(), child.pid), flush=True)
        self.assertIs(self.bridge.launch(self.reader, self.tab), child)
        return child

    def test_mode_handoff_closes_source_reader_after_editor_is_ready(self):
        child = self.reader.open_editor(self.tab)
        self.wait(lambda: child.status == "opened" and self.report(child).get("document"))
        self.wait(lambda: self.reader not in app._app_windows)
        self.assertEqual(self.reader._tabs.count(), 0)
        self.assertFalse(self.reader.isVisible())
        self.assertEqual(self.report(child)["mode"], "editor")

    def direct_process(self, mode=None, parent=None):
        args = [process_python_executable(), str(Path(__file__).with_name("workspace_process_fixture.py")),
                str(self.path), "--no-updates"]
        if mode:
            args += ["--workspace", mode]
        if parent:
            info = self.report(parent)
            args += ["--peer", info["endpoint"], "--peer-token", info["token"]]
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                   env=process_environment())
        child = EditorProcess(process, str(self.path), mode, {}, status="disconnected")
        self.bridge.children.append(child)  # Keep every test-owned handle for cleanup.
        self.wait(lambda: self.report(child).get("document"))
        return child

    def assert_reader_usable(self):
        before = self.ticks
        self.tab.show_page(2)
        self.tab.set_zoom(1.75)
        self.tab._render_current()
        self.tab.search_start("Reader")
        QTest.qWait(60)
        self.assertGreater(self.ticks, before)
        self.assertEqual(self.tab.view.zoom, 1.75)
        self.assertTrue(self.tab.doc.search(2, "Reader"))
        from PyQt5.QtPrintSupport import QPrinter
        printer = self.tab._new_printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        output = self.root / "print-output.pdf"
        printer.setOutputFileName(str(output))
        self.tab._paint_document(printer, show_progress=False)
        with fitz.open(output) as printed:
            self.assertEqual(printed.page_count, 3)
        self.assertTrue(self.tab.doc.render(2, 0.3)[3])

    def test_real_pids_normal_exit_kill_crash_hang_and_restart(self):
        for failure in ("close", "kill", "crash", "hang"):
            with self.subTest(failure=failure):
                child = self.launch()
                if failure == "kill":
                    child.process.kill()
                else:
                    self.send(child, failure, wait=False)
                if failure == "hang":
                    self.wait(lambda: self.report(child).get("phase") == "hang")
                    with patch("pdfeditor.process_workspace.TIMEOUT", 0.15):
                        QTest.qWait(250)
                        self.bridge.tick()
                    self.assertEqual(child.status, "unresponsive")
                else:
                    self.wait(lambda: child.process.poll() is not None)
                    if failure == "close":
                        self.assertEqual(child.process.returncode, 0)
                    if failure == "crash":
                        self.assertNotEqual(child.process.returncode, 0)
                        print("Test editor native-crash exit=%s" % child.process.returncode, flush=True)
                        self.assertIn("access violation", (self.root / str(child.pid) / "failure.log").read_text())
                self.assert_reader_usable()
                if failure == "hang":
                    restarted = self.launch()
                    self.assertNotEqual(restarted.pid, child.pid)
                    child.process.kill()
                    restarted.process.kill()
                    restarted.process.wait(timeout=10)
                child.process.wait(timeout=10)
                self.assertEqual(self.path.read_bytes(), self.original)

    def test_normal_save_refreshes_view_and_save_as_keeps_original_reader(self):
        self.tab.show_page(1)
        self.tab.set_zoom(2)
        self.tab._render_current()
        QTest.qWait(50)
        self.tab.view.verticalScrollBar().setValue(100)
        state = self.tab.capture_view_state()
        child = self.launch()
        self.assertEqual(self.report(child)["page"], 1)
        self.send(child, "edit")
        self.assertTrue(self.send(child, "save")["result"]["saved"])
        self.wait(lambda: "Process edit" in self.tab.doc._doc[1].get_text())
        self.assertEqual(self.tab.page_index, state["page"])
        self.assertEqual(self.tab.view.zoom, state["zoom"])
        self.assertAlmostEqual(self.tab.capture_view_state()["vertical"], state["vertical"], places=2)
        self.assertFalse(Path(str(self.path) + ".bak").exists())
        self.send(child, "save_as")
        self.assertEqual(self.tab.doc.path, str(self.path))
        self.assertTrue((self.root / "copy.pdf").exists())
        self.assert_reader_usable()

    def test_open_failure_can_retry_in_same_process(self):
        self.path.unlink()  # The reader already owns a complete private copy.
        child = self.reader.open_editor(self.tab)
        self.wait(lambda: child.status == "open_failed")
        self.assert_reader_usable()
        self.assertIn(self.reader, app._app_windows)
        self.path.write_bytes(self.original)
        self.assertIs(self.bridge.launch(self.reader, self.tab), child)
        self.wait(lambda: child.status == "opened" and self.report(child).get("document"))
        self.assert_reader_usable()

    def test_interrupt_each_save_boundary_keeps_reader_and_valid_original(self):
        for phase in ("before_save", "writer_lock", "before_replace", "after_replace"):
            with self.subTest(phase=phase):
                child = self.launch()
                self.send(child, "edit")
                self.send(child, "save_phase", wait=False, phase=phase)
                self.wait(lambda: self.report(child).get("phase") == phase)
                self.assert_reader_usable()
                child.process.kill()
                child.process.wait(timeout=10)
                self.assert_reader_usable()
                self.assertNotIn("Process edit", self.tab.doc._doc[1].get_text())
                if phase == "after_replace":
                    with fitz.open(self.path) as saved:
                        self.assertIn("Process edit", saved[1].get_text())
                    self.assertEqual(Path(str(self.path) + ".bak").read_bytes(), self.original)
                else:
                    self.assertEqual(self.path.read_bytes(), self.original)
        child = self.launch()
        self.send(child, "save")
        self.wait(lambda: "Process edit" in self.tab.doc._doc[1].get_text())

    def test_editor_survives_reader_close_and_recovery_is_independent(self):
        child = self.launch()
        self.send(child, "edit")
        self.reader.close()
        self.send(child, "checkpoint")
        session = self.report(child)["recovery_session"]
        self.wait(lambda: bool(list(Path(session).glob("*.recovery"))))
        self.assertIsNone(child.process.poll())
        child.process.kill()
        child.process.wait(timeout=10)
        from pdfeditor.recovery import RecoveryStore
        store = RecoveryStore(self.root / "recovery")
        try:
            entries = store.available()
            self.assertEqual(len(entries), 1)
            with fitz.open("pdf", store.read(entries[0])) as recovered:
                self.assertIn("Process edit", recovered[1].get_text())
            self.assertEqual(self.path.read_bytes(), self.original)
        finally:
            for lock in store._locks.values():
                lock.unlock()

    def test_stale_notification_and_failed_refresh_keep_last_document(self):
        document = self.tab.doc
        self.bridge.refresh_readers(str(self.path), [0, 0, 0, 0])
        self.wait(lambda: not self.bridge.refreshing)
        self.assertIs(self.tab.doc, document)
        self.path.write_bytes(b"not a PDF")
        from pdfeditor.document_snapshot import file_revision
        self.bridge.refresh_readers(str(self.path), file_revision(self.path))
        self.wait(lambda: not self.bridge.refreshing)
        self.assertIs(self.tab.doc, document)
        self.assert_reader_usable()

    def test_editor_first_and_real_reader_process_death_do_not_own_recovery(self):
        settings.set_startup_workspace("editor")
        editor = self.direct_process()  # Exercise the persisted startup setting.
        self.assertEqual(self.report(editor)["mode"], "editor")
        reader = self.direct_process("reader", parent=editor)
        self.assertNotEqual(reader.pid, editor.pid)
        self.assertFalse(self.report(reader)["organizer_loaded"])
        self.assertFalse(self.report(reader)["editor_dialog_loaded"])
        self.send(editor, "edit")
        self.send(editor, "save")
        self.wait(lambda: "Process edit" in self.report(reader).get("text", ""))
        reader.process.kill()
        reader.process.wait(timeout=10)
        self.send(editor, "edit")
        self.send(editor, "checkpoint")
        session = self.report(editor)["recovery_session"]
        self.wait(lambda: bool(list(Path(session).glob("*.recovery"))))
        self.assertIsNone(editor.process.poll())
        editor.process.kill()
        editor.process.wait(timeout=10)
        from pdfeditor.recovery import RecoveryStore
        store = RecoveryStore(self.root / "recovery")
        try:
            entries = store.available()
            self.assertEqual(len(entries), 1)
            with fitz.open("pdf", store.read(entries[0])) as recovered:
                self.assertEqual(recovered[1].get_text().count("Process edit"), 2)
            with fitz.open(self.path) as saved:
                self.assertEqual(saved[1].get_text().count("Process edit"), 1)
        finally:
            for lock in store._locks.values():
                lock.unlock()

    def test_copy_timeout_and_late_completion_do_not_replace_reader(self):
        from pdfeditor.document_snapshot import DocumentSnapshot, file_revision
        old = self.tab.doc
        # A new committed version, held by a deliberately delayed copy worker.
        temporary = self.root / "updated.pdf"
        with fitz.open(self.path) as pdf:
            pdf[1].insert_text((40, 100), "Delayed")
            pdf.save(temporary)
        os.replace(temporary, self.path)
        started, resume = threading.Event(), threading.Event()
        def delayed(path):
            started.set()
            resume.wait(5)
            return DocumentSnapshot(path)
        try:
            with patch("pdfeditor.process_workspace.DocumentSnapshot", side_effect=delayed) as copier:
                self.bridge.refresh_readers(str(self.path), file_revision(self.path))
                self.wait(started.is_set)
                with patch("pdfeditor.process_workspace.TIMEOUT", 0.01):
                    QTest.qWait(30)
                    self.bridge.tick()
                self.assertIs(self.tab.doc, old)
                self.assert_reader_usable()
                resume.set()
                self.wait(lambda: not self.bridge.copying)
                self.assertEqual(copier.call_count, 1)
            self.assertIs(self.tab.doc, old)
        finally:
            resume.set()

    def test_ipc_rejects_unauthenticated_oversized_and_stale_messages(self):
        from PyQt5.QtNetwork import QLocalSocket
        def connect():
            socket = QLocalSocket()
            socket.connectToServer(self.bridge.endpoint)
            self.wait(lambda: socket.state() == QLocalSocket.ConnectedState)
            return socket
        socket = connect()
        socket.write(b'{"sequence":1,"kind":"hello","token":"wrong"}\n')
        self.wait(lambda: socket.state() == QLocalSocket.UnconnectedState)
        socket = connect()
        socket.write(b'x' * 65537)
        self.wait(lambda: socket.state() == QLocalSocket.UnconnectedState)
        socket = connect()
        hello = dict(sequence=1, kind="hello", token=self.bridge.token, pid=os.getpid())
        socket.write(json.dumps(hello).encode() + b'\n')
        self.wait(lambda: any(c.authenticated for c in self.bridge.channels))
        saved = dict(sequence=2, kind="saved", path=str(self.path), revision=[1, 2, 3, 4], event="event-one")
        with patch.object(self.bridge, "refresh_readers") as refresh:
            socket.write(json.dumps(saved).encode() + b'\n')
            self.wait(lambda: refresh.call_count == 1)
            saved["event"] = "stale-sequence"
            socket.write(json.dumps(saved).encode() + b'\n')
            QTest.qWait(50)
            self.assertEqual(refresh.call_count, 1)
        socket.abort()
        self.assert_reader_usable()


if __name__ == "__main__":
    unittest.main()
