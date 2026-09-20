import tempfile
from pathlib import Path
import unittest

import fitz
from pdfeditor.core import Document
from pdfeditor.text_regions import text_lines, selected_region


class TextRegionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'text.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=400, height=400)
            page.insert_text((30, 50), 'Hello', fontsize=12)
            page.insert_text((61, 50), 'world', fontsize=12)
            page.insert_text((30, 70), 'Second line', fontsize=12)
            page.insert_text((230, 50), 'Other column', fontsize=12)
            page.draw_line((20, 30), (200, 80), color=(0, 0, 1))
            pdf.save(self.path)
        self.doc = Document(str(self.path))
        self.lines = text_lines(self.doc.spans(0))
        self.region = selected_region(self.lines, (20, 30, 150, 80))

    def tearDown(self):
        self.doc.close()
        self.temp.cleanup()

    def test_words_join_but_columns_stay_separate(self):
        self.assertEqual([s['text'] for s in self.lines],
                         ['Hello world', 'Other column', 'Second line'])
        self.assertEqual(self.region['text'], 'Hello world\nSecond line')
        self.assertEqual(len(self.region['sources']), 3)
        partial = selected_region(self.lines, (55, 30, 150, 58))
        self.assertEqual(partial['text'], 'world')

    def test_replace_wrap_save_reopen_preserves_other_content(self):
        drawings = self.doc._doc[0].get_drawings()
        self.doc.replace_text_region(0, self.region, 'A new paragraph that wraps over lines.',
            12, (0, 0, 0), fontname='helv', box=(30, 35, 150, 110))
        output = self.path.with_name('out.pdf')
        self.doc.save_as(str(output))
        with fitz.open(output) as pdf:
            text = pdf[0].get_text()
            self.assertNotIn('Hello', text)
            self.assertNotIn('Second', text)
            self.assertIn('Other column', text)
            self.assertIn('A new paragraph', text)
            self.assertEqual([{k: v for k, v in d.items() if k != 'seqno'}
                              for d in pdf[0].get_drawings()],
                             [{k: v for k, v in d.items() if k != 'seqno'} for d in drawings])
            self.assertGreater(len(pdf[0].search_for('lines.')), 0)

    def test_overflow_and_missing_font_glyph_do_not_mutate(self):
        before = self.doc._doc.tobytes(no_new_id=True)
        for text, box in [('too long ' * 100, (30, 35, 70, 50)),
                          ('한글', (30, 35, 150, 100))]:
            with self.assertRaises(ValueError):
                self.doc.replace_text_region(0, self.region, text, 12, (0, 0, 0),
                                             fontname='helv', box=box)
            self.assertEqual(self.doc._doc.tobytes(no_new_id=True), before)

    def test_rotated_page_keeps_text_in_original_coordinate_space(self):
        self.doc._doc[0].set_rotation(90)
        self.doc.replace_text_region(0, self.region, 'Replacement', 12, (0, 0, 0),
                                     fontname='helv', box=(30, 35, 150, 110))
        self.assertEqual(self.doc._doc[0].rotation, 90)
        self.assertLess(self.doc._doc[0].search_for('Replacement')[0].x0, 40)

    def test_existing_redactions_are_not_applied(self):
        self.doc._doc[0].add_redact_annot((220, 30, 350, 60))
        with self.assertRaisesRegex(ValueError, 'redactions'):
            self.doc.replace_text_region(0, self.region, 'Replacement', 12, (0, 0, 0),
                                         fontname='helv', box=(30, 35, 150, 110))
        self.assertIn('Other column', self.doc._doc[0].get_text())

    def test_overlapping_unselected_text_is_not_erased(self):
        self.doc._doc[0].insert_text((32, 50), 'Overlap', fontsize=12)
        before = self.doc._doc[0].get_text()
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            self.doc.replace_text_region(0, self.region, 'Replacement', 12, (0, 0, 0),
                                         fontname='helv', box=(30, 35, 150, 110))
        self.assertEqual(self.doc._doc[0].get_text(), before)

    def test_image_behind_text_is_retained(self):
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
        pix.clear_with(230)
        page = self.doc._doc[0]
        page.insert_image((20, 20, 180, 150), pixmap=pix, overlay=False)
        images = [self.doc._doc.extract_image(i[0])['image'] for i in page.get_images()]
        self.doc.replace_text_region(0, self.region, 'Replacement', 12, (0, 0, 0),
                                     fontname='helv', box=(30, 35, 150, 110))
        self.assertEqual(images, [self.doc._doc.extract_image(i[0])['image']
                                  for i in self.doc._doc[0].get_images()])

    def test_read_only_is_enforced(self):
        doc = Document(str(self.path), read_only=True)
        try:
            with self.assertRaises(PermissionError):
                doc.replace_text_region(0, self.region, 'Replacement', 12, (0, 0, 0))
        finally:
            doc.close()


if __name__ == '__main__':
    unittest.main()
