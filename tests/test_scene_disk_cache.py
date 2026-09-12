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
        self.settings = patch("pdfeditor.settings.PATH", str(self.root / "settings.json"))
        self.settings.start()
        self.path = self.root / "sample.pdf"
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((20, 30), "Cache example")
            pdf.save(self.path)

    def tearDown(self):
        self.redirect.stop()
        self.settings.stop()
        self.temp.cleanup()

    def test_reopen_uses_scene_without_extraction(self):
        doc = Document(str(self.path))
        scene = doc.gpu_vector_page(0)
        doc.close()
        doc = Document(str(self.path))
        try:
            with patch("pdfeditor.meta.APP_VERSION", "app-only-update"), \
                    patch("pdfeditor.gpu_raster.vector_page_from_pymupdf", side_effect=AssertionError):
                self.assertEqual(doc.gpu_vector_page(0), scene)
        finally:
            doc.close()

    def test_memory_only_lookup_does_not_restore_disk_scene(self):
        doc = Document(str(self.path))
        try:
            with patch.object(doc, "_load_disk_gpu_scene") as restore:
                self.assertIsNone(doc.cached_gpu_vector_page(0, memory_only=True))
                restore.assert_not_called()
        finally:
            doc.close()

    def test_worker_loads_disk_scene_without_extraction(self):
        from pdfeditor.gpu_scene_worker import main
        import pickle
        doc = Document(str(self.path))
        try:
            scene = doc.gpu_vector_page(0)
            key = doc.gpu_scene_disk_cache_key(0)
        finally:
            doc.close()
        result = self.root / "result.pickle"
        with patch("pdfeditor.gpu_scene_worker.vector_page_from_pymupdf",
                   side_effect=AssertionError("Unexpected extraction")):
            self.assertEqual(main([str(self.path), str(result),
                                   "--disk-cache-key", key]), 0)
        with result.open("rb") as stream:
            self.assertEqual(pickle.load(stream), scene)

    def test_file_and_version_changes_invalidate(self):
        doc = Document(str(self.path))
        try:
            first = cache.key(doc, 0, 1, False)
            with patch("pdfeditor.meta.APP_VERSION", "different"):
                self.assertEqual(first, cache.key(doc, 0, 1, False))
            with patch.object(cache, "SCENE_FORMAT_VERSION", 999):
                self.assertNotEqual(first, cache.key(doc, 0, 1, False))
            with patch("pdfeditor.d2d_backend.ABI_VERSION", 999):
                self.assertNotEqual(first, cache.key(doc, 0, 1, False))
            with patch("pymupdf.VersionBind", "different"):
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
                os.urandom(40960), 64, 160, 256, (1, 0, 0, 1, 0, 0)),))
        first, second = scene(), scene()
        with patch.object(cache, "_limit", return_value=70000):
            cache.save("first", first)
            self.assertEqual(cache.load("first"), first)
            cache.save("second", second)
        self.assertIsNone(cache.load("first"))
        self.assertEqual(cache.load("second"), second)

    def test_image_reference_cache_restores_exact_pixels_and_transforms(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, 256, 256, os.urandom(256*256*3), False)
            xref = page.insert_image(pymupdf.Rect(0, 0, 256, 256), pixmap=pixmap)
            page.insert_image(pymupdf.Rect(270, 0, 398, 128), xref=xref, rotate=90)
            scene = vector_page_from_pymupdf(page)
            cache.save("images", scene)
            self.assertIsNone(cache.load("images"))
            restored = cache.load("images", page)
            self.assertEqual(restored, scene)
            db = cache._connect()
            size = db.execute("SELECT length(data) FROM scenes WHERE key='images'").fetchone()[0]
            db.close()
            self.assertLess(size, 5000)

    def test_disabled_cache_clears_entries_and_skips_writes(self):
        from pdfeditor import settings
        cache.save("old", VectorPage(True))
        settings.set_disk_cache_mb(0)
        cache.trim()
        cache.save("new", VectorPage(True))
        settings.set_disk_cache_mb(100)
        self.assertIsNone(cache.load("old"))
        self.assertIsNone(cache.load("new"))

    def test_size_setting_validation(self):
        from pdfeditor import settings
        settings.set_disk_cache_mb(250)
        self.assertEqual(cache._limit(), 250*1024*1024)
        with self.assertRaises(ValueError):
            settings.set_disk_cache_mb(-1)
