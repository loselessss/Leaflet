import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("PyQt5"), "PyQt5 required")
class EditorWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        import fitz
        from pdfeditor import app, settings
        from pdfeditor.i18n import set_language
        set_language("en")
        self.module = app
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.path = root / "pages.pdf"
        with fitz.open() as pdf:
            for index in range(45):
                page = pdf.new_page(width=280, height=400)
                page.insert_text((35, 60), "Page %02d" % (index + 1), fontsize=20)
                page.draw_rect((35, 90, 240, 330), fill=(.8, .9, 1))
            pdf.save(self.path)
        self.original = self.path.read_bytes()
        self.dialogs = []
        self.patchers = [patch.object(settings, "PATH", str(root / "settings.json")),
                         patch.object(settings, "_OLD_PATH", str(root / "absent")),
                         patch.object(app, "_app_windows", [])]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for dialog in self.dialogs:
            dialog.close()
        for window in list(self.module._app_windows):
            for index in range(window._tabs.count()):
                window._tabs.widget(index)._dirty = False
            window.close()
        self.settle()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.directory.cleanup()

    def settle(self):
        for _ in range(6):
            self.application.processEvents()

    def open_editor(self):
        self.window = self.module.new_window(str(self.path), workspace_mode="editor")
        self.window.resize(1080, 800)
        self.settle()
        return self.window._tabs.currentWidget()

    def open_organizer(self, tab):
        from pdfeditor.page_organizer import PageOrganizerDialog
        dialog = PageOrganizerDialog(tab, grid=True)
        self.dialogs.append(dialog)
        dialog.show()
        self.settle()
        return dialog, dialog.panel

    def test_inline_text_cancel_apply_font_and_undo(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        tab.open_page_editor()
        span = tab.doc.spans(0)[0]
        point = QPointF(span['bbox'][0]+1, span['bbox'][1]+1)
        before = tab.doc._doc[0].get_text()
        tab.edit_span_at(point)
        session = tab._inline_text
        self.assertIs(session.input.parent(), tab.view.viewport())
        self.assertTrue(session.input.isVisible())
        self.assertFalse(session.palette.isModal())
        session.input.setText('Cancelled')
        session.cancel()
        self.assertEqual(tab.doc._doc[0].get_text(), before)
        self.assertFalse(tab._undo_stack)
        tab.edit_span_at(point)
        session = tab._inline_text
        session.input.setText('Changed')
        session.font.setCurrentIndex(2)
        self.assertTrue(session.commit())
        self.assertIn('Changed', tab.doc._doc[0].get_text())
        self.assertIn('Times', tab.doc.spans(0)[0]['font'])
        self.assertEqual(len(tab._undo_stack), 1)
        tab.undo()
        self.assertEqual(tab.doc._doc[0].get_text(), before)

    def test_inline_text_page_change_commits_to_original_page(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        tab.open_page_editor()
        tab._add_text_box_at(QPointF(35, 365))
        tab._inline_text.input.setText('Inline page zero')
        tab.show_page(1)
        self.assertIsNone(tab._inline_text)
        self.assertIn('Inline page zero', tab.doc._doc[0].get_text())
        self.assertNotIn('Inline page zero', tab.doc._doc[1].get_text())

    def test_inline_text_failure_retains_input_for_correction(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        tab.open_page_editor()
        tab._add_text_box_at(QPointF(35, 365))
        session = tab._inline_text
        session.font.setCurrentIndex(1)
        session.input.setText('한글')
        with patch('pdfeditor.editing.QMessageBox.warning'):
            self.assertFalse(session.commit())
        self.assertIs(tab._inline_text, session)
        self.assertEqual(session.input.text(), '한글')
        self.assertFalse(tab._undo_stack)
        session.font.setCurrentIndex(0)
        self.assertTrue(session.commit())
        self.assertIn('한글', tab.doc._doc[0].get_text())

    def test_save_commits_active_inline_text(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        tab.open_page_editor()
        tab._add_text_box_at(QPointF(35, 365))
        tab._inline_text.input.setText('Saved inline')
        with patch.object(tab, '_save_document_file') as save:
            save.side_effect = lambda path: self.assertIn('Saved inline', tab.doc._doc[0].get_text())
            self.assertTrue(tab.save())
        self.assertIsNone(tab._inline_text)

    def test_binding_guides_are_undoable_and_dialog_previews(self):
        from pdfeditor.binding_guides import add_guides
        from pdfeditor.binding_guide_dialog import BindingGuideDialog
        tab = self.open_editor()
        before = len(tab.doc._doc[0].get_drawings())
        dialog = BindingGuideDialog(tab.doc, 0, tab)
        self.dialogs.append(dialog)
        self.assertFalse(dialog.preview.pixmap().isNull())
        self.assertTrue(tab.apply_document_change(
            lambda: add_guides(tab.doc, [0], offset=30), structural=False))
        self.assertEqual(len(tab.doc._doc[0].get_drawings()), before+1)
        tab.undo()
        self.assertEqual(len(tab.doc._doc[0].get_drawings()), before)

    def test_object_property_and_mixed_history(self):
        from pdfeditor import editor_objects
        tab = self.open_editor()
        controller = tab._object_controller
        controller.add("rectangle")
        self.assertEqual(len(editor_objects.objects(tab.doc, 0)), 1)
        identity = controller.selected
        controller.fields[0].setValue(20)
        controller.apply()
        moved = editor_objects.objects(tab.doc, 0)[0]["rect"]
        self.assertAlmostEqual(moved[0], 20 * 72 / 25.4)
        tab._perform_text_edit(lambda: tab.doc._doc[0].insert_text((20, 50), "New text"))
        tab.undo()
        self.assertNotIn("New text", tab.doc._doc[0].get_text())
        self.assertEqual(editor_objects.objects(tab.doc, 0)[0]["rect"], moved)
        tab.undo()
        self.assertNotEqual(editor_objects.objects(tab.doc, 0)[0]["rect"], moved)
        tab.undo()
        self.assertEqual(editor_objects.objects(tab.doc, 0), [])
        tab.redo()
        self.assertEqual(editor_objects.objects(tab.doc, 0)[0]["id"], identity)
        tab.redo()
        self.assertEqual(editor_objects.objects(tab.doc, 0)[0]["rect"], moved)
        controller.selected = identity
        controller.refresh()
        count = len(tab._undo_stack)
        controller.apply()
        self.assertEqual(len(tab._undo_stack), count)

    def test_object_drag_preview_cancel_and_commit(self):
        from PyQt5.QtCore import QPointF, QEvent, Qt
        from PyQt5.QtGui import QMouseEvent
        from pdfeditor import editor_objects
        tab = self.open_editor()
        controller = tab._object_controller
        controller.add("rectangle")
        self.settle()
        item = controller.current()
        x0, y0, x1, y1 = item["rect"]
        view = tab.view
        def event(kind, dx=0):
            point = view.mapFromScene(view._page_transforms[0].map(QPointF((x0+x1)/2+dx, (y0+y1)/2)))
            return QMouseEvent(kind, QPointF(point), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        count = len(tab._undo_stack)
        controller.mouse("mousePressEvent", event(QEvent.MouseButtonPress))
        controller.mouse("mouseMoveEvent", event(QEvent.MouseMove, 20))
        self.assertIsNotNone(controller.preview)
        self.assertEqual(len(tab._undo_stack), count)
        self.assertEqual(editor_objects.objects(tab.doc, 0)[0]["rect"], item["rect"])
        controller.cancel()
        self.assertIsNone(controller.preview)
        controller.mouse("mousePressEvent", event(QEvent.MouseButtonPress))
        controller.mouse("mouseMoveEvent", event(QEvent.MouseMove, 20))
        controller.mouse("mouseReleaseEvent", event(QEvent.MouseButtonRelease, 20))
        self.assertEqual(len(tab._undo_stack), count + 1)
        self.assertNotEqual(editor_objects.objects(tab.doc, 0)[0]["rect"], item["rect"])
        tab.set_interaction_mode("hand")
        self.assertFalse(controller.active)

    def test_object_failed_edit_rolls_back(self):
        from pdfeditor import editor_objects
        tab = self.open_editor()
        controller = tab._object_controller
        with patch.object(editor_objects, "_write_data", side_effect=RuntimeError("failure")), \
                patch("pdfeditor.editing.QMessageBox.warning"):
            controller.add("rectangle")
        self.assertEqual(editor_objects.objects(tab.doc, 0), [])
        self.assertEqual(len(tab._undo_stack), 0)
        self.assertEqual(len(tab.doc._doc[0].get_drawings()), 1)

    def render_grid(self, grid):
        grid.stop_rendering()
        for _ in range(40):
            grid._render_visible_thumbnails()
            grid.stop_rendering()
            if all(grid.pages.item(row).data(256) for row in grid.pages.visible_rows()):
                break

    def test_editor_starts_in_detail_without_inline_mode_header(self):
        from pdfeditor.reader_view import TiledPageView
        tab = self.open_editor()
        self.assertFalse(tab.is_editor_overview())
        self.assertTrue(tab._edit_mode)
        self.assertIsNone(tab._page_grid)
        self.assertIsNone(tab._workspace_header)
        self.assertTrue(tab._zoom_input.isVisible())
        self.assertTrue(tab._page_size_label.isVisible())
        self.assertEqual(tab._page_size_label.text(), "98.8 × 141.1 mm")
        self.assertEqual(tab.statusBar().currentMessage(), "")
        self.assertIsInstance(tab.view, TiledPageView)
        self.assertEqual(tab.view.composition_backend, "cpu")
        self.assertTrue(tab.view.canvas._edit_boxes)

    def test_reader_button_uses_existing_save_checked_handoff(self):
        tab = self.open_editor()
        with patch.object(tab, "maybe_save", return_value=False) as save, \
                patch("pdfeditor.process_workspace.application_bridge") as bridge:
            tab._reader_mode_button.click()
        save.assert_called_once()
        bridge.assert_not_called()
        with patch.object(tab, "maybe_save", return_value=True), \
                patch("pdfeditor.process_workspace.application_bridge") as bridge:
            tab._reader_mode_button.click()
        bridge.return_value.launch.assert_called_once_with(
            self.window, tab, mode="reader", handoff_source=True)

    def test_object_commands_use_compact_icons(self):
        from PyQt5.QtCore import Qt
        tab = self.open_editor()
        controller = tab._object_controller
        for action in (controller.action, controller.rectangle_action,
                       controller.image_action):
            self.assertFalse(action.icon().isNull())
            button = tab._interaction_toolbar.widgetForAction(action)
            self.assertEqual(button.toolButtonStyle(), Qt.ToolButtonIconOnly)
            self.assertEqual(button.toolTip(), action.text())

    def test_editor_tiled_view_keeps_zoom_and_edit_interaction_bounded(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        with patch.object(tab, "edit_span_at") as edit:
            tab.view.canvas.clicked.emit(QPointF(40, 60))
        edit.assert_called_once()
        tab.set_zoom(8.0)
        tab.view._plan_tiles()
        self.assertEqual(tab._cache, {})
        self.assertLessEqual(len(tab.view._wanted), 48)
        self.assertTrue(tab.view._pending or tab.view._wanted)
        preview = tab.view._previews[tab.page_index]
        self.assertLessEqual(preview.width() * preview.height(), 1_100_000)

    def test_editor_text_element_can_be_resized(self):
        from PyQt5.QtCore import QPointF
        tab = self.open_editor()
        span = tab.doc.spans(tab.page_index)[0]
        x0, y0, x1, y1 = span["bbox"]

        tab.resize_span_at(QPointF((x0 + x1) / 2, (y0 + y1) / 2), 1.2)
        self.settle()

        resized = tab.doc.spans(tab.page_index)[0]
        self.assertGreater(resized["size"], span["size"])
        self.assertTrue(tab._dirty)

    def test_document_files_drop_anywhere_in_main_window(self):
        from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent
        tab = self.open_editor()
        targets = (self.window._tabs.tabBar(), tab.view.viewport(),
                   tab._interaction_toolbar, tab.statusBar())
        for index, target in enumerate(targets):
            path = self.path.parent / ("dropped-%d.pdf" % index)
            path.write_bytes(self.original)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(path))])
            enter = QDragEnterEvent(
                QPoint(2, 2), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            self.application.sendEvent(target, enter)
            self.assertTrue(enter.isAccepted())
            drop = QDropEvent(
                QPointF(2, 2), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
            self.application.sendEvent(target, drop)
            self.assertTrue(drop.isAccepted())
            self.settle()
            self.assertIsNotNone(self.window._find_open_tab(str(path)))

    def test_page_organizer_keeps_pdf_drop_as_page_insert(self):
        import fitz
        from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
        from PyQt5.QtGui import QDragEnterEvent, QDropEvent
        tab = self.open_editor()
        _dialog, grid = self.open_organizer(tab)
        inserted = self.path.parent / "inserted.pdf"
        with fitz.open() as document:
            document.new_page(width=200, height=300)
            document.save(inserted)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(inserted))])
        position = grid.pages.visualItemRect(grid.pages.item(0)).center()
        enter = QDragEnterEvent(
            QPoint(position), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        self.assertTrue(self.window._page_organizer_owns_drop(grid.pages.viewport()))
        grid.pages.dragEnterEvent(enter)
        self.assertTrue(enter.isAccepted())
        drop = QDropEvent(
            QPointF(position), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        grid.pages.dropEvent(drop)
        self.assertTrue(drop.isAccepted())
        self.assertEqual(tab.doc.page_count, 46)

    def test_separate_organizer_uses_wrapped_grid_without_full_page_raster(self):
        from pdfeditor.core import Document
        tab = self.open_editor()
        original_render = Document.render
        with patch.object(Document, "render", autospec=True, side_effect=original_render) as render:
            dialog, grid = self.open_organizer(tab)
            self.render_grid(grid)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(grid.pages.count(), 45)
        self.assertTrue(render.call_count)
        self.assertTrue(all(call.args[2] < 1 for call in render.call_args_list))
        pages = grid.pages
        self.assertTrue(pages.dragEnabled())
        self.assertTrue(pages.acceptDrops())
        first, second = pages.visualItemRect(pages.item(0)), pages.visualItemRect(pages.item(1))
        self.assertEqual(first.top(), second.top())
        self.assertGreater(second.left(), first.right())

    def test_mouse_drag_starts_with_selected_page_payload(self):
        from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
        from PyQt5.QtGui import QMouseEvent
        from PyQt5.QtTest import QTest
        from pdfeditor.page_organizer import PAGE_MIME
        tab = self.open_editor()
        _dialog, grid = self.open_organizer(tab)
        pages = grid.pages
        point = pages.visualItemRect(pages.item(0)).center()
        with patch("pdfeditor.page_organizer.QDrag") as drag:
            QTest.mousePress(pages.viewport(), Qt.LeftButton, pos=point)
            for offset in (20, 60):
                move = QMouseEvent(QEvent.MouseMove, QPointF(point + QPoint(offset, 0)),
                                   Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
                self.application.sendEvent(pages.viewport(), move)
            QTest.mouseRelease(pages.viewport(), Qt.LeftButton, pos=point + QPoint(60, 0))
        drag.assert_called_once_with(pages)
        mime = drag.return_value.setMimeData.call_args.args[0]
        self.assertEqual(json.loads(bytes(mime.data(PAGE_MIME))), [0])
        drag.return_value.exec_.assert_called_once_with(Qt.MoveAction)

    def test_drop_reorders_selected_pages_with_shared_undo_and_save(self):
        from PyQt5.QtCore import QByteArray, QMimeData, QPointF, Qt
        from PyQt5.QtGui import QDropEvent
        from pdfeditor.page_organizer import PAGE_MIME
        tab = self.open_editor()
        _dialog, grid = self.open_organizer(tab)
        pages = grid.pages
        target = pages.visualItemRect(pages.item(3)).topRight()
        mime = QMimeData()
        mime.setData(PAGE_MIME, QByteArray(json.dumps([0, 1]).encode("ascii")))
        event = QDropEvent(QPointF(target), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
        pages.dropEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertTrue(tab._dirty)
        self.assertFalse(tab.is_editor_overview())
        self.assertIn("Page 03", tab.doc._doc[0].get_text())
        self.assertIn("Page 01", tab.doc._doc[2].get_text())
        self.assertEqual([pages.row(item) for item in pages.selectedItems()], [2, 3])
        self.assertEqual(self.path.read_bytes(), self.original)
        tab.undo()
        self.assertIn("Page 01", tab.doc._doc[0].get_text())
        tab.redo()
        self.assertIn("Page 03", tab.doc._doc[0].get_text())
        self.assertTrue(tab.save())
        import fitz
        with fitz.open(self.path) as saved:
            self.assertIn("Page 03", saved[0].get_text())

    def test_double_click_in_separate_organizer_returns_to_shared_editor(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        tab = self.open_editor()
        document = tab.doc
        dialog, grid = self.open_organizer(tab)
        pages = grid.pages
        point = pages.visualItemRect(pages.item(2)).center()
        QTest.mouseClick(pages.viewport(), Qt.LeftButton, pos=point)
        QTest.mouseDClick(pages.viewport(), Qt.LeftButton, pos=point)
        self.settle()
        self.assertFalse(tab.is_editor_overview())
        self.assertEqual(tab.page_index, 2)
        self.assertTrue(tab._edit_mode)
        self.assertFalse(dialog.isVisible())
        self.assertIs(tab.doc, document)
        self.assertTrue(tab._perform_text_edit(lambda: tab.doc.add_text_box(2, (35, 365), "Kept edit")))
        dialog, grid = self.open_organizer(tab)
        self.assertEqual(grid.pages.currentRow(), 2)
        grid.open_selected_page()
        self.assertIn("Kept edit", tab.doc._doc[2].get_text())
        tab.undo()
        self.assertNotIn("Kept edit", tab.doc._doc[2].get_text())

    def test_long_grid_renders_last_page_and_evicts_old_cards(self):
        tab = self.open_editor()
        dialog, grid = self.open_organizer(tab)
        self.render_grid(grid)
        self.assertTrue(grid.pages.item(0).data(256))
        grid.pages.scrollToBottom()
        self.settle()
        self.render_grid(grid)
        self.assertIn(44, grid.pages.visible_rows())
        self.assertTrue(grid.pages.item(44).data(256))
        self.assertTrue(grid.pages.item(0).icon().isNull())
        self.assertLess(len(grid._rendered_rows), 30)
        dialog.hide()
        self.assertFalse(grid._thumbnail_timer.isActive())

    def test_page_organizer_action_opens_separate_dialog(self):
        tab = self.open_editor()
        with patch("pdfeditor.pages.PageOrganizerDialog") as dialog:
            tab.show_page_organizer()
        dialog.assert_called_once_with(tab, grid=True)
        dialog.return_value.exec_.assert_called_once()

    def test_editor_omits_view_modes_in_detail(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtTest import QTest
        tab = self.open_editor()
        for action in (tab._presentation_act, tab._full_screen_act):
            self.assertFalse(action.isVisible())
            self.assertFalse(action.isEnabled())
            self.assertTrue(action.shortcut().isEmpty())
            self.assertNotIn(action, tab._interaction_toolbar.actions())
            action.trigger()
        for key in (Qt.Key_F5, Qt.Key_F11):
            QTest.keyClick(tab, key)
        tab.toggle_presentation_mode()
        tab.toggle_full_screen()
        self.window.toggle_presentation()
        self.window.toggle_full_screen()
        self.settle()
        self.assertFalse(self.window.presentation_active)
        self.assertFalse(self.window.isFullScreen())
        self.assertFalse(tab.is_editor_overview())
        self.assertTrue(tab._interaction_toolbar.isVisible())

    def test_wheel_at_page_edge_does_not_leave_editor_page(self):
        tab = self.open_editor()
        tab.view._flip_accum = tab.view.FLIP_THRESHOLD
        with patch.object(tab, "next_page") as next_page, \
                patch.object(tab, "prev_page") as prev_page:
            tab.on_wheel_flip(1)
            tab.on_wheel_flip(-1)
        next_page.assert_not_called()
        prev_page.assert_not_called()
        self.assertEqual(tab.view._flip_accum, 0)

    def test_editor_label_follows_language_and_dirty_title(self):
        from pdfeditor.i18n import set_language
        tab = self.open_editor()
        try:
            for language, suffix in (("ko", "[편집/CPU]"), ("en", "[Edit/CPU]")):
                set_language(language)
                tab._dirty = False
                tab._update_title()
                self.assertEqual(tab.tab_title(), "pages.pdf " + suffix)
                self.assertEqual(self.window._tabs.tabText(0), tab.tab_title())
                self.assertEqual(self.window.windowTitle(), "pages.pdf " + suffix + " — sPDF")
                tab.mark_dirty()
                self.assertEqual(tab.tab_title(), "*pages.pdf " + suffix)
                self.assertEqual(self.window.windowTitle(), "*pages.pdf " + suffix + " — sPDF")
        finally:
            set_language("en")

    def test_window_title_tracks_actual_render_device(self):
        from types import SimpleNamespace

        tab = self.open_editor()
        tab.view._d2d_surface = Mock(
            info=SimpleNamespace(driver="hardware"))
        tab._update_title()
        self.assertEqual(self.window.windowTitle(), "pages.pdf [Edit/CPU] — sPDF")
        tab.view._rasterized_pages = {0: "GPU"}
        tab.view._notify_render_device()
        self.assertEqual(self.window.windowTitle(), "pages.pdf [Edit/GPU] — sPDF")
        tab.view._rasterized_pages = {0: "CPU+GPU"}
        tab.view._notify_render_device()
        self.assertEqual(self.window.windowTitle(), "pages.pdf [Edit/CPU+GPU] — sPDF")
        tab.view._d2d_surface.info.driver = "warp"
        tab._update_title()
        self.assertEqual(self.window.windowTitle(), "pages.pdf [Edit/CPU] — sPDF")
        tab.view._d2d_surface = None

    def test_reorder_failure_restores_document_and_history(self):
        tab = self.open_editor()
        _dialog, grid = self.open_organizer(tab)
        def failure(_order):
            tab.doc._doc.delete_page(0)
            raise RuntimeError("test failed move")
        with patch.object(tab.doc, "reorder_pages", side_effect=failure), \
                patch("pdfeditor.document_tools.QMessageBox.warning"):
            self.assertFalse(grid.move_pages([0], 3))
        self.assertEqual(tab.doc.page_count, 45)
        self.assertIn("Page 01", tab.doc._doc[0].get_text())
        self.assertEqual(tab._undo_stack, [])
        self.assertFalse(tab._dirty)

    def test_reader_prominent_button_and_embedded_behavior(self):
        reader = self.module.new_window(str(self.path), workspace_mode="reader")
        self.settle()
        reading = reader._tabs.currentWidget()
        button = reading._editor_mode_button
        self.assertEqual(button.text(), "Edit mode")
        self.assertFalse(button.property("accent"))
        self.assertGreaterEqual(button.height(), 34)
        self.assertTrue(reading._interaction_toolbar.isAncestorOf(button))
        self.assertIsNone(reading._workspace_header)
        with patch.object(reader, "open_editor") as launch:
            button.click()
        launch.assert_called_once_with(reading)
        embedded = self.module.new_window(str(self.path))
        self.settle()
        tab = embedded._tabs.currentWidget()
        self.assertIsNone(tab._page_grid)
        self.assertIsNone(tab._workspace_header)
        with patch("pdfeditor.pages.PageOrganizerDialog") as dialog:
            tab.show_page_organizer()
        dialog.assert_called_once_with(tab, grid=False)
        dialog.return_value.exec_.assert_called_once()


if __name__ == "__main__":
    unittest.main()
