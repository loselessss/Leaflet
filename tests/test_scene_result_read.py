"""Background result ownership, GUI responsiveness, cancellation and staleness."""
from pathlib import Path
import pickle
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch, PropertyMock

from pdfeditor import scene_worker_result as results
from pdfeditor.gpu_raster import VectorPage
from tests import test_reader_view as fixtures


def wait_ready(reader):
    deadline = time.monotonic() + 5
    while not reader.done() and time.monotonic() < deadline:
        time.sleep(.001)
    if not reader.done():
        raise AssertionError('background result did not finish')


class SceneResultReadTests(unittest.TestCase):
    def test_cancelled_queued_read_skips_decode_and_releases_files(self):
        with tempfile.TemporaryDirectory() as directory:
            directories = [Path(directory)/str(i) for i in range(2)]
            for path in directories:
                path.mkdir()
                (path/'result').write_bytes(b'private input')
            entered, release = threading.Event(), threading.Event()
            def blocked(_stream):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test release timed out')
                return VectorPage(True)
            with patch.object(results, 'load', side_effect=blocked) as decode:
                first = results.SceneResultRead(str(directories[0]/'result'), str(directories[0]))
                try:
                    self.assertTrue(entered.wait(2))
                    second = results.SceneResultRead(str(directories[1]/'result'), str(directories[1]))
                    second.cancel()
                    self.assertFalse(second.done())
                finally:
                    release.set()
                    wait_ready(first)
                wait_ready(second)
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(second.take(), (None, None))
                self.assertFalse(any(path.exists() for path in directories))
                self.assertEqual(first.take(), (VectorPage(True), None))
                self.assertEqual(first.take(), (None, None))


class ReaderResultHandoffTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ReaderViewTests.setUpClass.__func__)
    setUp = fixtures.ReaderViewTests.setUp
    tearDown = fixtures.ReaderViewTests.tearDown
    finish_worker_result = fixtures.ReaderViewTests.finish_worker_result
    finish_tiles = fixtures.ReaderViewTests.finish_tiles

    def make_job(self):
        directory = tempfile.mkdtemp(dir=self.directory.name)
        result = Path(directory)/'result.scene'
        result.write_bytes(pickle.dumps(VectorPage(True)))
        self.view._vector_refine_process = Mock(returncode=0, poll=Mock(return_value=0))
        job = dict(document=self.doc, generation=self.doc.render_generation, page=0,
            scale=self.view._vector_raster_scale(), directory=directory, result=str(result))
        self.view._vector_refine_job = job
        return job

    def test_decode_runs_off_gui_thread_and_gui_timer_keeps_running(self):
        from PyQt5.QtCore import QTimer
        job = self.make_job()
        entered, release = threading.Event(), threading.Event()
        threads, beats = [], []
        original = results.load
        def blocked(stream):
            threads.append(threading.get_ident())
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timed out')
            return original(stream)
        with patch.object(results, 'load', side_effect=blocked):
            self.view._poll_vector_refine_worker()
            reader = job['result_reader']
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(reader.done())
                QTimer.singleShot(0, lambda: beats.append(threading.get_ident()))
                self.app.processEvents()
                self.assertEqual(beats, [threading.get_ident()])
                self.assertNotEqual(threads, beats)
                self.assertIs(self.view._vector_refine_job, job)
            finally:
                release.set()
                self.finish_worker_result()
            self.assertTrue(self.view._vector_pages[0].supported)

    def test_close_during_decode_cancels_without_waiting_or_installing(self):
        job = self.make_job()
        entered, release = threading.Event(), threading.Event()
        def blocked(_stream):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timed out')
            return VectorPage(True)
        with patch.object(results, 'load', side_effect=blocked), \
                patch.object(self.doc, 'install_gpu_vector_page') as install:
            self.view._poll_vector_refine_worker()
            reader = job['result_reader']
            try:
                self.assertTrue(entered.wait(2))
                self.view.clear()
                self.doc.close()
                self.assertIsNone(self.view._vector_refine_job)
                self.assertFalse(reader.done())  # clear did not wait for the read.
            finally:
                release.set()
                wait_ready(reader)
            self.view._poll_vector_refine_worker()
            install.assert_not_called()
            self.assertEqual(reader.take(), (None, None))
            self.assertFalse(Path(job['directory']).exists())

    def test_revision_changed_during_decode_rejects_the_result(self):
        job = self.make_job()
        original = VectorPage(False, reason='GPU scene awaiting first frame')
        self.view._vector_pages[0] = original
        entered, release = threading.Event(), threading.Event()
        def blocked(_stream):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timed out')
            return VectorPage(True)
        with patch.object(results, 'load', side_effect=blocked), \
                patch.object(self.doc, 'install_gpu_vector_page') as install:
            self.view._poll_vector_refine_worker()
            try:
                self.assertTrue(entered.wait(2))
                self.doc.invalidate_render(0)
            finally:
                release.set()
                self.finish_worker_result()
            install.assert_not_called()
            self.assertIs(self.view._vector_pages[0], original)

    def test_reader_start_failure_becomes_specific_cpu_fallback(self):
        job = self.make_job()
        self.view._vector_pages[0] = VectorPage(False, reason='GPU scene awaiting first frame')
        with patch.object(results._executor, 'submit', side_effect=RuntimeError('thread unavailable')):
            self.finish_worker_result()
        self.assertEqual(self.view._vector_pages[0].reason,
            'GPU scene result reader could not start: thread unavailable')
        self.assertFalse(Path(job['directory']).exists())

    def test_cpu_tile_consumer_does_not_request_python_pixel_bytes(self):
        import pymupdf
        errors = []
        self.view.render_failed.connect(errors.append)
        with patch.object(pymupdf.Pixmap, 'samples', new_callable=PropertyMock,
                          side_effect=AssertionError('unexpected CPU tile bytes copy')):
            self.finish_tiles()
        self.assertTrue(self.view._tiles)
        self.assertEqual(errors, [])
