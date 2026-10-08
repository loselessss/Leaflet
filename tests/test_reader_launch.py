"""Real local-socket forwarding, including the GUI-free standalone entry point."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QTimer
from PyQt5.QtNetwork import QLocalServer
from PyQt5.QtWidgets import QApplication

from pdfeditor import reader_launch, settings


class ReaderLaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings_path = str(Path(self.directory.name) / "settings.json")
        self.patcher = patch.object(settings, "PATH", self.settings_path)
        self.patcher.start()
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.UserAccessOption)
        self.assertTrue(self.server.listen(reader_launch.server_name()), self.server.errorString())
        self.peers = []
        self.requests = []

    def tearDown(self):
        for peer in self.peers:
            peer.abort()
        self.server.close()
        self.patcher.stop()
        self.directory.cleanup()

    def run_client(self, code):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        prefix = "from pdfeditor import settings; settings.PATH = %r; " % self.settings_path
        with subprocess.Popen([sys.executable, "-c", prefix + code],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as child:
            deadline = time.monotonic() + 8
            while child.poll() is None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.001)
            if child.poll() is None:
                child.kill()  # Only this test's own isolated client process.
            output, errors = child.communicate()
            self.assertEqual(child.returncode, 0, errors.decode(errors="replace"))
            self.assertEqual(errors, b"")
        return json.loads(output)

    def acknowledge(self, *, fragmented=False):
        def accept():
            peer = self.server.nextPendingConnection()
            self.peers.append(peer)
            buffer = bytearray()
            def consume():
                buffer.extend(bytes(peer.readAll()))
                if b"\n" not in buffer:
                    return
                self.requests.append(json.loads(bytes(buffer).split(b"\n", 1)[0]))
                if fragmented:
                    peer.write(b"O")
                    peer.flush()
                    QTimer.singleShot(10, lambda: peer.write(b"K\n"))
                else:
                    peer.write(b"OK\n")
                    peer.flush()
            peer.readyRead.connect(consume)
            consume()
        self.server.newConnection.connect(accept)

    def test_standalone_forwarding_skips_gui_and_document_imports(self):
        self.acknowledge()
        result = self.run_client(
            "import sys,json; settings.reader_resident=lambda:True; "
            "sys.argv=['Leaflet','sample.pdf','--workspace','reader']; "
            "from pdfeditor.__main__ import main; main(); "
            "print(json.dumps([name for name in "
            "['PyQt5.QtGui','PyQt5.QtWidgets','pdfeditor.app','pdfeditor.theme',"
            "'pdfeditor.reader_resident','pymupdf'] if name in sys.modules]))")
        self.assertEqual(result, [])
        self.assertEqual(self.requests, [{"path": os.path.abspath("sample.pdf")}])

    def test_fragmented_acknowledgment_before_qapplication(self):
        self.acknowledge(fragmented=True)
        self.assertTrue(self.run_client(
            "import json; from pdfeditor.reader_launch import forward_to_resident; "
            "print(json.dumps(forward_to_resident()))"))
        self.assertEqual(self.requests, [{"path": None}])

    def test_missing_resident_allows_normal_qapplication_creation(self):
        self.server.close()
        self.assertEqual(self.run_client(
            "import json; from pdfeditor.reader_launch import forward_to_resident; "
            "forwarded=forward_to_resident(); from PyQt5.QtWidgets import QApplication; "
            "app=QApplication([]); print(json.dumps([forwarded, app is QApplication.instance()]))"),
            [False, True])

    def test_oversized_request_does_not_connect(self):
        with patch.object(reader_launch, "QLocalSocket", side_effect=AssertionError("Must not connect")):
            self.assertFalse(reader_launch.forward_to_resident("x" * reader_launch.MAX_REQUEST_BYTES))
