import unittest

from pdfeditor.i18n import (
    SUPPORTED_LANGUAGES, localize, localize_qt_standard_button,
    set_language, tr,
)


class InternationalEditionTests(unittest.TestCase):
    def setUp(self):
        set_language("en")

    def test_first_international_language_is_english(self):
        self.assertEqual(SUPPORTED_LANGUAGES, ("en", "ko"))
        self.assertEqual(tr("파일(&F)"), "&File")
        self.assertEqual(
            tr("페이지 구성(&P)"), "Page &Organization")
        self.assertEqual(tr("페이지 구성..."), "Organize Pages...")
        self.assertEqual(
            tr("PDF/Illustrator 파일 열기..."),
            "Open PDF/Illustrator File...")
        self.assertEqual(tr("PDF 파일 열기..."), "Open PDF File...")
        self.assertIn(
            "PDF/Illustrator Files (*.pdf *.ai)",
            tr("PDF/Illustrator 파일 (*.pdf *.ai);;PDF 파일 (*.pdf);;"
               "Illustrator 파일 (*.ai)"))
        self.assertEqual(tr("PDF 용량 줄이기..."), "Reduce PDF Size...")
        self.assertEqual(tr("페이지 미리보기"), "Page Thumbnails")
        self.assertEqual(tr("책갈피"), "Bookmarks")
        self.assertEqual(tr("지원하지 않는 링크"), "Unsupported Link")
        self.assertEqual(tr("현재 페이지 책갈피 추가"),
                         "Bookmark Current Page")
        self.assertEqual(tr("페이지 여백 자르기..."),
                         "Crop Page Margins...")
        self.assertEqual(tr("미저장 작업 복구..."),
                         "Recover Unsaved Work...")

    def test_dynamic_ui_messages_are_translated(self):
        self.assertEqual(tr("12쪽"), "Page 12")
        self.assertEqual(
            tr("3개 단어 선택 — Ctrl+C로 복사"),
            "3 words selected — press Ctrl+C to copy")
        self.assertEqual(tr("저장됨: C:\\paper.pdf"),
                         "Saved: C:\\paper.pdf")

    def test_document_content_is_not_changed(self):
        text = "이 문장은 PDF 본문입니다."
        self.assertEqual(tr(text), text)

    def test_artboard_command_and_help_exist_in_both_languages(self):
        from pdfeditor.help import HELP_HTML, HELP_HTML_EN
        self.assertEqual(tr("아트보드"), "Artboards")
        set_language("ko")
        self.assertEqual(tr("아트보드"), "아트보드")
        for guide in (HELP_HTML, HELP_HTML_EN):
            self.assertIn("Ctrl+Shift+A", guide)

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(set_language("fr-FR"), "en")
        self.assertEqual(tr("저장"), "Save")

    def test_korean_mode_preserves_source_messages(self):
        self.assertEqual(set_language("ko"), "ko")
        self.assertEqual(tr("저장"), "저장")
        self.assertEqual(localize("English", "한국어"), "한국어")

    def test_qt_standard_save_discard_buttons_follow_korean_ui(self):
        set_language("ko")
        self.assertEqual(localize_qt_standard_button("Save"), "저장")
        self.assertEqual(
            localize_qt_standard_button("Discard"), "저장 안 함")
        self.assertEqual(localize_qt_standard_button("Cancel"), "취소")

if __name__ == "__main__":
    unittest.main()
