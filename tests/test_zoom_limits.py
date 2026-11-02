"""3200% display input, DPI conversion, bounded preparation and sharp curves."""
import ctypes
import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
from pdfeditor.reader_view import ReaderPageView
from pdfeditor.widgets import PageView
from pdfeditor.artboards import ArtboardView
from pdfeditor.zoom_limits import actual_size_scale, MAX_RASTER_SCALE, MAX_SAVED_ZOOM
from tests import test_editor_workspace as fixtures


class ZoomLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_display_maximum_tracks_physical_dpi_in_all_views(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            view = kind(use_opengl=False) if kind is ReaderPageView else kind()
            try:
                for dpi in (72, 96, 144, 192):
                    with self.subTest(view=kind.__name__, dpi=dpi), \
                            patch.object(view.viewport(), 'physicalDpiX', return_value=dpi):
                        self.assertAlmostEqual(view.ZOOM_MAX / actual_size_scale(view) * 100, 3200)
            finally:
                view.close()
                view.deleteLater()
        self.app.processEvents()

    def test_native_preparation_scale_stays_within_its_64x_contract(self):
        view = ReaderPageView(use_opengl=False)
        try:
            for dpi in (72, 96, 144, 192):
                for dpr in (1, 2, 4):
                    with patch.object(view.viewport(), 'physicalDpiX', return_value=dpi), \
                            patch.object(view.viewport(), 'devicePixelRatioF', return_value=dpr):
                        view.zoom = view.ZOOM_MAX
                        expected = min(2 ** math.ceil(math.log2(view.zoom * dpr)), MAX_RASTER_SCALE)
                        self.assertEqual(view._vector_raster_scale(), expected)
        finally:
            view.close()
            view.deleteLater()
        self.app.processEvents()

    def test_saved_raw_zoom_preserves_dpi_scaled_3200_percent(self):
        from pdfeditor.settings import _clean_reading_position
        for dpi in (72, 96, 144, 192):
            zoom = 32 * dpi / 72
            self.assertEqual(_clean_reading_position(dict(page=0, zoom=zoom))['zoom'], zoom)
        self.assertEqual(_clean_reading_position(dict(page=0, zoom=1e100))['zoom'], MAX_SAVED_ZOOM)
        self.assertIsNone(_clean_reading_position(dict(page=0, zoom=float('inf'))))


class WindowZoomLimitTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditorWorkspaceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.EditorWorkspaceTests.tearDownClass.__func__)
    setUp = fixtures.EditorWorkspaceTests.setUp
    tearDown = fixtures.EditorWorkspaceTests.tearDown
    settle = fixtures.EditorWorkspaceTests.settle
    open_editor = fixtures.EditorWorkspaceTests.open_editor

    def test_percent_input_reaches_3200_on_different_dpi_and_keeps_tiles_bounded(self):
        from pdfeditor.reader_view import MAX_VISIBLE_TILES, TILE_PIXELS
        tab = self.open_editor()
        tab.view._d2d_requested = False  # Exercise the CPU fallback tile consumer too.
        for dpi in (72, 96, 144, 192):
            with self.subTest(dpi=dpi), \
                    patch.object(tab.view.viewport(), 'physicalDpiX', return_value=dpi), \
                    patch.object(tab.doc, 'render', side_effect=AssertionError('full-page zoom raster')):
                tab._update_page_label()
                self.assertEqual(tab._zoom_input.maximum(), 3200)
                tab._zoom_input.setValue(3199)
                tab._zoom_input.setValue(3200)
                self.assertAlmostEqual(tab.zoom_percent(), 3200)
                self.assertAlmostEqual(tab.view.zoom, 32*dpi/72)
                tab.view._plan_tiles()
                self.assertLessEqual(len(tab.view._wanted), MAX_VISIBLE_TILES)
                while tab.view._pending:
                    tab.view._render_next_tile()
                    tab.view._tile_timer.stop()
                for pixmap, _rect in tab.view._tiles.values():
                    self.assertLessEqual(pixmap.width(), TILE_PIXELS+3)
                    self.assertLessEqual(pixmap.height(), TILE_PIXELS+3)
                tab.set_zoom_percent(4000)
                self.assertAlmostEqual(tab.zoom_percent(), 3200)

    def test_fine_zoom_and_reading_position_preserve_3200(self):
        from pdfeditor import settings
        tab = self.open_editor()
        tab.set_zoom_percent(3200)
        tab.zoom_in_fine()
        self.assertAlmostEqual(tab.zoom_percent(), 3200)
        tab.zoom_out_fine()
        self.assertAlmostEqual(tab.zoom_percent(), 3199)
        tab.set_zoom_percent(3200)
        tab.save_reading_position()
        self.assertAlmostEqual(settings.reading_position(tab.doc.path)['zoom'], tab.view.zoom)

    def test_artboard_uses_same_percent_limit_without_large_previews(self):
        from pdfeditor.artboards import PREVIEW_MAX_PIXELS
        tab = self.open_editor()
        tab.show_editor_overview()
        tab.set_zoom_percent(3200)
        self.assertAlmostEqual(tab.zoom_percent(), 3200)
        self.assertEqual(tab._zoom_input.maximum(), 3200)
        view = tab._artboard_view
        tier, scale = view._preview_request(0)
        size = tab.doc.page_size(0)
        self.assertLessEqual(tier, 1000)
        self.assertLessEqual(size[0]*size[1]*scale*scale, PREVIEW_MAX_PIXELS+1e-6)


@unittest.skipUnless(os.name == 'nt', 'Direct2D requires Windows')
class HighZoomCurveTests(unittest.TestCase):
    def test_small_cached_curve_stays_round_at_high_zoom_and_high_dpi(self):
        from pdfeditor.d2d_backend import D2DSurface
        user32 = ctypes.WinDLL('user32')
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,
            ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        hwnd = user32.CreateWindowExW(0,'STATIC','high zoom curve',0,0,0,512,512,None,None,None,None)
        self.assertTrue(hwnd)
        k = 3*.5522847498307936
        commands = [('move',7,4),('cubic',7,4+k,4+k,7,4,7),
            ('cubic',4-k,7,1,4+k,1,4),('cubic',1,4-k,4-k,1,4,1),
            ('cubic',4+k,1,7,4-k,7,4),('close',)]
        try:
            for dpi, scale in ((96,64),(192,32)):
                with self.subTest(dpi=dpi), D2DSurface(hwnd,512,512,dpi) as surface:
                    path = surface.create_path(commands)
                    scene = surface.create_scene(8,8,(('path',path,0xff000000,None,1.,None,None),))
                    # Prime the normal-scale command list before enlarging it.
                    surface.begin_frame(0xffffffff)
                    surface.draw_scene(scene,(1,0,0,1,0,0))
                    surface.end_frame()
                    surface.begin_frame(0xffffffff)
                    surface.draw_scene(scene,(scale,0,0,scale,0,0))
                    pixels = surface.read_pixels_bgra(512,512)
                    surface.end_frame()
                    # A circle is an independent geometric reference. Pixels
                    # safely inside/outside it must not show coarse chords.
                    for i in range(128):
                        angle = i*math.tau/128
                        for radius, expected in ((190,0),(194,255)):
                            x = round(256+radius*math.cos(angle)-.5)
                            y = round(256+radius*math.sin(angle)-.5)
                            value = pixels[(y*512+x)*4]
                            self.assertLessEqual(abs(value-expected), 8, (dpi,i,radius,value))
                    # Integrating antialiased coverage measures the right edge
                    # against an analytic circle without assuming a tessellator.
                    # The cubic circle itself differs by at most ~0.06 px here.
                    for y in range(150,362):
                        covered = sum((255-pixels[(y*512+x)*4])/255 for x in range(256,512))
                        ideal = math.sqrt(192**2-(y+.5-256)**2)
                        self.assertLessEqual(abs(covered-ideal), .5, (dpi,y,covered,ideal))
                    scene.close()
                    path.close()
        finally:
            user32.DestroyWindow(hwnd)
