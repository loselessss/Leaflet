import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from build_legal import collect_distributions, is_notice
from create_source_bundle import (
    clean_source_status, include_source, prepare_source_release,
    source_record, write_archive,
)
from pdfeditor.meta import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class LicensingTests(unittest.TestCase):
    def test_mit_project_license_and_dependency_license_texts_are_present(self):
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(license_text.startswith("MIT License"))
        self.assertIn("Copyright (c) 2026 loselessss and contributors", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        for name in ("AGPL-3.0.txt", "GPL-3.0.txt", "LGPL-3.0.txt", "Apache-2.0.txt"):
            self.assertGreater((ROOT / "licenses" / name).stat().st_size, 10000)

    def test_exact_source_metadata_and_missing_source_fail_closed(self):
        def fetch(_url):
            return {"info": {"name": "PyMuPDF", "version": "1.2.3"}, "urls": [{
                "packagetype": "sdist", "filename": "pymupdf-1.2.3.tar.gz",
                "url": "https://files.pythonhosted.org/pymupdf-1.2.3.tar.gz",
                "digests": {"sha256": "a" * 64},
            }]}
        record = source_record({"name": "pymupdf", "version": "1.2.3"}, fetch)
        self.assertEqual(record["sha256"], "a" * 64)
        with self.assertRaisesRegex(ValueError, "mismatch"):
            source_record({"name": "pymupdf", "version": "1.2.4"}, fetch)
        with self.assertRaisesRegex(ValueError, "mapping required"):
            source_record({"name": "mystery", "version": "1"}, lambda url: {
                "info": {"name": "mystery", "version": "1"}, "urls": []})

    def test_qt_mapping_is_version_specific(self):
        def fetch(url):
            return {"info": {"name": "PyQt5-Qt5", "version": url.split("/")[-2]}, "urls": []}
        self.assertIn("qt-everywhere-src-5.15.2.tar.xz", source_record(
            {"name": "PyQt5-Qt5", "version": "5.15.2"}, fetch)["url"])
        with self.assertRaises(ValueError):
            source_record({"name": "PyQt5-Qt5", "version": "5.99.0"}, fetch)

    def test_source_excludes_companion_and_private_paths(self):
        for name in ("", ".", "paperorganizer/core.py", "paper_organizer.py", "paper_organizer.pyw",
                     "tests/test_paperlib.py", "tests/test_paper_settings.py",
                     "docs/PAPER_ORGANIZER_INTEGRATION.md", "test/private.pdf",
                     "../secret", "/absolute", "dir\\escape", "Output/setup.exe"):
            self.assertFalse(include_source(name), name)
        for name in ("pdfeditor/page_organizer.py", "tests/test_thumbnails.py", "LICENSE", ".github/workflows/release.yml"):
            self.assertTrue(include_source(name), name)

    def test_only_regenerated_icons_can_differ_from_tag(self):
        self.assertTrue(clean_source_status(b""))
        self.assertTrue(clean_source_status(b" M assets/spdf.ico\n M assets/spdf_doc.ico\n"))
        self.assertFalse(clean_source_status(b" M make_icons.py\n"))
        self.assertFalse(clean_source_status(b"?? private.txt\n"))
        self.assertFalse(clean_source_status(b"M  assets/spdf.ico\n"))
        self.assertTrue(clean_source_status(b" M native/bin/spdf_d2d_renderer.dll\n"))
        self.assertFalse(clean_source_status(b" M native/d2d_renderer/spdf_d2d.cpp\n"))
        self.assertFalse(include_source("native/bin/spdf_d2d_renderer.dll"))
        self.assertTrue(include_source("native/d2d_renderer/spdf_d2d.cpp"))

    def test_wheel_only_projects_use_upstream_release_tags(self):
        for name, version, upstream in (("rapidocr", "3.9.2", "RapidAI/RapidOCR"),
                                        ("flatbuffers", "25.12.19", "google/flatbuffers"),
                                        ("onnxruntime", "1.29.0", "microsoft/onnxruntime")):
            record = source_record({"name": name, "version": version}, lambda url: {
                "info": {"name": name, "version": version}, "urls": []})
            self.assertIn(upstream + "/archive/refs/tags/v" + version, record["url"])

    def test_source_archive_and_notices_round_trip_without_overwrite(self):
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("run.py", "print('test')")
            archive.writestr("paperorganizer/core.py", "not part of sPDF")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legal = root / "legal"
            legal.mkdir()
            (legal / "build-requirements.txt").write_text("PyQt5==5.15.11\n", encoding="utf-8")
            destination = root / "source.zip"
            write_archive(destination, source.getvalue(), legal, "source directions", [], APP_VERSION)
            prefix = "sPDF-%s/" % APP_VERSION
            with zipfile.ZipFile(destination) as archive:
                self.assertIn(prefix + "run.py", archive.namelist())
                self.assertNotIn(prefix + "paperorganizer/core.py", archive.namelist())
                self.assertEqual(archive.read(prefix + "DEPENDENCY_SOURCES.md"), b"source directions")
                self.assertEqual(json.loads(archive.read(prefix + "dependency-sources.json")), [])
                self.assertIn(prefix + "third-party/build-requirements.txt", archive.namelist())
            before = destination.read_bytes()
            with self.assertRaises(FileExistsError):
                write_archive(destination, source.getvalue(), legal, "new", [], APP_VERSION)
            self.assertEqual(destination.read_bytes(), before)

    def test_release_refuses_dirty_checkout_or_wrong_version(self):
        with patch("create_source_bundle.subprocess.check_output", return_value=b" M LICENSE\n"):
            with self.assertRaisesRegex(ValueError, "clean working tree"):
                prepare_source_release(ROOT, APP_VERSION)
        with self.assertRaisesRegex(ValueError, "version"):
            prepare_source_release(ROOT, "0.0.0")

    def test_release_bundle_matches_tag_inventory_and_checksum(self):
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("run.py", "# tagged source")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legal = root / "build" / "legal"
            legal.mkdir(parents=True)
            environment = {"commit": "abc123", "app_version": APP_VERSION, "python": "3.12.10",
                           "packages": [{"name": name, "version": "1.0.0"}
                                        for name in ("pymupdf", "PyQt5", "PyQt5-Qt5")]}
            inventory = legal / "build-environment.json"
            inventory.write_text(json.dumps(environment), encoding="utf-8")
            def git(command, **kwargs):
                if command[1] == "status":
                    return b""
                if command[1] == "archive":
                    return source.getvalue()
                return b"abc123\n"
            def record(package):
                return dict(package, url="https://example.org/source.tar.gz", sha256="a" * 64)
            with patch("create_source_bundle.subprocess.check_output", side_effect=git), \
                    patch("create_source_bundle.source_record", side_effect=record), \
                    patch("create_source_bundle.check_source_access") as check:
                result = prepare_source_release(root, APP_VERSION)
                self.assertEqual(check.call_count, 4)  # Three dependencies and Python.
                checksum = Path(str(result) + ".sha256").read_text(encoding="ascii")
                self.assertEqual(checksum.split()[0], hashlib.sha256(result.read_bytes()).hexdigest())
                self.assertTrue((root / "Output" / ("sPDF_Dependency_Sources_%s.md" % APP_VERSION)).is_file())
                environment["commit"] = "old-build"
                inventory.write_text(json.dumps(environment), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "different build"):
                    prepare_source_release(root, APP_VERSION)

    def test_notices_keep_original_bytes_and_build_versions(self):
        self.assertTrue(is_notice("package/THIRD_PARTY_NOTICES.txt"))
        self.assertFalse(is_notice("package/module.py"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "LICENSE"
            original.write_bytes(b"Copyright Example\r\nOriginal terms\r\n")
            class FakeDistribution:
                metadata = {"Name": "Example", "License": "MIT"}
                version = "1.2.3"
                files = ["LICENSE"]
                def locate_file(self, entry):
                    return root / entry
                def read_text(self, name):
                    return "Name: Example\nVersion: 1.2.3\n"
            target = root / "output"
            packages = collect_distributions([FakeDistribution()], target)
            self.assertEqual(packages[0]["version"], "1.2.3")
            self.assertEqual((target / packages[0]["notices"][0]).read_bytes(), original.read_bytes())

    def test_workflow_packages_sources_before_publication(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("python create_source_bundle.py"), workflow.index("gh release create"))
        self.assertIn('$sourceArchive "$sourceArchive.sha256" $dependencySources', workflow)
        self.assertIn("Output/sPDF_Source_*.zip", workflow)
        spec = (ROOT / "spdf.spec").read_text(encoding="utf-8")
        self.assertIn("write_legal_bundle", spec)
        self.assertIn("datas=ocr_datas + legal_datas", spec)
        installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        self.assertIn("LicenseFile=LICENSE", installer)
        self.assertIn('DestDir: "{app}\\third-party"', installer)


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 is required")
class LicenseDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_offline_texts_and_versioned_link_in_both_languages(self):
        from pdfeditor.i18n import set_language
        from pdfeditor.license_dialog import LicenseDialog, source_url
        try:
            for language, text in (("ko", "어떠한 보증"), ("en", "WITHOUT ANY WARRANTY")):
                set_language(language)
                dialog = LicenseDialog()
                self.assertEqual(dialog.tabs.count(), 8)
                self.assertIn(text, dialog.tabs.widget(0).toPlainText())
                self.assertIn("MIT License", dialog.tabs.widget(0).toPlainText())
                self.assertIn("/releases/tag/v" + APP_VERSION, source_url())
                self.assertIn(source_url(), dialog.tabs.widget(0).toHtml())
                self.assertIn("Permission is hereby granted", dialog.tabs.widget(1).toPlainText())
                self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", dialog.tabs.widget(3).toPlainText())
                dialog.close()
                dialog.deleteLater()
                self.app.processEvents()
        finally:
            set_language("en")

    def test_missing_license_is_reported_without_network_fallback(self):
        from pdfeditor.license_dialog import LicenseDialog
        with patch("pdfeditor.license_dialog.resource", return_value="/missing-spdf-license.txt"):
            dialog = LicenseDialog()
            self.assertIn("missing", dialog.tabs.widget(1).toPlainText())
            dialog.close()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
