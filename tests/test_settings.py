import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfeditor import settings


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
