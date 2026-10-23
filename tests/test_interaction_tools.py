import importlib.util
import os
import unittest
from unittest.mock import Mock


HAS_PYQT5 = importlib.util.find_spec("PyQt5") is not None


@unittest.skipUnless(HAS_PYQT5, "PyQt5가 설치된 환경에서 실행")
class InteractionToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_cursor_tracks_selected_interaction_mode(self):
        from PyQt5.QtCore import Qt
        from pdfeditor.widgets import PageView

        view = PageView()
        self.assertEqual(view.canvas.cursor().shape(), Qt.IBeamCursor)
        view.set_interaction_mode("hand")
        self.assertEqual(view.canvas.interaction_mode, "hand")
        self.assertEqual(view.canvas.cursor().shape(), Qt.OpenHandCursor)
        view.set_interaction_mode("select")
        self.assertEqual(view.canvas.cursor().shape(), Qt.IBeamCursor)
        with self.assertRaises(ValueError):
            view.set_interaction_mode("unknown")
        view.close()

    def test_hand_drag_delta_moves_scrollbars_in_opposite_direction(self):
        from PyQt5.QtCore import QPoint
        from pdfeditor.widgets import PageView

        view = PageView()
        view.resize(240, 240)
        view.canvas.resize(1000, 1000)
        view.show()
        self.app.processEvents()
        hbar = view.horizontalScrollBar()
        vbar = view.verticalScrollBar()
        hbar.setValue(200)
        vbar.setValue(200)
        view._pan_canvas(QPoint(25, -30))
        self.assertEqual(hbar.value(), 175)
        self.assertEqual(vbar.value(), 230)
        view.close()

    def test_hidpi_render_keeps_logical_page_size(self):
        from pdfeditor.widgets import PageCanvas, qimage_from_render

        image = qimage_from_render(
            4,
            4,
            12,
            bytes([255] * 48),
            device_pixel_ratio=2.0,
        )
        canvas = PageCanvas()
        canvas.set_image(image, 1.0)

        self.assertEqual(image.devicePixelRatio(), 2.0)
        self.assertEqual(canvas.width(), 2)
        self.assertEqual(canvas.height(), 2)
        canvas.close()

    def test_middle_drag_pans_scrolling_canvas_without_clearing_selection(self):
        from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
        from PyQt5.QtGui import QImage, QMouseEvent
        from PyQt5.QtTest import QSignalSpy
        from pdfeditor.widgets import PageView
        view = PageView()
        image = QImage(1000, 1000, QImage.Format_RGB888)
        image.fill(Qt.white)
        view.set_image(image)
        view.resize(240, 240)
        view.show()
        self.app.processEvents()
        h, v = view.horizontalScrollBar(), view.verticalScrollBar()
        h.setValue(200)
        v.setValue(200)
        selection = [QRectF(100, 100, 20, 20)]
        view.canvas.set_selection(selection)
        cleared = QSignalSpy(view.canvas.selection_cleared)
        start = view.canvas.mapToGlobal(QPoint(300, 300))
        try:
            for kind, delta, button, buttons in (
                    (QEvent.MouseButtonPress, QPoint(), Qt.MiddleButton, Qt.MiddleButton),
                    (QEvent.MouseMove, QPoint(30, 20), Qt.NoButton, Qt.MiddleButton),
                    (QEvent.MouseMove, QPoint(45, 35), Qt.NoButton, Qt.MiddleButton),
                    (QEvent.MouseButtonRelease, QPoint(45, 35), Qt.MiddleButton, Qt.NoButton)):
                global_pos = start + delta
                event = QMouseEvent(kind, QPointF(view.canvas.mapFromGlobal(global_pos)),
                                    QPointF(global_pos), button, buttons, Qt.NoModifier)
                self.app.sendEvent(view.canvas, event)
            self.assertEqual((h.value(), v.value()), (155, 165))
            self.assertEqual(len(cleared), 0)
            self.assertEqual(view.canvas._sel_rects, selection)
            self.assertEqual(view.canvas.cursor().shape(), Qt.IBeamCursor)
        finally:
            view.close()

    def test_two_page_canvas_keeps_page_coordinates_independent(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QImage
        from pdfeditor.widgets import PageCanvas

        image = QImage(100, 160, QImage.Format_RGB888)
        canvas = PageCanvas()
        canvas.set_images([(4, image), (5, image)], 1.0, 4)

        self.assertEqual(canvas.width(), 216)
        self.assertEqual(canvas._page_point(QPoint(25, 40))[0], 4)
        second = canvas._page_point(QPoint(141, 40))
        self.assertEqual(second[0], 5)
        self.assertAlmostEqual(second[1].x(), 25.0)
        self.assertAlmostEqual(second[1].y(), 40.0)
        canvas.close()

    def test_ctrl_click_emits_link_point_in_select_and_hand_modes(self):
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtGui import QImage
        from PyQt5.QtTest import QSignalSpy, QTest
        from pdfeditor.widgets import PageCanvas

        image = QImage(100, 160, QImage.Format_RGB888)
        canvas = PageCanvas()
        canvas.set_image(image, 1.0)
        canvas.show()
        self.app.processEvents()
        spy = QSignalSpy(canvas.ctrl_clicked)

        for mode in ("select", "hand"):
            canvas.set_interaction_mode(mode)
            QTest.mouseClick(
                canvas, Qt.LeftButton, Qt.ControlModifier, QPoint(25, 40))

        self.assertEqual(len(spy), 2)
        self.assertAlmostEqual(spy[0][0].x(), 25.0)
        self.assertAlmostEqual(spy[0][0].y(), 40.0)
        canvas.close()

    def test_two_page_navigation_moves_by_spread(self):
        from pdfeditor.viewer import ViewerMixin

        host = Mock()
        host._two_page_mode = True
        host.page_index = 1
        ViewerMixin.next_page(host)
        host.show_page.assert_called_once_with(2)

        host.show_page.reset_mock()
        host.page_index = 3
        ViewerMixin.prev_page(host)
        host.show_page.assert_called_once_with(0)

    def test_render_pixel_ratio_reduces_extra_work_at_high_zoom(self):
        from PyQt5.QtWidgets import QWidget
        from pdfeditor.viewer import render_pixel_ratio

        widget = QWidget()
        low_zoom = render_pixel_ratio(widget, 1.0)
        high_zoom = render_pixel_ratio(widget, 4.0)
        self.assertGreaterEqual(low_zoom, 2.0)
        self.assertGreaterEqual(high_zoom, widget.devicePixelRatioF())
        self.assertLessEqual(high_zoom, low_zoom)
        widget.close()

    def test_visible_page_rect_tracks_scroll_position(self):
        from pdfeditor.widgets import PageView

        view = PageView()
        view.resize(240, 240)
        view.canvas.resize(1000, 800)
        view.show()
        self.app.processEvents()
        view.horizontalScrollBar().setValue(200)
        view.verticalScrollBar().setValue(160)
        rect = view.visible_page_rect()

        self.assertIsNotNone(rect)
        self.assertAlmostEqual(rect.x(), 0.2, places=2)
        self.assertAlmostEqual(rect.y(), 0.2, places=2)
        self.assertLess(rect.width(), 0.25)
        self.assertLess(rect.height(), 0.3)
        view.close()

    def test_thumbnail_point_can_center_document_view(self):
        from PyQt5.QtCore import QPointF
        from pdfeditor.widgets import PageView

        view = PageView()
        view.resize(240, 240)
        view.canvas.resize(1000, 800)
        view.show()
        self.app.processEvents()

        view.center_on_page_fraction(QPointF(0.6, 0.7))
        rect = view.visible_page_rect()

        self.assertIsNotNone(rect)
        self.assertAlmostEqual(rect.center().x(), 0.6, places=2)
        self.assertAlmostEqual(rect.center().y(), 0.7, places=2)
        view.close()


if __name__ == "__main__":
    unittest.main()
