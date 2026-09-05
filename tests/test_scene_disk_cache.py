import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from pdfeditor.core import Document
from pdfeditor import scene_disk_cache as cache
from pdfeditor.gpu_raster import VectorPage, VectorImage


class SceneDiskCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.redirect = patch("pdfeditor.paths.user_data_dir", return_value=str(self.root))
        self.redirect.start()
        self.path = self.root / "sample.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((20, 30), "Cache example")
            pdf.save(self.path)

    def tearDown(self):
        self.redirect.stop()
        self.temp.cleanup()

    def test_reopen_uses_scene_without_extraction(self):
        doc = Document(str(self.path))
        scene = doc.gpu_vector_page(0)
        doc.close()
        doc = Document(str(self.path))
        try:
            with patch("pdfeditor.gpu_raster.vector_page_from_pymupdf", side_effect=AssertionError):
                self.assertEqual(doc.gpu_vector_page(0), scene)
        finally:
            doc.close()

    def test_file_and_version_changes_invalidate(self):
        doc = Document(str(self.path))
        try:
            first = cache.key(doc, 0, 1, False)
            with patch("pdfeditor.meta.APP_VERSION", "different"):
                self.assertNotEqual(first, cache.key(doc, 0, 1, False))
            doc.invalidate_render()
            self.assertIsNone(cache.key(doc, 0, 1, False))
        finally:
            doc.close()
        with self.path.open("ab") as stream:
            stream.write(b"\n% changed\n")
        doc = Document(str(self.path))
        try:
            self.assertNotEqual(first, cache.key(doc, 0, 1, False))
        finally:
            doc.close()

    def test_corrupt_cache_is_a_miss(self):
        cache.save("broken", VectorPage(True))
        with sqlite3.connect(self.root / "cache" / "gpu-scenes.sqlite3") as db:
            db.execute("UPDATE scenes SET data=?", (b"invalid",))
        db.close()
        self.assertIsNone(cache.load("broken"))

    def test_protected_document_is_not_persisted(self):
        protected = self.root / "protected.pdf"
        with pymupdf.open(self.path) as pdf:
            pdf.save(protected, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                     owner_pw="owner", user_pw="reader")
        doc = Document(str(protected), password="reader")
        try:
            self.assertIsNone(cache.key(doc, 0, 1, False))
        finally:
            doc.close()

    def test_worker_scene_is_reused_after_reopen(self):
        doc = Document(str(self.path))
        scene = VectorPage(True, raster_scale=2, features=("image-downsample",))
        doc.install_gpu_vector_page(0, scene)
        doc.close()
        doc = Document(str(self.path))
        try:
            self.assertEqual(doc.cached_gpu_vector_page(0, 2), scene)
            self.assertIsNone(doc.cached_gpu_vector_page(0, 4))
        finally:
            doc.close()

    def test_budget_evicts_oldest_and_roundtrips_pixels(self):
        def scene():
            return VectorPage(True, items=(VectorImage(
                os.urandom(4096), 32, 32, 128, (1, 0, 0, 1, 0, 0)),))
        first, second = scene(), scene()
        with patch.object(cache, "LIMIT", 7000):
            cache.save("first", first)
            self.assertEqual(cache.load("first"), first)
            cache.save("second", second)
        self.assertIsNone(cache.load("first"))
        self.assertEqual(cache.load("second"), second)
