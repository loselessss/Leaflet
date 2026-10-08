import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from create_release_bundle import prepare_release_bundle


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.output = Path(self.directory.name)
        self.version = "1.35.0"
        self.source = self.output / "Leaflet_Source_1.35.0.zip"
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("Leaflet-1.35.0/run.py", "# matching tagged source")
        for name in ("Leaflet_Setup_1.35.0.exe", "Leaflet_Setup_latest.exe"):
            (self.output / name).write_bytes(b"matching installer")
        for path in (self.source, self.output / "Leaflet_Setup_1.35.0.exe",
                     self.output / "Leaflet_Setup_latest.exe"):
            self.checksum(path)
        (self.output / "Leaflet_Dependency_Sources_1.35.0.md").write_text("Exact-version sources", encoding="utf-8")

    def tearDown(self):
        self.directory.cleanup()

    def checksum(self, path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        Path(str(path) + ".sha256").write_text(digest + "  " + path.name + "\n", encoding="ascii")

    def test_archive_contains_only_matching_supporting_files(self):
        (self.output / "private.pdf").write_bytes(b"not a release asset")
        (self.output / "Leaflet_Source_0.0.1.zip").write_bytes(b"old release")
        (self.output / "sPDF_Setup_1.35.0.exe").write_bytes(b"legacy installer")
        result = prepare_release_bundle(self.output, self.version)
        with zipfile.ZipFile(result) as archive:
            self.assertEqual(set(archive.namelist()), {
                "Leaflet_Source_1.35.0.zip", "Leaflet_Source_1.35.0.zip.sha256",
                "Leaflet_Dependency_Sources_1.35.0.md",
                "Leaflet_Setup_1.35.0.exe.sha256", "Leaflet_Setup_latest.exe.sha256"})
            self.assertEqual(archive.read(self.source.name), self.source.read_bytes())
            self.assertIsNone(archive.testzip())

    def test_corrupt_source_checksum_stops_bundle_creation(self):
        self.source.write_bytes(b"changed source")
        with self.assertRaisesRegex(ValueError, "checksum"):
            prepare_release_bundle(self.output, self.version)
        self.assertFalse((self.output / "Leaflet_Release_Files_1.35.0.zip").exists())

    def test_missing_guide_and_wrong_latest_installer_stop_publication(self):
        guide = self.output / "Leaflet_Dependency_Sources_1.35.0.md"
        guide.unlink()
        with self.assertRaises(FileNotFoundError):
            prepare_release_bundle(self.output, self.version)
        guide.write_text("sources", encoding="utf-8")
        latest = self.output / "Leaflet_Setup_latest.exe"
        latest.write_bytes(b"different version")
        self.checksum(latest)
        with self.assertRaisesRegex(ValueError, "Latest installer"):
            prepare_release_bundle(self.output, self.version)

    def test_existing_bundle_is_preserved(self):
        result = prepare_release_bundle(self.output, self.version)
        original = result.read_bytes()
        with self.assertRaises(FileExistsError):
            prepare_release_bundle(self.output, self.version)
        self.assertEqual(result.read_bytes(), original)
