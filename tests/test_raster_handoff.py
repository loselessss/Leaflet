"""Owned Qt images must outlive the borrowed SDK pixels and their document."""
import gc
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import PropertyMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pymupdf
from PyQt5.QtGui import QImage, QPixmap, QTransform, QColor
from PyQt5.QtWidgets import QApplication
from pdfeditor.core import Document
from pdfeditor.raster_buffer import RasterBuffer
from pdfeditor import widgets


def rgb(image):
    image = image.convertToFormat(QImage.Format_RGB888)
    bits = image.constBits()
    bits.setsize(image.sizeInBytes())
    view = memoryview(bits)
    return b''.join(view[y * image.bytesPerLine():y * image.bytesPerLine() + image.width() * 3]
                    for y in range(image.height()))


class RasterHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'source.pdf'
        with pymupdf.open() as pdf:
            for width in (101, 102, 103, 104):
                page = pdf.new_page(width=width, height=129)
                page.draw_rect((3.2, 4.1, 76.6, 90.3), color=(.9, .1, .4),
                               fill=(.1, .4, .9), fill_opacity=.37)
                page.insert_text((4, 110), 'Reader RGB', fontsize=12)
            pdf[1].set_rotation(90)
            pdf[2].set_cropbox((3, 5, 95, 120))
            pdf.save(self.path)

    def test_reader_pixels_match_bytes_route_at_odd_widths_and_device_ratios(self):
        doc = Document(str(self.path), read_only=True)
        try:
            for index in range(doc.page_count):
                for scale in (1., 1.375):
                    expected = widgets.qimage_from_render(*doc.render(index, scale))
                    actual = widgets.qimage_from_render(*doc.render(index, scale, copy_pixels=False),
                                                       device_pixel_ratio=2)
                    self.assertEqual(rgb(actual), rgb(expected))
                    self.assertEqual(actual.devicePixelRatio(), 2.)
                    self.assertEqual(QPixmap.fromImage(actual).size(), actual.size())
        finally:
            doc.close()

    def test_no_python_samples_copy_and_buffer_survives_document_close(self):
        doc = Document(str(self.path), read_only=True)
        try:
            expected = widgets.qimage_from_render(*doc.render(0))
            with patch.object(pymupdf.Pixmap, 'samples', new_callable=PropertyMock,
                              side_effect=AssertionError('unexpected Python pixel copy')):
                rendered = doc.render(0, copy_pixels=False)
                self.assertIsInstance(rendered[3], RasterBuffer)
                doc.close()
                gc.collect()
                actual = widgets.qimage_from_render(*rendered)
            del rendered
            gc.collect()
            self.assertEqual(rgb(actual), rgb(expected))
        finally:
            doc.close()

    def test_qt_shallow_copies_and_pixmaps_keep_independent_pixels(self):
        doc = Document(str(self.path), read_only=True)
        try:
            rendered = doc.render(0, copy_pixels=False)
            image = widgets.qimage_from_render(*rendered)
            expected = rgb(image)
            shared = QImage(image)
            pixmap = QPixmap.fromImage(image)
            # Mutate the SDK pixels after handoff: Qt must already own its data.
            rendered[3]._pixmap.clear_with(0)
            image.fill(QColor('red'))  # Qt detaches from its implicit copy.
            del rendered, image
            doc.close()
            gc.collect()
            self.assertEqual(rgb(shared), expected)
            self.assertEqual(rgb(pixmap.toImage()), expected)
            self.assertFalse(shared.transformed(QTransform().rotate(90)).isNull())
        finally:
            doc.close()

    def test_missing_or_older_extension_uses_owned_qt_copy(self):
        doc = Document(str(self.path), read_only=True)
        try:
            expected = widgets.qimage_from_render(*doc.render(0))
            with patch.object(widgets, '_copy_rgb_rows', None):
                actual = widgets.qimage_from_render(*doc.render(0, copy_pixels=False))
            doc.close()
            gc.collect()
            self.assertEqual(rgb(actual), rgb(expected))
        finally:
            doc.close()

    def test_legacy_bytes_and_geometry_validation(self):
        self.assertEqual(rgb(widgets.qimage_from_render(1, 1, 3, b'\x11\x22\x33')), b'\x11\x22\x33')
        doc = Document(str(self.path), read_only=True)
        try:
            w, h, stride, samples = doc.render(0, copy_pixels=False)
            with self.assertRaises(ValueError):
                widgets.qimage_from_render(w + 1, h, stride, samples)
        finally:
            doc.close()

    @unittest.skipIf(widgets._copy_rgb_rows is None, 'Rust RGB buffer copier not built')
    def test_rust_rows_ignore_source_padding_clear_target_padding_and_keep_guards(self):
        for width in (1, 2, 3, 4, 101):
            row = width * 3
            for source_stride in (row, row + 5):
                for target_stride in (row, row + 3):
                    source = bytes((i % 251 for i in range(source_stride * 3)))
                    target = bytearray(b'\xcc' * (target_stride * 3 + 7))
                    widgets._copy_rgb_rows(memoryview(source), target, width, 3,
                                           source_stride, target_stride)
                    expected = b''.join(source[y * source_stride:y * source_stride + row]
                                        + b'\0' * (target_stride - row) for y in range(3))
                    self.assertEqual(target, expected + b'\xcc' * 7)

    @unittest.skipIf(widgets._copy_rgb_rows is None, 'Rust RGB buffer copier not built')
    def test_invalid_rust_buffers_do_not_change_destination(self):
        for source, width, height, source_stride, target_stride in (
                (b'abc', 2, 1, 6, 6), (b'abc', 1, 1, 2, 3),
                (b'abc', 1, 1, 3, 2), (b'abc', 0, 1, 3, 3),
                (b'abc', 1, 0, 3, 3), (b'abc', 1, 1, 2**63, 3),
                (memoryview(b'abcdef')[::2], 1, 1, 3, 3)):
            destination = bytearray(b'\xcc' * 8)
            with self.assertRaises((ValueError, BufferError, OverflowError)):
                widgets._copy_rgb_rows(source, destination, width, height,
                                       source_stride, target_stride)
            self.assertEqual(destination, b'\xcc' * 8)
        with self.assertRaises(ValueError):
            widgets._copy_rgb_rows(b'abc', b'abc', 1, 1, 3, 3)
        shared = bytearray(b'abcdef')
        with self.assertRaises(ValueError):
            widgets._copy_rgb_rows(memoryview(shared)[:3], memoryview(shared)[1:4], 1, 1, 3, 3)
        self.assertEqual(shared, b'abcdef')


if __name__ == '__main__':
    unittest.main()
