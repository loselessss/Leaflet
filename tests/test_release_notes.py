import tempfile
import unittest
from pathlib import Path

from release_notes import (
    STABLE_CHANNEL_NOTICES, STORE_URL,
    compose_localized_documents, compose_localized_release_notes,
    extract_release_notes, main)


SAMPLE = """# 변경 이력

## 1.7.2 - 2026-08-03

### 개선

- 프로세스 표시를 정리했습니다.

### 버그 수정

- 종료 처리를 보강했습니다.

## 1.7.1 - 2026-08-01

### 개선

- 선택 기능을 개선했습니다.
"""

SAMPLE_EN = SAMPLE.replace("# 변경 이력", "# Changelog").replace(
    "### 개선", "### Improvements").replace(
    "프로세스 표시를 정리했습니다.", "Improved process display.").replace(
    "### 버그 수정", "### Bug fixes").replace(
    "종료 처리를 보강했습니다.", "Improved shutdown handling.").replace(
    "선택 기능을 개선했습니다.", "Improved selection.")


class ReleaseNotesTests(unittest.TestCase):
    def test_extracts_only_requested_version_body(self):
        notes = extract_release_notes(SAMPLE, "1.7.2")
        self.assertIn("### 개선", notes)
        self.assertIn("종료 처리를 보강", notes)
        self.assertNotIn("1.7.1", notes)
        self.assertNotIn("선택 기능", notes)

    def test_missing_version_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "1.8.0"):
            extract_release_notes(SAMPLE, "1.8.0")

    def test_cli_writes_utf8_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            changelog = root / "CHANGELOG.md"
            output = root / "notes.md"
            changelog.write_text(SAMPLE, encoding="utf-8")
            main(["--version", "1.7.2", "--changelog", str(changelog),
                  "--output", str(output)])
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                extract_release_notes(SAMPLE, "1.7.2"))

    def test_composes_bilingual_release_body(self):
        notes = compose_localized_release_notes("1.7.2", SAMPLE_EN, SAMPLE)
        self.assertIn("spdf-release-notes:start:en", notes)
        self.assertIn("Improved shutdown handling.", notes)
        self.assertIn("spdf-release-notes:start:ko", notes)
        self.assertIn("종료 처리를 보강했습니다.", notes)

    def test_cli_writes_bilingual_release_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english = root / "CHANGELOG.md"
            korean = root / "CHANGELOG.ko.md"
            output = root / "notes.md"
            english.write_text(SAMPLE_EN, encoding="utf-8")
            korean.write_text(SAMPLE, encoding="utf-8")
            main(["--version", "1.7.2", "--changelog", str(english),
                  "--changelog-ko", str(korean), "--output", str(output)])
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                compose_localized_release_notes("1.7.2", SAMPLE_EN, SAMPLE))

    def test_each_version_recommends_store_inside_both_language_sections(self):
        from pdfeditor.update_service import localized_release_notes
        for version in ("1.7.2", "1.7.1"):
            body = compose_localized_documents(version, SAMPLE_EN, SAMPLE)
            for language in ("en", "ko"):
                notes = localized_release_notes(body, language)
                self.assertIn(STABLE_CHANNEL_NOTICES[language], notes)
                self.assertEqual(notes.count(STORE_URL), 1)

    def test_existing_store_guidance_is_not_duplicated(self):
        english = SAMPLE_EN.replace("Improved shutdown handling.",
            "Improved shutdown handling.\n\n" + STABLE_CHANNEL_NOTICES["en"])
        korean = SAMPLE.replace("종료 처리를 보강했습니다.",
            "종료 처리를 보강했습니다.\n\n" + STABLE_CHANNEL_NOTICES["ko"])
        body = compose_localized_documents("1.7.2", english, korean)
        self.assertEqual(body.count(STORE_URL), 2)

    def test_release_documents_exclude_previous_versions(self):
        notes = compose_localized_documents(
            "1.7.2", SAMPLE_EN, SAMPLE)
        self.assertIn("Improved shutdown handling.", notes)
        self.assertIn("종료 처리를 보강했습니다.", notes)
        self.assertNotIn("1.7.1", notes)
        self.assertNotIn("Improved selection.", notes)
        self.assertNotIn("선택 기능", notes)
        self.assertIn("spdf-release-notes:start:ko", notes)

    def test_release_workflow_cli_excludes_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english, korean, output = (root / name for name in ('en.md', 'ko.md', 'out.md'))
            english.write_text(SAMPLE_EN, encoding='utf-8')
            korean.write_text(SAMPLE, encoding='utf-8')
            main(['--version', '1.7.2', '--release-notes', str(english),
                  '--release-notes-ko', str(korean), '--output', str(output)])
            self.assertEqual(output.read_text(encoding='utf-8'),
                             compose_localized_release_notes('1.7.2', SAMPLE_EN, SAMPLE))

    def test_complete_release_documents_require_current_version(self):
        with self.assertRaisesRegex(ValueError, "1.7.2"):
            compose_localized_documents(
                "1.7.2", "## 1.7.1 Highlights", "## 1.7.1 주요 변경")


if __name__ == "__main__":
    unittest.main()
