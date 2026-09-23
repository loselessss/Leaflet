import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pdfeditor.viewer import ViewerMixin


class ThumbnailSchedulingTests(unittest.TestCase):
    def test_one_thumbnail_per_tick_and_queue_finishes(self):
        rendered = set()
        thumbs = Mock()
        thumbs.thumbnail_width.return_value = 100
        thumbs.visible_rows.return_value = [0, 1, 2]
        thumbs.is_rendered.side_effect = lambda row, width: row in rendered
        thumbs.set_thumb.side_effect = lambda row, image, **kw: rendered.add(row)
        host = SimpleNamespace(
            doc=Mock(page_count=3), thumbs=thumbs, view=SimpleNamespace(),
            _view_ready=True, is_editor_overview=lambda: False,
            _displayed_page_size=lambda row: (500, 700),
            _schedule_thumbs=Mock(), update_thumbnail_viewport_marker=Mock())
        host.doc.render.return_value = (1, 1, 3, b"\xff\xff\xff")
        with patch("pdfeditor.viewer.render_pixel_ratio", return_value=1), \
                patch("pdfeditor.viewer.qimage_from_render"):
            for count in range(1, 4):
                ViewerMixin._render_visible_thumbs(host)
                self.assertEqual(len(rendered), count)
            ViewerMixin._render_visible_thumbs(host)
        self.assertEqual(host.doc.render.call_count, 3)
        self.assertEqual(host._schedule_thumbs.call_count, 2)

    def test_initial_layout_takes_priority(self):
        host = SimpleNamespace(doc=object(), _view_ready=False,
                               is_editor_overview=lambda: False,
                               _schedule_thumbs=Mock())
        ViewerMixin._render_visible_thumbs(host)
        host._schedule_thumbs.assert_called_once()
