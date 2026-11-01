"""Deliver real Qt wheel events to each document viewport."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QImage, QWheelEvent
from PyQt5.QtWidgets import QApplication

from pdfeditor.artboards import ArtboardView
from pdfeditor.reader_view import ReaderPageView
from pdfeditor.widgets import PageView


class TouchpadScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.views = []
        self.lines = QApplication.wheelScrollLines()
        QApplication.setWheelScrollLines(3)

    def tearDown(self):
        for view in self.views:
            view.close()
            view.deleteLater()
        self.app.processEvents()
        QApplication.setWheelScrollLines(self.lines)

    def view(self, kind):
        view = kind(use_opengl=False) if kind is ReaderPageView else kind()
        self.views.append(view)
        view.resize(420, 340)
        if kind is PageView:
            image = QImage(2000, 2000, QImage.Format_RGB888)
            image.fill(Qt.white)
            view.set_image(image)
        else:
            view.scene().setSceneRect(0, 0, 2000, 2000)
        view.show()
        self.app.processEvents()
        for bar in (view.horizontalScrollBar(), view.verticalScrollBar()):
            self.assertGreater(bar.maximum(), 600)
            bar.setValue(500)
            bar.setSingleStep(20)
        return view

    def wheel(self, view, *, pixel=(0, 0), angle=(0, 0), modifiers=Qt.NoModifier,
              phase=Qt.ScrollUpdate, inverted=False):
        position = view.viewport().rect().center()
        event = QWheelEvent(QPointF(position), QPointF(view.viewport().mapToGlobal(position)),
            QPoint(*pixel), QPoint(*angle), Qt.NoButton, modifiers, phase, inverted,
            Qt.MouseEventSynthesizedBySystem)
        self.app.sendEvent(view.viewport(), event)

    def position(self, view):
        return view.horizontalScrollBar().value(), view.verticalScrollBar().value()

    def test_pixel_diagonal_preserves_both_axes_without_using_angle_fallback(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                self.wheel(view, pixel=(17, -29), angle=(120, -120))
                self.assertEqual(self.position(view), (483, 529))
                # Natural scrolling is already expressed by the delivered deltas.
                self.wheel(view, pixel=(17, -29), inverted=True)
                self.assertEqual(self.position(view), (466, 558))

    def test_small_angle_diagonal_accumulates_both_axes(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                for _ in range(4):
                    self.wheel(view, angle=(1, -1))
                self.assertEqual(self.position(view), (498, 502))
                for _ in range(4):
                    self.wheel(view, angle=(-1, 1))
                self.assertEqual(self.position(view), (500, 500))

    def test_diagonal_scroll_at_vertical_edge_pans_without_flipping_pages(self):
        for kind in (ReaderPageView, PageView):
            for pixel, angle in (((30, -30), (120, -120)), ((0, 0), (120, -120))):
                with self.subTest(view=kind.__name__, pixel=pixel):
                    view = self.view(kind)
                    flips = []
                    view.page_flip.connect(flips.append)
                    vertical = view.verticalScrollBar()
                    vertical.setValue(vertical.maximum())
                    view._flip_accum = -60
                    self.wheel(view, pixel=pixel, angle=angle)
                    self.assertEqual(view.horizontalScrollBar().value(), 470 if pixel[0] else 440)
                    self.assertEqual(vertical.value(), vertical.maximum())
                    self.assertEqual(flips, [])
                    self.assertEqual(view._flip_accum, 0)

    def test_regular_vertical_wheel_still_scrolls_and_turns_pages_at_edge(self):
        for kind in (ReaderPageView, PageView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                flips = []
                view.page_flip.connect(flips.append)
                self.wheel(view, angle=(0, -120))
                self.assertEqual(self.position(view), (500, 560))
                view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
                self.wheel(view, angle=(0, -60))
                self.assertEqual(flips, [])
                self.wheel(view, angle=(0, -60))
                self.assertEqual(flips, [1])

    def test_one_axis_reaching_its_edge_does_not_block_the_other(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                horizontal = view.horizontalScrollBar()
                horizontal.setValue(horizontal.minimum())
                self.wheel(view, pixel=(20, -30))
                self.assertEqual(self.position(view), (horizontal.minimum(), 530))
                self.wheel(view, pixel=(-3, -5))
                self.assertEqual(self.position(view), (horizontal.minimum() + 3, 535))

    def test_separate_gestures_do_not_inherit_fractional_movement(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                self.wheel(view, angle=(1, -1))  # Half a pixel on each axis.
                self.wheel(view, phase=Qt.ScrollEnd)
                self.wheel(view, phase=Qt.ScrollBegin)
                self.wheel(view, angle=(1, -1))
                self.assertEqual(self.position(view), (500, 500))
                self.wheel(view, angle=(1, -1))
                self.assertEqual(self.position(view), (499, 501))

    def test_pixel_only_vertical_scroll_and_empty_gesture_boundaries(self):
        for kind in (ReaderPageView, PageView, ArtboardView):
            with self.subTest(view=kind.__name__):
                view = self.view(kind)
                self.wheel(view, phase=Qt.ScrollBegin)
                self.assertEqual(self.position(view), (500, 500))
                self.wheel(view, pixel=(0, -23))
                self.wheel(view, pixel=(-11, -7), phase=Qt.ScrollMomentum)
                self.wheel(view, phase=Qt.ScrollEnd)
                self.assertEqual(self.position(view), (511, 530))

    def test_zoom_shortcuts_take_priority_over_touchpad_pan(self):
        reader = self.view(ReaderPageView)
        with patch.object(reader, '_start_zoom_animation') as zoom:
            self.wheel(reader, pixel=(20, 30), angle=(120, 120), modifiers=Qt.ControlModifier)
            self.assertAlmostEqual(zoom.call_args.args[0], 1.25)
            self.wheel(reader, pixel=(20, 30), angle=(120, 120), modifiers=Qt.AltModifier)
            self.assertAlmostEqual(zoom.call_args.args[0], 1.01)
        self.assertEqual(self.position(reader), (500, 500))
        legacy = self.view(PageView)
        self.wheel(legacy, pixel=(20, 30), angle=(120, 120), modifiers=Qt.ControlModifier)
        self.assertAlmostEqual(legacy.zoom, 1.25)
        self.wheel(legacy, pixel=(20, 30), angle=(120, 120), modifiers=Qt.AltModifier)
        self.assertAlmostEqual(legacy.zoom, 1.26)
        self.assertEqual(self.position(legacy), (500, 500))
        artboard = self.view(ArtboardView)
        with patch.object(artboard, 'set_zoom') as zoom:
            self.wheel(artboard, pixel=(20, 30), angle=(120, 120), modifiers=Qt.ControlModifier)
            self.assertAlmostEqual(zoom.call_args.args[0], 1.25)
        self.assertEqual(self.position(artboard), (500, 500))
