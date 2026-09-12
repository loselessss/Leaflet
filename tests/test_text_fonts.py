import tempfile
from pathlib import Path
import unittest
import pymupdf
from pdfeditor.core import Document


class TextFontTests(unittest.TestCase):
    def test_custom_font_is_embedded_and_missing_glyphs_do_not_erase_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output, fontfile = root/'source.pdf', root/'out.pdf', root/'font.otf'
            fontfile.write_bytes(pymupdf.Font('helv').buffer)
            with pymupdf.open() as pdf:
                page = pdf.new_page()
                page.insert_text((40, 80), 'Original')
                pdf.save(source)
            doc = Document(str(source))
            try:
                span = doc.spans(0)[0]
                with self.assertRaises(ValueError):
                    doc.replace_span(0, span['bbox'], span['origin'], '한글', 11,
                                     (0, 0, 0), fontname='helv')
                self.assertIn('Original', doc._doc[0].get_text())
                doc.replace_span(0, span['bbox'], span['origin'], 'Changed', 11,
                                 (0, 0, 1), fontfile=str(fontfile))
                doc.save_as(str(output))
            finally:
                doc.close()
            fontfile.unlink()
            with pymupdf.open(output) as pdf:
                self.assertIn('Changed', pdf[0].get_text())
                self.assertNotIn('Original', pdf[0].get_text())
                fonts = pdf[0].get_fonts()
                self.assertTrue(any(pdf.extract_font(font[0])[3] for font in fonts
                                    if font[4].startswith('spdf')))
