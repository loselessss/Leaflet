import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfeditor import settings


class RecentFileSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.temp = self.root / "Temp"
        self.cache = self.root / "Local" / "Microsoft" / "Windows" / "INetCache"
        self.real_roots = settings._temporary_file_roots
        for name, value in (("PATH", str(self.root / "settings.json")),
                            ("_OLD_PATH", str(self.root / "absent.json"))):
            self.enterContext(patch.object(settings, name, value))
        self.enterContext(patch.object(settings, "_temporary_file_roots", return_value=(
            os.path.normcase(str(self.temp)), os.path.normcase(str(self.cache)))))

    def test_temporary_open_does_not_enter_history_or_displace_documents(self):
        for index in range(settings.MAX_RECENT):
            settings.push_recent(str(self.root / f"document{index}.pdf"))
        before = settings._load()
        for temporary in (self.temp / "attachment.pdf",
                          self.cache / "Content.Outlook" / "ABC123" / "mail.pdf"):
            settings.push_recent(str(temporary))
        self.assertEqual(settings._load(), before)
        self.assertEqual(len(settings.recent_files()), settings.MAX_RECENT)

    def test_old_temporary_entries_are_hidden_and_cleaned_on_next_open(self):
        keep = str(self.root / "Documents" / "report.pdf")
        temporary = str(self.temp / "old.pdf")
        outlook = str(self.cache / "Content.Outlook" / "ABC123" / "mail.pdf")
        settings._save({"recent": [temporary, keep, outlook],
                        "favorites": [temporary], "custom": {"value": 42}})
        with patch.object(settings, "_save") as save:
            self.assertEqual(settings.recent_files(), [keep])
            save.assert_not_called()
        settings.push_recent(outlook)
        self.assertEqual(settings._load(), {"recent": [keep],
                         "favorites": [temporary], "custom": {"value": 42}})
        new = str(self.root / "Documents" / "new.pdf")
        settings.push_recent(new)
        self.assertEqual(settings.recent_files(), [new, keep])
        settings.push_recent(keep)
        self.assertEqual(settings.recent_files(), [keep, new])

    def test_similar_names_and_ordinary_temp_named_folders_are_kept(self):
        paths = [self.root / "Temp-archive" / "saved.pdf",
                 self.root / "Documents" / "temp" / "report.pdf",
                 self.root / "Documents" / "template.pdf",
                 self.cache.parent / "INetCache-backup" / "saved.pdf"]
        for path in paths:
            settings.push_recent(str(path))
        self.assertEqual(settings.recent_files(), [str(p) for p in reversed(paths)])

    def test_detects_runtime_windows_and_outlook_cache_roots(self):
        runtime = str(self.root / "runtime-temp")
        local = self.root / "Local"
        with patch.dict(os.environ, {"TEMP": str(self.temp),
                                    "TMP": str(self.root / "other-temp"),
                                    "LOCALAPPDATA": str(local),
                                    "WINDIR": str(self.root / "Windows")}), \
                patch.object(settings.tempfile, "gettempdir", return_value=runtime):
            roots = self.real_roots()
        for folder in (Path(runtime), self.temp, self.root / "other-temp",
                       local / "Temp", self.cache,
                       local / "Microsoft" / "Windows" / "Temporary Internet Files",
                       self.root / "Windows" / "Temp"):
            with self.subTest(folder=folder):
                self.assertTrue(settings._is_temporary_file(str(folder / "file.pdf"), roots))
        self.assertFalse(settings._is_temporary_file(str(local / "Documents" / "file.pdf"), roots))

    @unittest.skipUnless(os.name == "nt", "Windows path normalization")
    def test_windows_case_slashes_and_parent_segments(self):
        path = str(self.temp / "folder" / ".." / "mail.pdf").upper().replace("\\", "/")
        settings.push_recent(path)
        self.assertEqual(settings.recent_files(), [])
        self.assertFalse(Path(settings.PATH).exists())


class AutomaticUpdateScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings_path = str(Path(self.directory.name) / "settings.json")
        self.path_patch = patch.object(settings, "PATH", self.settings_path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.directory.cleanup()

    def test_first_automatic_check_is_due(self):
        self.assertTrue(settings.automatic_update_check_due(now=1000))

    def test_startup_workspace_defaults_validates_and_persists(self):
        self.assertEqual(settings.startup_workspace(), "reader")
        self.assertTrue(settings.set_startup_workspace("editor"))
        self.assertEqual(settings.startup_workspace(), "editor")
        self.assertFalse(settings.set_startup_workspace("unknown"))
        self.assertEqual(settings.startup_workspace(), "editor")
        with patch.object(settings, "_load", return_value={"startup_workspace": "unknown"}):
            self.assertEqual(settings.startup_workspace(), "reader")

    def test_render_backend_defaults_validates_and_persists(self):
        self.assertEqual(settings.render_backend(), "auto")
        self.assertTrue(settings.set_render_backend("gpu"))
        self.assertEqual(settings.render_backend(), "gpu")
        self.assertTrue(settings.set_render_backend("cpu"))
        self.assertEqual(settings.render_backend(), "cpu")
        self.assertFalse(settings.set_render_backend("vulkan"))
        self.assertEqual(settings.render_backend(), "cpu")
        with patch.object(settings, "_load", return_value={"render_backend": "bad"}):
            self.assertEqual(settings.render_backend(), "auto")

    def test_object_snapping_defaults_on_and_persists(self):
        self.assertTrue(settings.object_snapping())
        settings.set_object_snapping(False)
        self.assertFalse(settings.object_snapping())
        settings.set_object_snapping(True)
        self.assertTrue(settings.object_snapping())

    def test_render_diagnostics_defaults_off_and_persists(self):
        self.assertFalse(settings.render_diagnostics())
        self.assertTrue(settings.set_render_diagnostics(True))
        self.assertTrue(settings.render_diagnostics())
        self.assertTrue(settings.set_render_diagnostics(False))
        self.assertFalse(settings.render_diagnostics())

    def test_automatic_check_is_limited_to_once_per_24_hours(self):
        settings.mark_automatic_update_check(now=1000)

        self.assertFalse(settings.automatic_update_check_due(
            now=1000 + 24 * 60 * 60 - 1))
        self.assertTrue(settings.automatic_update_check_due(
            now=1000 + 24 * 60 * 60))

    def test_clock_rollback_does_not_block_checks_indefinitely(self):
        settings.mark_automatic_update_check(now=2000)

        self.assertTrue(settings.automatic_update_check_due(now=1000))

    def test_ui_language_defaults_to_english(self):
        with patch.object(settings, "_installer_ui_language", return_value=None):
            self.assertEqual(settings.ui_language(), "en")

    def test_ui_language_uses_installer_choice_before_user_setting(self):
        with patch.object(settings, "_installer_ui_language", return_value="ko"):
            self.assertEqual(settings.ui_language(), "ko")

    def test_ui_language_can_be_saved_as_korean(self):
        self.assertTrue(settings.set_ui_language("ko"))
        self.assertEqual(settings.ui_language(), "ko")

    def test_invalid_ui_language_is_rejected(self):
        with patch.object(settings, "_installer_ui_language", return_value=None):
            self.assertFalse(settings.set_ui_language("fr"))
            self.assertEqual(settings.ui_language(), "en")

    def test_reading_positions_are_bounded_and_validated(self):
        self.assertIsNone(settings.reading_position("missing.pdf"))
        state = {"page": 4, "zoom": 1.5, "vertical": 0.7}
        for index in range(105):
            settings.set_reading_position("%s.pdf" % index, state)
        self.assertIsNone(settings.reading_position("0.pdf"))
        self.assertEqual(settings.reading_position("104.pdf")["page"], 4)
        self.assertEqual(settings.reading_position("104.pdf")["vertical"], 0.7)
        self.assertIsNone(settings._clean_reading_position({"page": 0, "zoom": float("nan")}))

    def test_failed_settings_write_preserves_previous_settings(self):
        settings.set_sidebar_mode("bookmarks")
        original = Path(self.settings_path).read_bytes()
        with patch.object(settings.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                settings.set_sidebar_mode("none")
        self.assertEqual(Path(self.settings_path).read_bytes(), original)

    def test_sidebar_mode_defaults_to_thumbnails_and_can_be_saved(self):
        self.assertEqual(
            settings.SIDEBAR_MODES,
            ("none", "thumbnails", "bookmarks"))
        self.assertEqual(settings.sidebar_mode(), "thumbnails")
        self.assertTrue(settings.set_sidebar_mode("bookmarks"))
        self.assertEqual(settings.sidebar_mode(), "bookmarks")
        self.assertFalse(settings.set_sidebar_mode("invalid"))

    def test_print_duplex_mode_defaults_to_simplex_and_can_be_saved(self):
        self.assertEqual(settings.print_duplex_mode(), "simplex")
        self.assertTrue(settings.set_print_duplex_mode("long"))
        self.assertEqual(settings.print_duplex_mode(), "long")
        self.assertTrue(settings.set_print_duplex_mode("short"))
        self.assertEqual(settings.print_duplex_mode(), "short")
        self.assertFalse(settings.set_print_duplex_mode("booklet"))
        self.assertEqual(settings.print_duplex_mode(), "short")


if __name__ == "__main__":
    unittest.main()
