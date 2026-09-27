import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import fitz

from pdfeditor.core import Document
from pdfeditor.document_snapshot import DocumentSnapshot
from pdfeditor.eps import convert_eps, find_ghostscript
from pdfeditor.filetypes import is_supported_document, suggested_pdf_path


EPS = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 120 80\n0 1 0 setrgbcolor\n10 10 100 60 rectfill\nshowpage\n%%EOF\n"


class EpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "drawing.EPS"
        self.source.write_bytes(EPS)

    def fake_conversion(self, source, destination):
        self.assertEqual(Path(source).read_bytes(), EPS)
        with fitz.open() as doc:
            doc.new_page(width=120, height=80).insert_text((10, 30), "EPS text")
            doc.save(destination)

    def test_document_conversion_save_and_source_preservation(self):
        self.assertTrue(is_supported_document(self.source))
        self.assertEqual(suggested_pdf_path(self.source), str(self.source.with_suffix('.pdf')))
        with patch('pdfeditor.eps.convert_eps', side_effect=self.fake_conversion):
            doc = Document(str(self.source))
        self.addCleanup(doc.close)
        self.assertEqual(doc.page_count, 1)
        self.assertIn('EPS text', doc._doc[0].get_text())
        self.assertTrue(doc.render(0)[3])
        with self.assertRaises(ValueError):
            doc.save_as(str(self.source))
        output = self.source.with_suffix('.pdf')
        doc.save_as(str(output))
        with fitz.open(output) as reopened:
            self.assertEqual(tuple(reopened[0].rect), (0, 0, 120, 80))
        self.assertEqual(self.source.read_bytes(), EPS)

    def test_failed_conversion_cleans_private_files(self):
        directories = []
        def fail(source, destination):
            directories.append(Path(destination).parent)
            raise RuntimeError('bad EPS')
        with patch('pdfeditor.eps.convert_eps', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'bad EPS'):
                DocumentSnapshot(self.source)
        self.assertTrue(directories)
        self.assertFalse(directories[0].exists())
        self.assertEqual(self.source.read_bytes(), EPS)

    def test_missing_engine_and_timeout_are_actionable(self):
        with patch('pdfeditor.eps.shutil.which', return_value=None), \
                patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'Install Ghostscript'):
                find_ghostscript()
        with patch('pdfeditor.eps.find_ghostscript', return_value='gswin64c.exe'), \
                patch('pdfeditor.eps.subprocess.run', side_effect=subprocess.TimeoutExpired('gs', 120)):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                convert_eps(self.source, self.source.with_suffix('.pdf'))

    def test_converter_uses_safe_arguments_and_rejects_failure(self):
        output = self.source.with_suffix('.pdf')
        with patch('pdfeditor.eps.find_ghostscript', return_value='gswin64c.exe'), \
                patch('pdfeditor.eps.subprocess.run', return_value=subprocess.CompletedProcess([], 1)) as run, \
                patch.dict(os.environ, {'GS_OPTIONS': '-dNOSAFER'}):
            with self.assertRaisesRegex(RuntimeError, 'Unable to convert'):
                convert_eps(self.source, output)
        args, kwargs = run.call_args
        self.assertIn('-dSAFER', args[0])
        self.assertIn('-dEPSCrop', args[0])
        self.assertEqual(args[0][-2:], ['-f', str(self.source.resolve())])
        self.assertNotIn('GS_OPTIONS', kwargs['env'])
        self.assertEqual(kwargs['timeout'], 120)

    def test_real_ghostscript_bounding_box_and_render(self):
        try:
            find_ghostscript()
        except RuntimeError:
            self.skipTest('Ghostscript is not installed')
        doc = Document(str(self.source))
        self.addCleanup(doc.close)
        self.assertEqual(tuple(doc._doc[0].rect), (0, 0, 120, 80))
        pix = doc._doc[0].get_pixmap()
        self.assertEqual(pix.pixel(60, 40)[:3], (0, 255, 0))
        self.assertEqual(self.source.read_bytes(), EPS)
