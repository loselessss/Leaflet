import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import pymupdf
from pdfeditor.core import Document
from pdfeditor import file_digest, scene_disk_cache


class FileDigestTests(unittest.TestCase):
    def test_streamed_digest_matches_whole_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data"
            data = b"large-file-block" * 200000
            path.write_bytes(data)
            job = file_digest.FileDigest(path, file_digest.revision(path.stat()))
            self.assertEqual(job.future.result(timeout=5), hashlib.sha256(data).hexdigest())
            self.assertEqual(job.value(), hashlib.sha256(data).hexdigest())

    def test_cache_lookup_does_not_wait_and_reuses_one_job(self):
        entered, release = threading.Event(), threading.Event()
        original = file_digest._hash_file
        def slow_hash(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Cache lookup blocked on hashing")
            return original(*args)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.save(path)
            doc = Document(str(path))
            try:
                with patch.object(file_digest, "_hash_file", side_effect=slow_hash) as worker, \
                        patch.object(scene_disk_cache, "_limit", return_value=100000):
                    self.assertIsNone(scene_disk_cache.key(doc, 0, 1, False))
                    self.assertTrue(entered.wait(2))
                    self.assertIsNone(scene_disk_cache.key(doc, 0, 2, False))
                    self.assertEqual(worker.call_count, 1)
                    saved = threading.Event()
                    saved_keys = []
                    def on_ready(key):
                        saved_keys.append((key, threading.get_ident()))
                        saved.set()
                    self.assertIsNone(scene_disk_cache.key(
                        doc, 0, 1, False, on_ready=on_ready))
                    release.set()
                    doc._disk_cache_hash_job.future.result(timeout=5)
                    self.assertTrue(saved.wait(2))
                    self.assertEqual(saved_keys[0][0], scene_disk_cache.key(doc, 0, 1, False))
                    self.assertNotEqual(saved_keys[0][1], threading.get_ident())
                    saved.clear()
                    self.assertIsNone(scene_disk_cache.key(
                        doc, 0, 1, False, on_ready=on_ready, defer_ready=True))
                    self.assertTrue(saved.wait(2))
                    self.assertNotEqual(saved_keys[-1][1], threading.get_ident())
                    with path.open("ab") as stream:
                        stream.write(b"changed")
                    self.assertIsNone(scene_disk_cache.key(doc, 0, 1, False))
            finally:
                release.set()
                doc.close()

    def test_changed_file_and_cancelled_job_produce_no_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data"
            path.write_bytes(b"before")
            expected = file_digest.revision(path.stat())
            path.write_bytes(b"after-change")
            self.assertIsNone(file_digest._hash_file(path, expected, threading.Event()))
            cancelled = threading.Event()
            cancelled.set()
            self.assertIsNone(file_digest._hash_file(
                path, file_digest.revision(path.stat()), cancelled))

    def test_document_close_and_edit_cancel_hashing(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.pdf"
            with pymupdf.open() as pdf:
                pdf.new_page()
                pdf.save(path)
            doc = Document(str(path))
            doc._disk_cache_hash_job = Mock()
            doc.invalidate_render()
            doc._disk_cache_hash_job.cancel.assert_called_once()
            doc._disk_cache_hash_job.reset_mock()
            doc.close()
            doc._disk_cache_hash_job.cancel.assert_called_once()
