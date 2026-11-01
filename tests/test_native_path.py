import unittest
from unittest.mock import patch
import pymupdf
from pymupdf import mupdf as m
from pdfeditor import gpu_raster as g
from pdfeditor import mupdf_path as bridge
from pdfeditor.d2d_backend import _path_array
from pdfeditor.scene_transfer import PackedCommands


@unittest.skipUnless(bridge._library() is not None, 'Native MuPDF bridge not built')
class NativePathTests(unittest.TestCase):
    def test_native_text_skips_python_span_iteration_and_preserves_clip(self):
        if not hasattr(bridge._library(), 'leaflet_text_scan'):
            self.skipTest('Native text bridge not built')
        with pymupdf.open() as document:
            page=document.new_page()
            page.insert_text((50,80),'Native text with spaces and repeated glyphs')
            page.insert_text((150,220),'Rotated text',rotate=90)
            page.insert_text((50,300),'Text clip',render_mode=7)
            expected=g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True)
            with patch.object(g._mupdf.FzTextSpan,'__init__',side_effect=AssertionError('Python span')):
                actual=g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True,native_text=True)
            self.assertTrue(actual.supported,actual.reason)
            self.assertEqual(actual,expected)

    def test_unavailable_native_text_uses_original_iteration(self):
        with pymupdf.open() as document:
            page=document.new_page();page.insert_text((50,80),'Fallback text')
            expected=g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True)
            with patch.object(bridge,'scan_text',return_value=None):
                self.assertEqual(g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True,
                                                          native_text=True),expected)

    def test_version_mismatch_disables_bridge(self):
        from types import SimpleNamespace
        def version():
            return b'0.0.0-mismatch'
        bridge._library.cache_clear()
        try:
            with patch.object(bridge.ctypes, 'PyDLL', return_value=SimpleNamespace(leaflet_path_version=version)):
                self.assertIsNone(bridge._library())
        finally:
            bridge._library.cache_clear()

    def test_path_shapes_empty_rectangles_and_curves_match(self):
        paths = [m.FzPath()]
        path=m.FzPath(); path.fz_moveto(-0., -12.5); path.fz_lineto(3., 4.)
        path.fz_curveto(1.,2.,3.,4.,5.,6.);path.fz_closepath();paths.append(path)
        rectangle=m.FzPath();rectangle.fz_rectto(-1.,-2.,30.,40.);paths.append(rectangle)
        for path in paths:
            expected=g._path_commands(path,allow_empty=True)
            actual=bridge.walk_path(path)
            self.assertIsInstance(actual,PackedCommands)
            self.assertEqual(tuple(actual),expected)
            if expected:
                self.assertEqual(bytes(_path_array(actual)),bytes(_path_array(expected)))

    def test_page_extraction_does_not_invoke_python_coordinate_callbacks(self):
        with pymupdf.open() as document:
            page=document.new_page();page.insert_text((50,80),'Native glyph outlines')
            page.draw_rect((10,100,90,160),fill=(.2,.3,.4))
            expected=g.vector_page_from_pymupdf(page,packed_paths=True)
            with patch.object(g._PathWalker,'__init__',side_effect=AssertionError('Python walker')):
                actual=g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True)
            self.assertTrue(actual.supported,actual.reason)
            self.assertEqual(actual,expected)

    def test_missing_bridge_keeps_original_path(self):
        with pymupdf.open() as document:
            page=document.new_page();page.insert_text((50,80),'Fallback')
            expected=g.vector_page_from_pymupdf(page,packed_paths=True)
            with patch.object(bridge,'_library',return_value=None):
                self.assertEqual(g.vector_page_from_pymupdf(page,packed_paths=True,native_paths=True),expected)
