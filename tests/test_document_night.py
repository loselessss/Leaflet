import ctypes
import os
from pathlib import Path
import unittest
from unittest.mock import Mock

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication

from pdfeditor.document_night import build_plan, NightDisplay


class DocumentNightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def paper(self):
        image = QImage(400, 500, QImage.Format_RGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        painter.fillRect(40, 40, 120, 2, Qt.black)
        painter.fillRect(40, 220, 180, 140, QColor('#202020'))
        painter.fillRect(80, 270, 50, 2, Qt.white)
        painter.fillRect(260, 60, 100, 100, Qt.white)
        painter.fillRect(260, 60, 100, 30, Qt.red)
        painter.fillRect(260, 130, 100, 30, Qt.blue)
        painter.end()
        return QPixmap.fromImage(image)

    def test_bright_paper_text_photographs_and_dark_boxes(self):
        source = self.paper()
        plan = build_plan(source, (400, 500), [(260, 60, 360, 160)])
        self.assertIsNotNone(plan)
        display = NightDisplay()
        result = display.pixmap(source, (0, 0, 400, 500), plan).toImage()
        self.assertLess(result.pixelColor(20, 20).lightness(), 70)
        self.assertGreater(result.pixelColor(90, 41).lightness(), 180)
        self.assertEqual(result.pixelColor(80, 250), QColor('#202020'))
        self.assertGreater(result.pixelColor(100, 271).lightness(), 240)
        before = source.toImage()
        for x, y in ((280, 75), (300, 100), (300, 145)):
            self.assertEqual(result.pixelColor(x, y), before.pixelColor(x, y))
        self.assertEqual(before.pixelColor(20, 20), QColor(Qt.white))

    def test_already_dark_page_and_full_page_photograph_are_unchanged(self):
        dark = QPixmap(400, 500)
        dark.fill(QColor('#202020'))
        self.assertIsNone(build_plan(dark, (400, 500)))
        photo = self.paper()
        self.assertIsNone(build_plan(photo, (400, 500), [(0, 0, 400, 500)]))

    def test_paper_like_full_page_scan_can_be_darkened(self):
        image = QImage(400, 500, QImage.Format_RGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        for top in range(30, 460, 20):
            painter.fillRect(40, top, 280, 2, Qt.black)
        painter.end()
        self.assertIsNotNone(build_plan(QPixmap.fromImage(image), (400, 500), [(0, 0, 400, 500)]))

    def test_analysis_and_cpu_transforms_are_cached(self):
        source = self.paper()
        document = Mock(render_generation=1)
        document.display_image_regions.return_value = []
        display = NightDisplay()
        first = display.plan(document, 0, source, (400, 500))
        self.assertIs(display.plan(document, 0, source, (400, 500)), first)
        document.display_image_regions.assert_called_once()
        transformed = display.pixmap(source, (0, 0, 400, 500), first)
        self.assertIs(display.pixmap(source, (0, 0, 400, 500), first), transformed)
        document.render_generation = 2
        self.assertIsNot(display.plan(document, 0, source, (400, 500)), first)

    def test_bold_text_remains_readable_and_subpixel_images_do_not_disable_mode(self):
        source = self.paper()
        painter = QPainter(source)
        painter.setPen(Qt.NoPen)
        # Font-independent bold O-shaped glyphs (the Windows offscreen backend
        # can omit system-font text entirely).
        for x in range(25, 325, 25):
            painter.setBrush(Qt.black)
            painter.drawEllipse(x, 171, 18, 24)
            painter.setBrush(Qt.white)
            painter.drawEllipse(x+5, 176, 8, 14)
        painter.end()
        plan = build_plan(source, (400, 500), [(200, 200, 200.001, 200.001)])
        self.assertIsNotNone(plan)
        after = NightDisplay().pixmap(source, (0, 0, 400, 500), plan).toImage()
        before = source.toImage()
        dark_text = [(x,y) for y in range(175,195) for x in range(25,330)
                     if before.pixelColor(x,y).lightness() < 30]
        self.assertTrue(dark_text)
        self.assertGreater(sum(after.pixelColor(x,y).lightness()>150 for x,y in dark_text)/len(dark_text), .98)

    def test_rotated_image_bounds_follow_the_visible_page(self):
        import tempfile
        import pymupdf
        from pdfeditor.core import Document
        from PyQt5.QtCore import QBuffer, QIODevice
        image = QImage(10, 10, QImage.Format_RGB32)
        image.fill(Qt.red)
        buffer = QBuffer();buffer.open(QIODevice.WriteOnly);image.save(buffer,'PNG')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'rotated.pdf'
            with pymupdf.open() as pdf:
                page=pdf.new_page(width=100,height=200)
                page.insert_image((10,20,60,70),stream=bytes(buffer.data()))
                page.set_rotation(90)
                pdf.save(path)
            document = Document(str(path),read_only=True)
            try:
                self.assertEqual(document.display_image_regions(0), [(130.,10.,180.,60.)])
            finally:
                document.close()

    def test_embedded_reader_keeps_reference_colors_without_explicit_opt_in(self):
        from unittest.mock import patch
        from pdfeditor.reader_view import ReaderPageView
        with patch('pdfeditor.settings.document_night',return_value=True), \
                patch.object(self.app, 'property', return_value=True), \
                patch.object(self.app, '_leaflet_theme_controller', None, create=True):
            embedded = ReaderPageView(use_opengl=False)
            standalone = ReaderPageView(use_opengl=False,document_colors=True)
        try:
            self.assertFalse(embedded._document_night_enabled)
            self.assertTrue(standalone._document_night_enabled)
        finally:
            embedded.close();standalone.close()
            embedded.deleteLater();standalone.deleteLater()

    @unittest.skipUnless(os.name == 'nt', 'Direct2D is Windows-only')
    def test_native_filter_preserves_photos_colors_and_large_hidpi_tile_edges(self):
        from pdfeditor.d2d_backend import D2DSurface
        library = Path(__file__).resolve().parents[1]/'native/bin/spdf_d2d_renderer.dll'
        if not library.is_file():
            self.skipTest('native renderer is not built')
        user = ctypes.WinDLL('user32')
        user.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint32, *([ctypes.c_int]*4), *([ctypes.c_void_p]*4)]
        user.CreateWindowExW.restype = ctypes.c_void_p
        user.DestroyWindow.argtypes = [ctypes.c_void_p]
        window = user.CreateWindowExW(0, 'STATIC', 'Night display test', 0,
            0, 0, 2400, 120, None, None, None, None)
        self.assertTrue(window)
        try:
            for dpi in (96., 144.):
                with self.subTest(dpi=dpi), D2DSurface(window, 2400, 120, dpi, path=library) as surface:
                    width, height = 2400*96/dpi, 120*96/dpi
                    mask = surface.create_bitmap_bgra(b'\xff'*4+b'\0'*4, 2, 1, 8)
                    surface.begin_frame(0xffffffff)
                    surface.fill_rect(width*.1, 10, width*.2, 30, 0xff000000)
                    surface.fill_rect(width*.3, 10, width*.4, 30, 0xffff0000)
                    before = surface.read_pixels_bgra(2400, 120)
                    baseline_offset = (80*2400+30)*4
                    self.assertEqual(tuple(before[baseline_offset:baseline_offset+4]), (255,255,255,255))
                    self.assertTrue(surface.apply_document_night([(mask, (1,0,0,1,0,0), width, height)]))
                    after = surface.read_pixels_bgra(2400, 120)
                    surface.end_frame()
                    def pixel(data, x, y):
                        start = (y*2400+x)*4
                        return tuple(data[start:start+4])
                    samples = {x: pixel(after, x, round(20*dpi/96)) for x in (30, 350, 800, 2000, 2047, 2048, 2200)}
                    self.assertGreater(pixel(after, 30, 80)[0], 20, samples)
                    self.assertLess(pixel(after, 30, 80)[0], 70, samples)
                    self.assertGreater(pixel(after, 350, round(20*dpi/96))[0], 180, samples)
                    self.assertEqual(pixel(after, 800, round(20*dpi/96)), pixel(before, 800, round(20*dpi/96)))
                    for x in (2000, 2047, 2048, 2200, 2390):
                        self.assertEqual(pixel(after, x, 80), pixel(before, x, 80))
                    surface.release_document_night()
        finally:
            user.DestroyWindow(window)


if __name__ == '__main__':
    unittest.main()
