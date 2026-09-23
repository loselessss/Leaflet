import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pdfeditor.viewer import ViewerMixin


class InitialLayoutGuardsTests(unittest.TestCase):
    def test_live_document_initializes_only_once(self):
        document = object()
        viewer = SimpleNamespace(
            doc=document, _closing_doc=False, _view_ready=False,
            _initial_reading_state=None,
            view=SimpleNamespace(zoom=1.0),
            page_index=0, _set_fit_zoom=Mock(), show_page=Mock(),
            _update_page_label=Mock(), update_thumbnail_viewport_marker=Mock())
        ViewerMixin.finish_initial_layout(viewer, document)
        ViewerMixin.finish_initial_layout(viewer, document)
        viewer._set_fit_zoom.assert_called_once_with(0, reserve_vertical=True)
        viewer.show_page.assert_called_once_with(0)
        self.assertTrue(viewer._view_ready)

    def test_initial_fit_reserves_scrollbar_without_second_render(self):
        bar = SimpleNamespace(isVisible=lambda: False,
                              sizeHint=lambda: SimpleNamespace(width=lambda: 14))
        view = SimpleNamespace(
            zoom=1.0, ZOOM_MIN=.1, ZOOM_MAX=8.0,
            viewport=lambda: SimpleNamespace(width=lambda: 934, height=lambda: 677),
            verticalScrollBar=lambda: bar)
        document = SimpleNamespace(page_count=1)
        viewer = SimpleNamespace(
            doc=document, _closing_doc=False, _view_ready=False,
            _initial_reading_state=None, view=view, page_index=0,
            _two_page_mode=False, _cache={},
            _displayed_page_size=lambda _page: (200, 300),
            _set_fit_zoom=lambda page, **kwargs: ViewerMixin._set_fit_zoom(viewer, page, **kwargs),
            show_page=Mock(), _update_page_label=Mock(),
            update_thumbnail_viewport_marker=Mock())
        ViewerMixin.finish_initial_layout(viewer, document)
        self.assertEqual(view.zoom, (934 - 14 - 24) / 200)
        viewer.show_page.assert_called_once_with(0)

    def test_closed_replaced_or_completed_document_is_not_rendered(self):
        document = object()
        for current, closing, ready in (
                (document, True, False), (document, False, True),
                (object(), False, False), (None, False, False)):
            with self.subTest(closing=closing, ready=ready, current=current):
                viewer = SimpleNamespace(
                    doc=current, _closing_doc=closing, _view_ready=ready,
                    show_page=Mock())
                ViewerMixin.finish_initial_layout(viewer, document)
                viewer.show_page.assert_not_called()
