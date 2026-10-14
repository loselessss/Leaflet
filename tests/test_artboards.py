"""Artboards use view-only positions and the existing document editor."""

import math
import unittest
from unittest.mock import patch

from tests import test_editor_workspace as fixtures


class ArtboardTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditorWorkspaceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.EditorWorkspaceTests.tearDownClass.__func__)
    setUp = fixtures.EditorWorkspaceTests.setUp
    tearDown = fixtures.EditorWorkspaceTests.tearDown
    settle = fixtures.EditorWorkspaceTests.settle
    open_editor = fixtures.EditorWorkspaceTests.open_editor

    def overview(self):
        tab = self.open_editor()
        tab.show_editor_overview()
        self.settle()
        return tab, tab._artboard_view

    def test_selection_and_double_click_open_same_document(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        tab, view = self.overview()
        document = tab.doc
        board = view._boards[1]
        point = view.mapFromScene(board.sceneBoundingRect().center())
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(tab.page_index, 1)
        QTest.mouseDClick(view.viewport(), Qt.LeftButton, pos=point)
        self.settle()
        self.assertFalse(tab.is_editor_overview())
        self.assertIs(tab.doc, document)
        self.assertEqual(tab.page_index, 1)
        self.assertTrue(tab._edit_mode)
        self.assertFalse(view._timer.isActive())

    def test_view_layout_does_not_edit_or_reorder_pdf(self):
        from PyQt5.QtCore import QPointF
        tab, view = self.overview()
        original = [tab.doc._doc.xref_object(index) for index in range(1, tab.doc._doc.xref_length())]
        view._boards[1].setPos(QPointF(-350, 120))
        view._update_scene_rect()
        view.arrange(2)
        self.assertEqual(view._boards[2].pos().x(), 0)
        self.assertEqual(view._boards[0].rect.width(), 280)
        self.assertEqual([tab.doc._doc.xref_object(index) for index in range(1, tab.doc._doc.xref_length())], original)
        self.assertFalse(tab._dirty)
        self.assertEqual(len(tab._undo_stack), 0)

    def test_zoom_uses_canvas_transform_and_restores_detail(self):
        tab = self.open_editor()
        tab.set_zoom(1.37)
        tab.show_editor_overview()
        self.settle()
        view = tab._artboard_view
        tab.set_zoom_percent(125)
        self.assertAlmostEqual(tab.zoom_percent(), 125)
        self.assertAlmostEqual(view.transform().m11(), view.zoom)
        self.assertEqual(tab._zoom_input.value(), 125)
        zoom = view.zoom
        tab.zoom_in()
        self.assertAlmostEqual(view.zoom, zoom * 1.25)
        view.set_zoom(math.nan)
        self.assertTrue(math.isfinite(view.zoom))
        tab.open_page_editor()
        self.assertAlmostEqual(tab.view.zoom, 1.37)

    def test_preview_is_lazy_reused_and_memory_bounded(self):
        tab, view = self.overview()
        view.stop_rendering()
        view._previews.clear()
        view._cache_bytes = 0
        with patch.object(tab.doc, "render", wraps=tab.doc.render) as render:
            view._render_next()
            view.stop_rendering()
            self.assertEqual(render.call_count, 1)
            page = next(iter(view._previews))
            self.assertIn(page, view.visible_pages())
            with patch.object(view, "visible_pages", return_value=[page]):
                view._render_next()
                self.assertEqual(render.call_count, 1)
        image_bytes = view._cache_bytes
        view.cache_limit = image_bytes
        with patch.object(view, "visible_pages", return_value=[(page + 1) % tab.doc.page_count]):
            view._render_next()
        self.assertLessEqual(view._cache_bytes, view.cache_limit)
        tab.prepare_close_doc()
        self.assertIsNone(view._document)
        self.assertEqual(view._cache_bytes, 0)
        self.assertFalse(view._timer.isActive())

    def test_changed_geometry_refreshes_and_undo_restores(self):
        tab, view = self.overview()
        tab.apply_document_change(lambda: tab.doc.set_page_canvas_size(0, 350, 450))
        self.assertEqual(view._boards[0].rect.width(), 350)
        tab.undo()
        self.assertEqual(view._boards[0].rect.width(), 280)
        self.assertTrue(tab.is_editor_overview())

    def test_text_overflow_prevents_switch(self):
        tab = self.open_editor()
        with patch.object(tab, "_commit_inline_text", return_value=False):
            tab.toggle_artboards()
        self.assertFalse(tab.is_editor_overview())
        self.assertFalse(tab._artboard_act.isChecked())

    def test_cache_pressure_settles_instead_of_rerender_loop(self):
        tab, view = self.overview()
        view.stop_rendering()
        view._previews.clear()
        view._cache_bytes = 0
        view.cache_limit = 2 * 1024 * 1024
        view.set_zoom(1.5)
        with patch.object(view, "visible_pages", return_value=list(range(45))), \
                patch.object(tab.doc, "render", wraps=tab.doc.render) as render:
            for _ in range(10):
                view._render_next()
                view.stop_rendering()
            count = render.call_count
            self.assertGreater(count, 0)
            self.assertLess(count, 45)
            for _ in range(10):
                view._render_next()
                view.stop_rendering()
            self.assertEqual(render.call_count, count)
            self.assertLessEqual(view._cache_bytes, view.cache_limit)

    def test_page_label_drag_and_space_pan_are_view_only(self):
        from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtTest import QTest
        tab, view = self.overview()
        board = view._boards[0]
        origin = board.pos()
        point = view.mapFromScene(board.label.scenePos()) + QPoint(20, 7)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=point)
        self.assertIsNotNone(view._layout_drag)
        self.application.sendEvent(view.viewport(), QMouseEvent(
            QEvent.MouseMove, QPointF(point + QPoint(80, 40)), Qt.NoButton,
            Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=point + QPoint(80, 40))
        self.assertNotEqual(board.pos(), origin)
        self.assertFalse(tab._dirty)
        view.set_zoom(1.5)
        view.centerOn(board.sceneBoundingRect().center())
        point = view.viewport().rect().center()
        before = view.mapToScene(point)
        QTest.keyPress(view, Qt.Key_Space)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=point)
        self.application.sendEvent(view.viewport(), QMouseEvent(
            QEvent.MouseMove, QPointF(point + QPoint(40, 30)), Qt.NoButton,
            Qt.LeftButton, Qt.NoModifier))
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=point + QPoint(40, 30))
        QTest.keyRelease(view, Qt.Key_Space)
        self.assertNotEqual(view.mapToScene(point), before)
        self.assertFalse(view._space)
        self.assertEqual(len(tab._undo_stack), 0)

    def test_artboard_navigation_state_does_not_save_canvas_offsets(self):
        tab, view = self.overview()
        tab.show_page(20)
        self.assertEqual(view.selected_page, 20)
        state = tab.capture_view_state()
        self.assertEqual(state["page"], 20)
        self.assertEqual(state["horizontal"], 0)
        self.assertEqual(state["vertical"], 0)
        tab.restore_view_state({"page": 3, "zoom": 1.2})
        self.assertFalse(tab.is_editor_overview())
        self.assertEqual(tab.page_index, 3)
        self.assertEqual(tab.view.zoom, 1.2)

    def test_navigation_back_from_overview_preserves_forward_history(self):
        tab, view = self.overview()
        tab.show_page(2)
        tab.navigate_history()
        self.assertFalse(tab.is_editor_overview())
        self.assertEqual(tab.page_index, 0)
        tab.navigate_history(False)
        self.assertEqual(tab.page_index, 2)

    def test_object_and_note_tools_focus_editor(self):
        tab, view = self.overview()
        tab._object_controller.activate()
        self.assertFalse(tab.is_editor_overview())
        self.assertTrue(tab._object_controller.active)
        tab.show_editor_overview()
        tab.start_note_mode()
        self.assertFalse(tab.is_editor_overview())
        self.assertTrue(tab._note_mode)

    def test_reader_and_embedded_do_not_expose_artboards(self):
        for mode in ("reader", None):
            window = self.module.new_window(str(self.path), workspace_mode=mode)
            self.settle()
            tab = window._tabs.currentWidget()
            tab.show_editor_overview()
            self.assertFalse(tab.is_editor_overview())
            self.assertIsNone(tab._artboard_act)
            self.assertIsNone(tab._artboard_view)


if __name__ == "__main__":
    unittest.main()
