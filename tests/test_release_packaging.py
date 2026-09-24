import re
import unittest
from pathlib import Path

from pdfeditor.meta import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingTests(unittest.TestCase):
    def test_standalone_starts_in_reader_workspace(self):
        entry = (ROOT / "pdfeditor" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn('workspace = args.workspace or settings.startup_workspace()', entry)
        self.assertIn('workspace_mode=workspace', entry)
        from pdfeditor import settings
        from unittest.mock import patch
        with patch.object(settings, "_load", return_value={}):
            self.assertEqual(settings.startup_workspace(), "reader")

    def test_standalone_entry_point_uses_native_file_dialogs(self):
        entry = (ROOT / "pdfeditor" / "__main__.py").read_text(
            encoding="utf-8")
        self.assertNotIn("AA_DontUseNativeDialogs", entry)

    def test_application_and_installer_versions_match(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        match = re.search(
            r'^#define MyAppVersion "([^"]+)"$', installer, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), APP_VERSION)

    def test_installer_offers_english_and_korean(self):
        installer = Path("installer.iss").read_text(encoding="utf-8-sig")
        self.assertIn('Name: "english"', installer)
        self.assertIn('Name: "korean"', installer)
        self.assertIn("ShowLanguageDialog=yes", installer)
        self.assertIn('ValueName: "UILanguage"', installer)

    def test_registered_document_type_is_simply_pdf(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn(
            'Subkey: "Software\\Classes\\{#MyProgId}"; '
            'ValueType: string; ValueData: "PDF";', installer)
        registration = (ROOT / "register_filetype.py").read_text(
            encoding="utf-8")
        self.assertIn('k, "", 0, winreg.REG_SZ, "PDF")', registration)
        self.assertNotIn("PDF / Illustrator Document", installer)
        self.assertNotIn("PDF / Illustrator Document", registration)

    def test_localized_release_documents_include_current_version(self):
        for name in (
                "README.md", "README.ko.md", "CHANGELOG.md",
                "CHANGELOG.ko.md", "RELEASE_NOTES.md",
                "RELEASE_NOTES.ko.md"):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(APP_VERSION, content, name)

        self.assertIn(
            "[한국어](README.ko.md)",
            (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn(
            "[English](README.md)",
            (ROOT / "README.ko.md").read_text(encoding="utf-8"))

    def test_version_tag_builds_github_release(self):
        workflow = (
            ROOT / ".github" / "workflows" / "release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('      - "v*.*.*"', workflow)
        self.assertIn("cmd /c build_exe.bat", workflow)
        self.assertIn("cmd /c build_installer.bat", workflow)
        self.assertIn("python ci_test_runner.py", workflow)
        self.assertIn("Get-FileHash -Algorithm SHA256", workflow)
        self.assertIn("Leaflet_Setup_latest.exe", workflow)
        self.assertIn("Output\\sPDF_Setup_$version.exe", workflow)
        self.assertIn("gh release create", workflow)
        self.assertIn("python release_notes.py", workflow)
        self.assertIn("--release-notes RELEASE_NOTES.md", workflow)
        self.assertIn("--release-notes-ko RELEASE_NOTES.ko.md", workflow)
        self.assertIn("--notes-file release-notes.md", workflow)
        self.assertNotIn("--generate-notes", workflow)
        self.assertIn("gh release edit", workflow)
        self.assertIn("gh release upload", workflow)
        self.assertIn("--clobber", workflow)
        self.assertIn("contents: write", workflow)

    def test_both_executables_have_windows_version_resources(self):
        spec = (ROOT / "spdf.spec").read_text(encoding="utf-8")
        self.assertIn("version=gui_version_info", spec)
        self.assertIn("version=ocr_version_info", spec)
        self.assertGreaterEqual(spec.count('icon="assets/spdf.ico"'), 2)

    def test_installer_shortcuts_use_same_app_id_as_runtime(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        integration = (
            ROOT / "pdfeditor" / "windows_integration.py"
        ).read_text(encoding="utf-8")
        app_id = re.search(
            r'^#define MyAppUserModelId "([^"]+)"$',
            installer, re.MULTILINE).group(1)
        runtime_app_id = re.search(
            r'^APP_USER_MODEL_ID = ["\']([^"\']+)["\']$',
            integration, re.MULTILINE).group(1)
        self.assertEqual(runtime_app_id, app_id)
        self.assertEqual(installer.count('AppUserModelID: "{#MyAppUserModelId}"'), 4)
        worker = (ROOT / "ocr_worker_main.py").read_text(encoding="utf-8")
        self.assertIn("set_current_process_app_id()", worker)

    def test_installer_creates_explicit_reader_and_editor_shortcuts(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        for target in ("{group}", "{autodesktop}"):
            self.assertIn(
                'Name: "%s\\{cm:ReaderShortcut}"' % target, installer)
            self.assertIn(
                'Name: "%s\\{cm:EditorShortcut}"' % target, installer)
        self.assertEqual(installer.count('Parameters: "--workspace reader"'), 2)
        self.assertEqual(installer.count('Parameters: "--workspace editor"'), 2)
        self.assertIn("Tasks: desktopreader", installer)
        self.assertIn("Tasks: desktopeditor", installer)
        self.assertIn("Flags: unchecked", installer)
        self.assertIn("korean.ReaderShortcut=Leaflet 리더", installer)
        self.assertIn("korean.EditorShortcut=Leaflet 편집기", installer)
        self.assertNotIn("Tasks: desktopicon", installer)
        for target in ("{group}", "{autodesktop}"):
            self.assertIn(
                'Type: files; Name: "%s\\{#MyAppName}.lnk"' % target,
                installer)
            for name in ("sPDF Reader.lnk", "sPDF Editor.lnk",
                         "sPDF 리더.lnk", "sPDF 편집기.lnk"):
                self.assertIn(
                    'Type: files; Name: "%s\\%s"' % (target, name), installer)

    def test_installer_registers_pdf_and_illustrator_open_with(self):
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn(
            'Subkey: "Software\\Classes\\.pdf\\OpenWithProgids"',
            installer)
        self.assertIn(
            'Subkey: "Software\\Classes\\.ai\\OpenWithProgids"',
            installer)
        self.assertIn('ValueName: ".ai"', installer)

    def test_app_disables_dialog_context_help_before_startup(self):
        startup = (
            ROOT / "pdfeditor" / "__main__.py"
        ).read_text(encoding="utf-8")
        setting = (
            "QApplication.setAttribute("
            "Qt.AA_DisableWindowContextHelpButton, True)")
        self.assertIn(setting, startup)
        self.assertLess(startup.index(setting), startup.index("QApplication(sys.argv)"))


if __name__ == "__main__":
    unittest.main()
