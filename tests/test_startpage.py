import base64
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import pymupdf
from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication

from pdfeditor import settings
from pdfeditor.home_previews import HomePreviews
from pdfeditor.home_preview_worker import preview
from pdfeditor.startpage import StartPage
from pdfeditor.theme import apply_theme_colors


class StartPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(settings, "PATH", str(self.root / "settings.json")))
        self.enterContext(patch("pdfeditor.paths.user_data_dir", return_value=str(self.root)))
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}))
        self.enterContext(patch.object(settings, "_temporary_file_roots", return_value=()))
        self.enterContext(patch("pdfeditor.home_previews.HomePreviews._start_next"))
        apply_theme_colors(self.app, False)
        self.page = StartPage(workspace_mode="reader", workspace_switching=True)
        self.addCleanup(self.dispose)

    def dispose(self):
        self.page.close()
        self.page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def populate(self, favorites, recent=40):
        settings._save({"favorites": [str(self.root / ("favorite%d.pdf" % i)) for i in range(favorites)],
                        "recent": [str(self.root / ("recent%d.pdf" % i)) for i in range(recent)]})
        self.page.refresh()

    def settle(self):
        for _ in range(4):
            self.app.processEvents()
        self.page._fit_favorites()
        self.app.processEvents()

    def test_columns_follow_width_without_horizontal_scrolling(self):
        self.populate(4)
        self.page.resize(1280, 960)
        self.page.show()
        self.settle()
        wide = self.page.recent_list.columns
        self.page.resize(620, 760)
        self.settle()
        self.assertGreater(wide, self.page.recent_list.columns)
        view = self.page.recent_list
        self.assertEqual(view.horizontalScrollBar().maximum(), 0)
        self.assertLessEqual(view.visualItemRect(view.item(view.columns - 1)).right(), view.viewport().width())
        self.assertEqual(view.visualItemRect(view.item(view.columns - 1)).top(),
                         view.visualItemRect(view.item(0)).top())
        self.page.resize(860, 700)
        self.settle()
        self.assertEqual(view.visualItemRect(view.item(view.columns - 1)).top(),
                         view.visualItemRect(view.item(0)).top())

    def test_favorites_grow_to_two_rows_then_expand_in_one_scroll_area(self):
        self.page.resize(1100, 980)
        self.page.show()
        self.populate(1)
        self.settle()
        self.assertEqual(self.page.fav_list.height(), 180)
        self.populate(30)
        self.settle()
        self.assertEqual(self.page.fav_list.height(), 358)
        self.assertEqual(self.page.fav_list.verticalScrollBar().maximum(), 0)
        self.assertTrue(self.page.more_favorites.isVisible())
        self.assertGreaterEqual(self.page.recent_list.height(), 178)
        self.assertGreater(self.page.recent_list.y(), self.page.fav_list.geometry().bottom())
        self.page.more_favorites.click()
        self.settle()
        self.assertGreater(self.page.fav_list.height(), 358)
        self.assertGreater(self.page.file_scroll.verticalScrollBar().maximum(), 0)
        self.page.more_favorites.click()
        self.settle()
        self.assertEqual(self.page.fav_list.height(), 358)

    def test_empty_favorites_stay_compact_and_short_windows_keep_recent_space(self):
        self.page.resize(700, 560)
        self.page.show()
        self.populate(0)
        self.settle()
        self.assertEqual(self.page.fav_list.height(), 56)
        self.populate(30)
        self.settle()
        self.assertEqual(self.page.fav_list.height(), 180)
        self.assertGreater(self.page.recent_list.height(), 55)

    def test_scroll_prepares_visible_files_and_replaces_old_queue(self):
        self.populate(2, 30)
        self.page.resize(860, 700)
        self.page.show()
        self.settle()
        with patch.object(self.page._previews, "request") as request:
            self.page._prepare_visible()
            first = request.call_args.args[0]
            self.assertLess(len(first), 32)
            self.page.file_scroll.verticalScrollBar().setValue(self.page.file_scroll.verticalScrollBar().maximum())
            self.settle()
            self.page._prepare_visible()
            last = request.call_args.args[0]
            self.assertNotEqual(first, last)
            self.assertIn(str(self.root / "recent29.pdf"), last)

    def test_click_and_context_paths_remain_available(self):
        self.populate(1)
        self.page.resize(1000, 800)
        self.page.show()
        self.settle()
        view = self.page.recent_list
        point = view.visualItemRect(view.item(0)).center()
        spy = QSignalSpy(self.page.open_file)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(list(spy), [[str(self.root / "recent0.pdf")]])
        self.assertEqual(view.path_at(point), str(self.root / "recent0.pdf"))
        switch = QSignalSpy(self.page.workspace_requested)
        self.page.switch_mode_button.click()
        self.assertEqual(list(switch), [["editor"]])

    def test_hiding_stops_preview_work_and_keeps_ram_cache(self):
        self.populate(1)
        self.page.show()
        self.settle()
        cache = self.page._previews
        cache._active = (str(self.root / "recent0.pdf"), None)
        cache._complete(QImage(20, 20, QImage.Format_RGB32), "ready")
        self.page.hide()
        self.assertIsNone(cache._active)
        self.assertFalse(cache._pending)
        self.assertIsNotNone(cache.lookup(str(self.root / "recent0.pdf"))[0])


class HomePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.enterContext(patch.object(settings, "PATH", str(self.root / "settings.json")))
        self.enterContext(patch("pdfeditor.paths.user_data_dir", return_value=str(self.root)))
        self.enterContext(patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}))
        self.enterContext(patch.object(settings, "_temporary_file_roots", return_value=()))
        self.path = str(self.root / "document.pdf")
        with pymupdf.open() as document:
            document.new_page(width=1800, height=1000).insert_text((80, 80), "Home preview")
            document.save(self.path)
        settings.push_recent(self.path)

    def test_first_page_preview_is_bounded_and_persisted_without_scene_cache(self):
        settings.set_disk_cache_mb(0)
        result = preview(self.path)
        self.assertEqual(result["status"], "ready")
        image = QImage.fromData(base64.b64decode(result["png"]))
        self.assertLessEqual(image.width(), 341)
        self.assertLessEqual(image.height(), 221)
        with patch.object(pymupdf.Page, "get_pixmap", side_effect=AssertionError("Must reuse disk thumbnail")):
            self.assertEqual(preview(self.path), result)

    def test_modified_pdf_regenerates_preview(self):
        first = preview(self.path)
        with pymupdf.open(self.path) as document:
            document[0].draw_rect(document[0].rect, color=(1, 0, 0), fill=(1, 0, 0))
            document.saveIncr()
        self.assertNotEqual(preview(self.path)["png"], first["png"])

    def test_preview_uses_private_copy_and_releases_original_before_rendering(self):
        original = pymupdf.Page.get_pixmap
        def render(page, *args, **kwargs):
            self.assertNotEqual(page.parent.name, self.path)
            replacement = Path(self.path).with_suffix(".replacement")
            replacement.write_bytes(Path(self.path).read_bytes())
            os.replace(replacement, self.path)
            return original(page, *args, **kwargs)
        with patch.object(pymupdf.Page, "get_pixmap", render):
            self.assertEqual(preview(self.path)["status"], "ready")

    def test_encrypted_preview_does_not_persist(self):
        protected = str(self.root / "protected.pdf")
        with pymupdf.open(self.path) as document:
            document.save(protected, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="reader", owner_pw="owner")
        from pdfeditor import scene_disk_cache
        with patch.object(scene_disk_cache, "save_thumbnail") as save:
            self.assertEqual(preview(protected), {"status": "locked"})
        save.assert_not_called()

    def test_corrupt_disk_thumbnail_is_regenerated(self):
        from pdfeditor import scene_disk_cache
        preview(self.path)
        with scene_disk_cache._connect() as database:
            database.execute("UPDATE scenes SET data=? WHERE key LIKE 'thumbnail-v1:%'", (b"\x89PNG\r\n\x1a\nbroken",))
        database.close()
        self.assertEqual(preview(self.path)["status"], "ready")

    def test_removal_waits_for_both_lists_and_rejects_late_results(self):
        from pdfeditor import scene_disk_cache as disk
        settings.add_favorite(self.path)
        result = preview(self.path)
        with disk._connect() as database:
            key, = database.execute("SELECT key FROM scenes WHERE key LIKE 'thumbnail-v1:%'").fetchone()
        database.close()
        key = key.removeprefix("thumbnail-v1:")
        settings.remove_recent(self.path)
        self.assertIsNotNone(disk.load_thumbnail(key))
        settings.remove_favorite(self.path)
        self.assertIsNone(disk.load_thumbnail(key))
        disk.save_thumbnail(key, base64.b64decode(result["png"]))
        self.assertIsNone(disk.load_thumbnail(key))

    def test_ram_cache_is_bounded_and_drops_removed_paths(self):
        cache = HomePreviews()
        with patch.object(cache, "_start_next"):
            cache.MAX_BYTES = 2000
            for index in range(5):
                cache._active = (str(index), None)
                cache._complete(QImage(20, 20, QImage.Format_RGB32), "ready")
            self.assertLessEqual(cache._bytes, 2000)
            self.assertEqual(len(cache._cache), 1)
            cache.retain([])
            self.assertEqual(cache._bytes, 0)
        cache.stop()

    def test_thumbnail_and_scene_use_one_eviction_budget(self):
        from pdfeditor import scene_disk_cache as disk
        from pdfeditor.gpu_raster import VectorImage, VectorPage
        result = preview(self.path)
        with disk._connect() as database:
            database.execute("UPDATE scenes SET used=0")
            key, = database.execute("SELECT key FROM scenes WHERE key LIKE 'thumbnail-v1:%'").fetchone()
        database.close()
        scene = VectorPage(True, items=(VectorImage(
            os.urandom(40960), 64, 160, 256, (1, 0, 0, 1, 0, 0)),))
        with patch.object(disk, "_limit", return_value=70000):
            disk.save("first", scene)
            disk.save("second", scene)
            self.assertIsNone(disk.load_thumbnail(key.removeprefix("thumbnail-v1:")))
            self.assertIsNone(disk.load("first"))
            self.assertEqual(disk.load("second"), scene)
            with disk._connect() as database:
                total, = database.execute("SELECT sum(length(data)) FROM scenes").fetchone()
            database.close()
            self.assertLessEqual(total, 63000)
        self.assertEqual(result["status"], "ready")

    def test_disabling_scene_cache_keeps_thumbnail_and_deletes_scenes(self):
        from pdfeditor import scene_disk_cache as disk
        from pdfeditor.gpu_raster import VectorPage
        result = preview(self.path)
        disk.save("scene", VectorPage(True))
        settings.set_disk_cache_mb(0)
        disk.trim()
        with patch.object(pymupdf.Page, "get_pixmap", side_effect=AssertionError("Must reuse disk thumbnail")):
            self.assertEqual(preview(self.path), result)
        settings.set_disk_cache_mb(100)
        self.assertIsNone(disk.load("scene"))

    def test_reduced_thumbnail_budget_evicts_oldest(self):
        from pdfeditor import scene_disk_cache as disk
        settings.set_disk_cache_mb(0)
        png = b"\x89PNG\r\n\x1a\n" + os.urandom(24000)
        first = disk.thumbnail_key(self.path, (1,), "test")
        second = disk.thumbnail_key(self.path, (2,), "test")
        other = str(self.root / "other.pdf")
        settings.push_recent(other)
        second = disk.thumbnail_key(other, (2,), "test")
        with patch.object(disk, "THUMBNAIL_ONLY_LIMIT", 40000):
            disk.save_thumbnail(first, png)
            disk.save_thumbnail(second, png)
            self.assertIsNone(disk.load_thumbnail(first))
            self.assertEqual(disk.load_thumbnail(second), png)

    def test_clearing_history_keeps_favorites_and_deletes_other_previews(self):
        from pdfeditor import scene_disk_cache as disk
        settings.add_favorite(self.path)
        preview(self.path)
        other = str(self.root / "other.pdf")
        Path(other).write_bytes(Path(self.path).read_bytes())
        settings.push_recent(other)
        preview(other)
        settings.clear_recent()
        with disk._connect() as database:
            keys = [key for key, in database.execute("SELECT key FROM scenes")]
        database.close()
        self.assertEqual(len(keys), 1)
        self.assertIn(disk._thumbnail_path_id(self.path), keys[0])

    def test_trimmed_history_removes_old_preview_automatically(self):
        from pdfeditor import scene_disk_cache as disk
        preview(self.path)
        with patch.object(settings, "MAX_RECENT", 1):
            settings.push_recent(str(self.root / "new.pdf"))
        with disk._connect() as database:
            self.assertEqual(database.execute("SELECT count(*) FROM scenes").fetchone()[0], 0)
        database.close()

    def test_failed_history_write_preserves_disk_thumbnail(self):
        from pdfeditor import scene_disk_cache as disk
        preview(self.path)
        with patch.object(settings, "_save", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                settings.remove_file_entry(self.path)
        with disk._connect() as database:
            self.assertEqual(database.execute("SELECT count(*) FROM scenes").fetchone()[0], 1)
        database.close()

    def test_isolated_worker_returns_image_and_survives_missing_file(self):
        cache = HomePreviews()
        self.addCleanup(cache.stop)
        # Missing files do not write a cache; this subprocess cannot see our patched history.
        cache.request([str(self.root / "missing.pdf"), self.path])
        deadline = time.monotonic() + 15
        while cache.lookup(self.path)[1] == "pending" and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(cache.lookup(str(self.root / "missing.pdf"))[1], "unavailable")
        self.assertEqual(cache.lookup(self.path)[1], "ready")
        self.assertIsNotNone(cache.lookup(self.path)[0])
        work_dir = cache._resources["temporary"].name
        cache.stop()
        cache._process.waitForFinished(2000)
        self.app.processEvents()
        self.assertFalse(Path(work_dir).exists())
