"""Desktop tear-off, merging, in-bar return and cancellation keep live tabs."""
import os
import unittest
from unittest.mock import patch

from PyQt5.QtCore import QEvent, QMimeData, QPoint, Qt
from PyQt5.QtGui import QDragEnterEvent, QDragMoveEvent, QDragLeaveEvent, QKeyEvent
from PyQt5.QtWidgets import QApplication

from pdfeditor import tab_drag
from tests import test_embedded_mode as fixtures


class TabDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.fixture = fixtures.EmbeddedModeTests.document_windows(self)
        self.module, self.path = self.fixture.__enter__()

    def tearDown(self):
        tab_drag._dragged_tabs.clear()
        self.fixture.__exit__(None, None, None)

    def opened(self, window):
        tab = window.open_in_tab(str(self.path))
        for _ in range(4):
            self.app.processEvents()
        return tab

    def test_desktop_release_detaches_same_document_and_view(self):
        window = self.module.new_window(workspace_mode="reader")
        tab = self.opened(window)
        tab.restore_view_state({"page": 1, "zoom": 1.5})
        document = tab.doc
        bar = window._tabs.tabBar()
        with patch.object(tab_drag, "QDrag") as drag, \
                patch.object(tab_drag, "DragReleaseState") as state, \
                patch.object(tab_drag.QCursor, "pos", return_value=QPoint(5000, 5000)):
            drag.return_value.exec_.return_value = Qt.IgnoreAction
            state.return_value.finish.return_value = (True, False)
            bar._start_transfer(tab)
        destination = tab._shell
        self.assertIsNot(destination, window)
        self.assertIs(destination._tabs.currentWidget(), tab)
        self.assertIs(tab.doc, document)
        self.assertEqual(tab.page_index, 1)
        self.assertEqual(tab.view.zoom, 1.5)
        self.assertEqual(destination.workspace_mode, "reader")
        self.assertFalse(destination.updates_enabled)
        self.assertFalse(window._closed_tabs)
        self.assertFalse(tab_drag._dragged_tabs)

    def test_escape_or_unreleased_drag_does_not_detach(self):
        window = self.module.new_window(read_only=True)
        tab = self.opened(window)
        for released, cancelled in ((True, True), (False, False)):
            with self.subTest(released=released, cancelled=cancelled), \
                    patch.object(tab_drag, "QDrag") as drag, \
                    patch.object(tab_drag, "DragReleaseState") as state, \
                    patch.object(window, "detach_tab_at_drop") as detach:
                drag.return_value.exec_.return_value = Qt.IgnoreAction
                state.return_value.finish.return_value = (released, cancelled)
                window._tabs.tabBar()._start_transfer(tab)
                detach.assert_not_called()
            self.assertIs(tab._shell, window)
            self.assertEqual(window._tabs.count(), 1)

    def test_release_over_source_content_keeps_tab(self):
        window = self.module.new_window(read_only=True)
        tab = self.opened(window)
        with patch.object(window, "detach_tab") as detach:
            window.detach_tab_at_drop(tab, window.frameGeometry().center(), QPoint())
            detach.assert_not_called()

    def test_merge_moves_unsaved_document_and_undo_history(self):
        source = self.module.new_window()
        target = self.module.new_window(force_new=True)
        tab = self.opened(source)
        existing = self.opened(target)
        tab._perform_text_edit(lambda: tab.doc.add_note(0, 80, 80, "Unsaved note"))
        self.assertTrue(tab._dirty)
        document, undo = tab.doc, tab._undo_stack

        def drop(_actions):
            mime = drag.return_value.setMimeData.call_args.args[0]
            self.assertTrue(target._tabs.tabBar()._can_accept(mime))
            payload = tab_drag._decode_tab_drag(mime)
            self.assertTrue(target._receive_tab_drop(payload, 0))
            return Qt.MoveAction

        with patch.object(tab_drag, "QDrag") as drag, \
                patch.object(tab_drag, "DragReleaseState") as state:
            drag.return_value.exec_.side_effect = drop
            state.return_value.finish.return_value = (True, False)
            source._tabs.tabBar()._start_transfer(tab)
            mime = drag.return_value.setMimeData.call_args.args[0]
            snapshot = tab_drag._decode_tab_drag(mime)["snapshot"]
        self.assertFalse(os.path.exists(snapshot))
        self.assertIs(target._tabs.widget(0), tab)
        self.assertIs(target._tabs.widget(1), existing)
        self.assertIs(tab.doc, document)
        self.assertIs(tab._undo_stack, undo)
        self.assertTrue(tab._dirty)
        self.assertTrue(any(note["text"] == "Unsaved note" for note in tab.doc.annots(0)))
        tab.undo()
        self.assertFalse(any(note["text"] == "Unsaved note"
                             for note in tab.doc.annots(0)))
        tab.redo()
        self.assertTrue(any(note["text"] == "Unsaved note" for note in tab.doc.annots(0)))

    def test_return_to_source_tab_strip_reorders_without_closing(self):
        window = self.module.new_window(read_only=True)
        tab = self.opened(window)
        # Two tabs may own the same file after merging windows.
        other = self.module.new_window(force_new=True, read_only=True)
        second = self.opened(other)
        window._adopt_tab(other, second, 1)

        def drop(_actions):
            mime = drag.return_value.setMimeData.call_args.args[0]
            bar = window._tabs.tabBar()
            self.assertTrue(bar._can_accept(mime))
            self.assertTrue(window._receive_tab_drop(tab_drag._decode_tab_drag(mime), 2))
            return Qt.MoveAction

        with patch.object(tab_drag, "QDrag") as drag, \
                patch.object(tab_drag, "DragReleaseState") as state:
            drag.return_value.exec_.side_effect = drop
            state.return_value.finish.return_value = (True, False)
            window._tabs.tabBar()._start_transfer(tab)
        self.assertEqual(window._tabs.count(), 2)
        self.assertIs(window._tabs.widget(1), tab)
        self.assertIs(window._tabs.currentWidget(), tab)
        self.assertFalse(window._closed_tabs)

    def test_drag_cancel_tracks_escape_key(self):
        state = tab_drag.DragReleaseState(self.module.new_window(read_only=True))
        try:
            state.eventFilter(None, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
            self.assertTrue(state.cancelled)
        finally:
            state.close()

    def test_rejected_mode_does_not_show_drop_indicator(self):
        reader = self.module.new_window(workspace_mode="reader")
        editor = self.module.new_window(workspace_mode="editor")
        tab = self.opened(reader)
        tab_drag._dragged_tabs["test"] = (reader, tab)
        mime = QMimeData()
        mime.setData(tab_drag._TAB_MIME,
                     ('{"pid":%d,"token":"test","path":"test.pdf"}' % os.getpid()).encode())
        self.assertFalse(editor._tabs.tabBar()._can_accept(mime))

    def test_insert_marker_follows_target_position_and_clears_on_leave(self):
        source = self.module.new_window(read_only=True)
        target = self.module.new_window(force_new=True, read_only=True)
        tab = self.opened(source)
        self.opened(target)
        tab_drag._dragged_tabs["marker"] = (source, tab)
        mime = QMimeData()
        mime.setData(tab_drag._TAB_MIME,
            ('{"pid":%d,"token":"marker","path":"test.pdf"}' % os.getpid()).encode())
        bar = target._tabs.tabBar()
        first = bar.tabRect(0)
        enter = QDragEnterEvent(first.topLeft(), Qt.MoveAction, mime,
                               Qt.LeftButton, Qt.NoModifier)
        bar.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        self.assertEqual(bar._drop_index, 0)
        move = QDragMoveEvent(first.topRight(), Qt.MoveAction, mime,
                             Qt.LeftButton, Qt.NoModifier)
        bar.dragMoveEvent(move)
        self.assertTrue(move.isAccepted())
        self.assertEqual(bar._drop_index, 1)
        bar.dragLeaveEvent(QDragLeaveEvent())
        self.assertIsNone(bar._drop_index)
