import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfeditor.update_service import (
    GitHubUpdateService, UpdateError, localized_release_notes)


class FakeResponse:
    def __init__(self, payload):
        self.stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, _kind, _error, _traceback):
        return False

    def read(self, size=-1):
        return self.stream.read(size)


def release_payload(tag="v1.6.1", content=b"installer", url=None,
                    body="변경 내용"):
    version = tag.lstrip("v")
    download = url or (
        "https://github.com/loselessss/Leaflet/releases/download/%s/"
        "sPDF_Setup_%s.exe" % (tag, version))
    return json.dumps({
        "tag_name": tag,
        "name": "sPDF %s" % version,
        "body": body,
        "html_url": (
            "https://github.com/loselessss/Leaflet/releases/tag/%s" % tag),
        "assets": [{
            "name": "sPDF_Setup_%s.exe" % version,
            "browser_download_url": download,
            "size": len(content),
            "digest": "sha256:%s" % hashlib.sha256(content).hexdigest(),
        }],
    }).encode("utf-8")


class UpdateServiceTests(unittest.TestCase):
    def test_localized_release_notes_selects_requested_language(self):
        body = (
            "## English\n\n<!-- spdf-release-notes:start:en -->\n"
            "English notes\n<!-- spdf-release-notes:end:en -->\n\n"
            "## 한국어\n\n<!-- spdf-release-notes:start:ko -->\n"
            "한국어 변경 내용\n<!-- spdf-release-notes:end:ko -->")
        self.assertEqual(localized_release_notes(body, "en"), "English notes")
        self.assertEqual(
            localized_release_notes(body, "ko"), "한국어 변경 내용")

    def test_legacy_release_notes_are_preserved(self):
        self.assertEqual(localized_release_notes("기존 변경 내용", "en"),
                         "기존 변경 내용")

    def test_update_uses_configured_release_note_language(self):
        body = (
            "<!-- spdf-release-notes:start:en -->English notes"
            "<!-- spdf-release-notes:end:en -->"
            "<!-- spdf-release-notes:start:ko -->한국어 변경 내용"
            "<!-- spdf-release-notes:end:ko -->")
        service = GitHubUpdateService(
            "1.6.0", language="ko",
            opener=lambda _request, timeout: FakeResponse(
                release_payload(body=body)))
        self.assertEqual(service.check().release_notes, "한국어 변경 내용")

    def test_newer_release_selects_exact_versioned_installer(self):
        service = GitHubUpdateService(
            "1.6.0", opener=lambda _request, timeout: FakeResponse(
                release_payload()))
        update = service.check()
        self.assertEqual(update.version, "1.6.1")
        self.assertEqual(update.asset.name, "sPDF_Setup_1.6.1.exe")
        self.assertEqual(len(update.asset.sha256), 64)

    def test_same_release_is_current(self):
        service = GitHubUpdateService(
            "1.6.0", opener=lambda _request, timeout: FakeResponse(
                release_payload("v1.6.0")))
        self.assertIsNone(service.check())

    def test_untrusted_asset_is_rejected(self):
        service = GitHubUpdateService(
            "1.6.0", opener=lambda _request, timeout: FakeResponse(
                release_payload(url="https://example.com/setup.exe")))
        with self.assertRaisesRegex(UpdateError, "안전하지"):
            service.check()

    def test_download_verifies_hash_and_reports_progress(self):
        content = b"verified installer"
        calls = [release_payload(content=content), content]

        def opener(_request, timeout):
            return FakeResponse(calls.pop(0))

        with tempfile.TemporaryDirectory() as temp:
            service = GitHubUpdateService(
                "1.6.0", opener=opener, download_root=Path(temp))
            update = service.check()
            progress = []
            result = service.download(update, progress=progress.append)
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(progress[-1].completed_bytes, len(content))

    def test_cleanup_removes_only_updater_temp_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "updates"
            root.mkdir()
            installer = root / "sPDF_Setup_1.6.1.exe"
            partial = root / "sPDF_Setup_1.6.2.exe.part"
            unrelated = root / "notes.txt"
            invalid = root / "other_setup.exe"
            for path in (installer, partial, unrelated, invalid):
                path.write_bytes(b"data")
            service = GitHubUpdateService("1.6.0", download_root=root)

            self.assertEqual(service.cleanup_downloads(), 2)
            self.assertFalse(installer.exists())
            self.assertFalse(partial.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(invalid.exists())

    def test_installer_launch_does_not_use_shell(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "sPDF_Setup_1.6.1.exe"
            installer.write_bytes(b"MZ")
            service = GitHubUpdateService("1.6.0")
            with patch("pdfeditor.update_service.subprocess.Popen") as popen:
                service.launch_installer(installer)
            command = popen.call_args.args[0]
            self.assertEqual(command[0], str(installer.resolve()))
            self.assertIn("/LANG=english", command)
            self.assertNotIn("shell", popen.call_args.kwargs)

    def test_korean_updater_prefers_korean_installer_language(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Path(temp) / "sPDF_Setup_1.6.1.exe"
            installer.write_bytes(b"MZ")
            service = GitHubUpdateService("1.6.0", language="ko")
            with patch("pdfeditor.update_service.subprocess.Popen") as popen:
                service.launch_installer(installer)
            self.assertIn("/LANG=korean", popen.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
