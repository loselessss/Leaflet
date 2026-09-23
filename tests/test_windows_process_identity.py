import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_version_info import version_info_text, write_version_info_files
from pdfeditor import windows_integration
from pdfeditor.meta import APP_VERSION


class WindowsProcessIdentityTests(unittest.TestCase):
    def test_non_windows_app_id_is_safe_noop(self):
        with patch.object(windows_integration.sys, "platform", "linux"):
            self.assertFalse(windows_integration.set_current_process_app_id())

    def test_version_info_uses_four_part_numeric_version(self):
        text = version_info_text("1.7.2", "sPDF", "sPDF", "sPDF.exe")
        self.assertIn("filevers=(1, 7, 2, 0)", text)
        self.assertIn("StringStruct('FileDescription', 'sPDF')", text)

    def test_gui_and_ocr_resources_share_release_version(self):
        with tempfile.TemporaryDirectory() as directory:
            gui_path, ocr_path = write_version_info_files(
                directory, APP_VERSION)
            gui = Path(gui_path).read_text(encoding="utf-8")
            ocr = Path(ocr_path).read_text(encoding="utf-8")

        self.assertIn("StringStruct('ProductVersion', %r)" % APP_VERSION, gui)
        self.assertIn("StringStruct('ProductVersion', %r)" % APP_VERSION, ocr)
        self.assertIn("Leaflet OCR 작업 프로세스", ocr)


if __name__ == "__main__":
    unittest.main()
