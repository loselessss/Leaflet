import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pdfeditor.viewer import ViewerMixin


class InitialLayoutGuardsTests(unittest.TestCase):
    def test_live_document_initializes_only_once(self):
        document = object()
        viewer = SimpleNamespace(
            doc=document, _closing_doc=False, _view_ready=False,
            _initial_reading_state=None, view=SimpleNamespace(zoom=1.0),
            page_index=0, _set_fit_zoom=Mock(), show_page=Mock(),
            _update_page_label=Mock(), update_thumbnail_viewport_marker=Mock())
        ViewerMixin.finish_initial_layout(viewer, document)
        ViewerMixin.finish_initial_layout(viewer, document)
        viewer._set_fit_zoom.assert_called_once_with(0)
        viewer.show_page.assert_called_once_with(0)
        self.assertTrue(viewer._view_ready)

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
