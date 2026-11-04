import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from pdfeditor.layout_text import text_in_layout_order


def word(text, x, y, block=0, line=0, number=0):
    return (x, y, x + 15, y + 10, text, block, line, number)


class LayoutOrderTests(unittest.TestCase):
    def test_columns_overlap_and_unassigned_preserve_every_original_word(self):
        words = [word("R1", 210, 10, 0), word("L2", 10, 40, 1),
                 word("L1", 10, 10, 1, 1), word("R2", 210, 40, 0, 1),
                 word("foot", 10, 300, 2)]
        regions = [(0, 0, 100, 100, "text"), (200, 0, 300, 100, "text"),
                   (0, 0, 400, 200, "picture")]
        text = text_in_layout_order(words, regions)
        self.assertEqual(text, "L1 L2\n\nR1 R2\n\nfoot")
        self.assertCountEqual(text.split(), [w[4] for w in words])

    def test_selection_and_empty_layout(self):
        words = [word("only", 20, 40), word("selected", 40, 40, number=1)]
        self.assertEqual(text_in_layout_order(words, []), "only selected")


class LayoutJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def document(self, root, *, rotation=0, encrypted=False):
        import pymupdf
        path = Path(root) / "source.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), "Selected sentence.")
            page.insert_text((72, 120), "Leave this paragraph alone.")
            page.set_rotation(rotation)
            if encrypted:
                pdf.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                         owner_pw="owner", user_pw="", permissions=pymupdf.PDF_PERM_PRINT)
            else:
                pdf.save(path)
        return path

    def test_real_headless_worker_selected_words_and_rotated_page(self):
        import pymupdf
        from PyQt5.QtCore import QEventLoop, QTimer
        from pdfeditor.core import Document
        from pdfeditor.layout_copy import LayoutCopyJob
        with tempfile.TemporaryDirectory() as directory:
            path = self.document(directory, rotation=90)
            document = Document(str(path))
            try:
                selected = [w for w in document.words(0) if w[1] < 90]
                loop, result = QEventLoop(), []
                job = LayoutCopyJob(document, 0, selected)
                root = job._root
                job.completed.connect(lambda text, error: (result.append((text, error)), loop.quit()))
                guard = QTimer()
                guard.setSingleShot(True)
                guard.timeout.connect(loop.quit)
                guard.start(65000)
                job.start()
                loop.exec_()
                guard.stop()
                if not result:
                    job.cancel()
                self.assertTrue(result, "layout worker did not finish")
                self.assertEqual(result, [("Selected sentence.", "")])
                self.assertFalse(root.exists(), "worker files leaked after completion")
                self.assertNotIn("pymupdf.layout", sys.modules)
                self.assertNotIn("onnxruntime", sys.modules)
            finally:
                document.close()

    def test_cancel_before_start_cleans_input_and_never_copies(self):
        from pdfeditor.core import Document
        from pdfeditor.layout_copy import LayoutCopyJob
        with tempfile.TemporaryDirectory() as directory:
            document = Document(str(self.document(directory)))
            try:
                job = LayoutCopyJob(document, 0)
                result = []
                job.completed.connect(lambda *args: result.append(args))
                root = job._root
                job.cancel()
                self.assertEqual(result, [("", "cancelled")])
                self.assertFalse(root.exists())
            finally:
                document.close()

    def test_ui_drops_stale_results_and_cancels_on_document_reset(self):
        from PyQt5.QtCore import QObject, pyqtSignal
        from PyQt5.QtWidgets import QWidget, QApplication
        from pdfeditor.textsel import TextSelectMixin

        class Job(QObject):
            completed = pyqtSignal(str, str)

            def __init__(self, document, page, words, parent):
                super().__init__(parent)
                self.cancel = Mock()

            def start(self):
                pass

        class Host(TextSelectMixin, QWidget):
            def statusBar(self):
                return Mock()

        host = Host()
        host._init_textsel_state()
        host.doc = Mock(render_generation=1)
        host.doc._doc.permissions = -1
        host.page_index = 0
        host._selected = [word("chosen", 1, 1)]
        host._closing_doc = False
        QApplication.clipboard().setText("original")
        try:
            with patch("pdfeditor.layout_copy.LayoutCopyJob", Job):
                host.copy_in_reading_order()
                job = host._layout_copy_job
                host.doc.render_generation = 2
                job.completed.emit("stale", "")
                self.assertEqual(QApplication.clipboard().text(), "original")
                host.copy_in_reading_order()
                job = host._layout_copy_job
                host._reset_textsel()
                job.cancel.assert_called_once()
                job.completed.emit("cancelled late result", "")
                self.assertEqual(QApplication.clipboard().text(), "original")
        finally:
            host._cancel_layout_copy()
            host.close()

    def test_copy_permission_checked_before_snapshot(self):
        from pdfeditor.core import Document
        from pdfeditor.textsel import TextSelectMixin
        with tempfile.TemporaryDirectory() as directory:
            document = Document(str(self.document(directory, encrypted=True)))
            try:
                host = Mock(doc=document, _closing_doc=False)
                with patch.object(document, "write_gpu_page_snapshot") as snapshot:
                    TextSelectMixin.copy_in_reading_order(host)
                snapshot.assert_not_called()
                host.statusBar().showMessage.assert_called_once()
            finally:
                document.close()

    def test_running_worker_cancel_terminates_process_and_removes_snapshot(self):
        from PyQt5.QtCore import QEventLoop, QProcess, QTimer
        from pdfeditor.core import Document
        from pdfeditor.layout_copy import LayoutCopyJob
        with tempfile.TemporaryDirectory() as directory:
            document = Document(str(self.document(directory)))
            try:
                job = LayoutCopyJob(document, 0)
                root, result, loop = job._root, [], QEventLoop()
                job.completed.connect(lambda *args: (result.append(args), loop.quit()))
                job._process.started.connect(lambda: QTimer.singleShot(50, job.cancel))
                guard = QTimer()
                guard.setSingleShot(True)
                guard.timeout.connect(loop.quit)
                guard.start(10000)
                job.start()
                loop.exec_()
                guard.stop()
                self.assertEqual(result, [("", "cancelled")])
                self.assertEqual(job._process.state(), QProcess.NotRunning)
                self.assertFalse(root.exists())
            finally:
                document.close()

    def test_worker_entry_is_headless_and_plain_read_does_not_load_models(self):
        code = ('import pymupdf,sys; d=pymupdf.open(); p=d.new_page(); '
                'p.get_text(); p.get_pixmap(); '
                'assert "onnxruntime" not in sys.modules; '
                'assert "pymupdf.layout" not in sys.modules')
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, timeout=30)
        with tempfile.TemporaryDirectory() as directory:
            request, result = Path(directory) / "request.json", Path(directory) / "result.json"
            request.write_text(json.dumps(dict(pdf="missing.pdf", page=0)), encoding="utf-8")
            code = ('import sys; from pdfeditor.__main__ import main; '
                    'sys.argv=["leaflet","--pdf-layout-worker",*sys.argv[1:]]; '
                    '\ntry: main()\nfinally: assert "PyQt5.QtCore" not in sys.modules')
            process = subprocess.run([sys.executable, "-c", code, str(request), str(result)],
                                     capture_output=True, timeout=30)
            self.assertEqual(process.returncode, 1, process.stderr.decode(errors="replace"))
            self.assertIn("error", json.loads(result.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
