import importlib.util
import os
import unittest
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


HAS_PYQT5 = importlib.util.find_spec("PyQt5") is not None


@unittest.skipUnless(HAS_PYQT5, "PyQt5가 설치된 환경에서 실행")
class EmbeddedModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        # Other localization tests intentionally switch the process-wide
        # catalog. Embedded-mode assertions use the international default.
        from pdfeditor.i18n import set_language
        set_language("en")

    @contextmanager
    def document_windows(self):
        import fitz
        from pdfeditor import app, settings

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "reader.pdf"
            with fitz.open() as pdf:
                page = pdf.new_page()
                page.insert_text((72, 72), "Read this sentence.")
                page.add_text_annot((100, 100), "Existing note")
                pdf.new_page()
                pdf.set_toc([[1, "Start", 1]])
                pdf.save(source)
            with patch.object(settings, "PATH", str(root / "settings.json")), \
                    patch.object(settings, "_OLD_PATH", str(root / "absent")), \
                    patch.object(app, "_app_windows", []):
                try:
                    yield app, source
                finally:
                    for window in list(app._app_windows):
                        for index in range(window._tabs.count()):
                            window._tabs.widget(index)._dirty = False
                        window.close()
                    for _ in range(4):
                        self.app.processEvents()

    def test_read_only_window_keeps_reading_and_blocks_all_edit_commands(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QAction, QAbstractItemView

        with self.document_windows() as (module, source):
            window = module.new_window(read_only=True)
            tab = window.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            self.assertTrue(window.read_only)
            self.assertTrue(tab.read_only)
            self.assertTrue(tab.doc.read_only)
            self.assertFalse(window.updates_enabled)
            self.assertIsNone(window._update_service)
            self.assertIsNone(window._recovery_store)
            for action in (tab._save_act, tab._edit_act, tab._pages_act,
                           tab._undo_act, tab._redo_act, tab._rotate_cw_act):
                self.assertFalse(action.isVisible())
                self.assertFalse(action.isEnabled())
                action.trigger()
            for owner in (window, tab):
                for name in dir(type(owner)):
                    method = getattr(owner, name)
                    if callable(method) and getattr(method, "requires_editing", False):
                        with self.subTest(command=name):
                            self.assertFalse(method())
            tab.set_edit_mode(True)
            self.assertFalse(tab._edit_mode)
            self.assertFalse(tab._dirty)
            self.assertEqual(tab._undo_stack, [])
            self.assertIsNone(tab._ocr_worker)
            with self.assertRaises(PermissionError):
                tab.doc.rotate_page(0, 90)

            tree = tab.bookmarks
            self.assertEqual(tree.dragDropMode(), QAbstractItemView.NoDragDrop)
            self.assertFalse(tree.topLevelItem(0).flags() & Qt.ItemIsEditable)
            self.assertTrue(tab._print_act.isEnabled())
            self.assertTrue(tab._search_act.isEnabled())
            shortcuts = {action.shortcut().toString(): action
                         for action in tab.findChildren(QAction)}
            for shortcut in ("Ctrl+C", "Ctrl+A", "Ctrl+F", "Ctrl+P"):
                self.assertTrue(shortcuts[shortcut].isEnabled())
            tab.select_all()
            tab.copy_selection()
            self.assertIn("Read this sentence.", self.app.clipboard().text())
            tab.show_page(1)
            self.assertEqual(tab.page_index, 1)
            tab.set_zoom(1.25)
            self.assertEqual(tab.view.zoom, 1.25)
            note = tab.doc.annots(0)[0]
            with patch("pdfeditor.annots.QMessageBox.exec_"), patch(
                    "pdfeditor.annots.QInputDialog.getMultiLineText") as edit:
                tab.edit_annot(note)
                edit.assert_not_called()
            self.assertFalse(tab._dirty)

    def test_new_windows_inherit_policy_and_cannot_reuse_opposite_mode(self):
        with self.document_windows() as (module, source):
            editor = module.new_window()
            reader = module.new_window(read_only=True)
            self.assertIsNot(editor, reader)
            self.assertIs(module.new_window(read_only=False), editor)
            self.assertIs(module.new_window(read_only=True), reader)
            child = reader.new_window()
            self.assertIsNot(child, reader)
            self.assertTrue(child.read_only)
            self.assertFalse(child.updates_enabled)
            tab = editor.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            self.assertFalse(reader._adopt_tab(editor, tab, 0))
            self.assertEqual(editor._tabs.indexOf(tab), 0)
            self.assertEqual(reader._tabs.count(), 0)
            self.assertFalse(reader.open_snapshot_in_tab("missing.pdf", str(source)))

    def test_read_only_does_not_enable_self_updates_or_recovery(self):
        from pdfeditor.app import AppWindow
        with patch("pdfeditor.app.GitHubUpdateService") as updater:
            window = AppWindow(read_only=True)
            try:
                updater.assert_not_called()
                self.assertIsNone(window._recovery_store)
            finally:
                window.close()

    def test_annotation_mode_autosaves_and_restores_without_changing_pdf(self):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtTest import QTest
        from PyQt5.QtWidgets import QAction
        from pdfeditor.core import Document

        with self.document_windows() as (module, source):
            original = source.read_bytes()
            window = module.new_window(read_only=True, annotations_enabled=True)
            tab = window.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            self.assertTrue(tab.annotations_enabled)
            self.assertTrue(tab._save_act.isEnabled())
            self.assertFalse(tab._edit_act.isVisible())
            self.assertFalse(tab._pages_act.isVisible())
            menu = [action.text() for action in tab.findChildren(QAction)]
            self.assertIn("Save PDF with annotations...", menu)
            tab._annotation_timer.setInterval(20)
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText",
                       return_value=("New annotation", True)):
                tab._add_note_at(QPointF(80, 80))
            self.assertTrue(tab._dirty)
            self.assertTrue(tab._annotation_timer.isActive())
            self.assertTrue(tab._undo_act.isEnabled())
            QTest.qWait(60)
            self.assertFalse(tab._dirty)
            self.assertEqual(source.read_bytes(), original)
            tab.undo()
            self.assertEqual(len(tab.doc.annots(0)), 1)
            QTest.qWait(60)
            tab.redo()
            self.assertEqual(len(tab.doc.annots(0)), 2)
            # Closing immediately must flush the pending timer's changes.
            self.assertTrue(tab.maybe_save())
            self.assertFalse(tab._dirty)
            readback = Document(str(source), read_only=True, annotations_enabled=False)
            try:
                self.assertEqual(readback.annots(0)[-1]["text"], "New annotation")
            finally:
                readback.close()
            child = window.new_window()
            self.assertEqual(child.access_policy, window.access_policy)
            reader = module.new_window(read_only=True, annotations_enabled=False)
            manual = module.new_window(read_only=True, annotations_enabled=True,
                                       autosave_annotations=False)
            self.assertIsNot(reader, window)
            self.assertIsNot(manual, window)
            self.assertFalse(manual._adopt_tab(window, tab, 0))

    def test_annotation_autosave_off_requires_save_and_can_cancel_close(self):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtWidgets import QMessageBox
        with self.document_windows() as (module, source):
            window = module.new_window(read_only=True, annotations_enabled=True,
                                       autosave_annotations=False)
            tab = window.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText",
                       return_value=("Manual annotation", True)):
                tab._add_note_at(QPointF(80, 80))
            self.assertFalse(tab._annotation_timer.isActive())
            sidecar = Path(str(source) + ".spdf-annotations.json")
            self.assertFalse(sidecar.exists())
            with patch("pdfeditor.annots.QMessageBox.exec_", return_value=QMessageBox.Cancel):
                self.assertFalse(tab.maybe_save())
            self.assertTrue(tab._dirty)
            self.assertTrue(tab.save())
            self.assertTrue(sidecar.exists())
            self.assertFalse(tab._dirty)

    def test_annotation_save_failure_keeps_pending_edits_and_cancelable_close(self):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtWidgets import QMessageBox
        with self.document_windows() as (module, source):
            window = module.new_window(read_only=True, annotations_enabled=True)
            tab = window.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText",
                       return_value=("Do not lose this", True)):
                tab._add_note_at(QPointF(80, 80))
            with patch.object(tab.doc, "save_annotations", side_effect=OSError("disk full")):
                tab._autosave_annotations()
                self.assertTrue(tab._dirty)
                self.assertIn("could not be saved", tab.statusBar().currentMessage())
                with patch("pdfeditor.annots.QMessageBox.exec_", return_value=QMessageBox.Cancel):
                    self.assertFalse(tab.maybe_save())
                target = source.with_name("exported.pdf")
                with patch("pdfeditor.annotation_ui.QFileDialog.getSaveFileName",
                           return_value=(str(target), "PDF")):
                    self.assertTrue(tab.save_as_dialog())
                self.assertTrue(target.exists())
                self.assertEqual(tab.doc.path, str(source))
                self.assertTrue(tab._dirty)
            self.assertTrue(tab.save())

    def test_annotation_mode_can_edit_existing_note_and_delete_with_undo(self):
        with self.document_windows() as (module, source):
            window = module.new_window(read_only=True, annotations_enabled=True,
                                       autosave_annotations=False)
            tab = window.open_in_tab(str(source))
            for _ in range(4):
                self.app.processEvents()
            note = tab.doc.annots(0)[0]
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText",
                       return_value=("Revised original note", True)):
                tab.edit_annot(note)
            self.assertEqual(tab.doc.annots(0)[0]["text"], "Revised original note")
            tab.delete_annot(tab.doc.annots(0)[0])
            self.assertEqual(tab.doc.annots(0), [])
            tab.undo()
            self.assertEqual(tab.doc.annots(0)[0]["text"], "Revised original note")
            tab.undo()
            self.assertEqual(tab.doc.annots(0)[0]["text"], "Existing note")

    def test_host_default_never_reuses_or_inherits_standalone_updater(self):
        with self.document_windows() as (module, source):
            with patch("pdfeditor.app.GitHubUpdateService"), patch(
                    "pdfeditor.app.settings.automatic_update_check_due", return_value=False):
                standalone = module.new_window(updates_enabled=True)
                embedded = module.new_window()
                self.assertIsNot(embedded, standalone)
                self.assertFalse(embedded.updates_enabled)
                self.assertIsNone(embedded._update_service)

    def settle(self):
        from PyQt5.QtTest import QTest
        QTest.qWait(40)
        for _ in range(6):
            self.app.processEvents()

    def test_reader_dispatches_editor_process_with_source_and_update_policy(self):
        from pdfeditor.reader_view import ReaderPageView
        with self.document_windows() as (module, source):
            reader = module.new_window(workspace_mode="reader")
            tab = reader.open_in_tab(str(source))
            self.settle()
            with patch("pdfeditor.process_workspace.application_bridge") as bridge:
                child = reader.open_editor(tab)
                self.assertIs(child, bridge.return_value.launch.return_value)
                bridge.return_value.launch.assert_called_once_with(
                    reader, tab, recovery=False, handoff_source=True)
            self.assertIsInstance(tab.view, ReaderPageView)
            self.assertFalse(reader.updates_enabled)
            self.assertTrue(tab._open_editor_act.isVisible())
            self.assertFalse(tab._edit_act.isVisible())
            child = reader.new_window()
            self.assertEqual(child.workspace_mode, "reader")
            self.assertFalse(child.updates_enabled)

    def test_editor_hands_saved_document_to_reader_and_cancel_keeps_tab(self):
        with self.document_windows() as (module, source):
            editor = module.new_window(str(source), workspace_mode="editor")
            self.settle()
            tab = editor._tabs.currentWidget()
            with patch("pdfeditor.process_workspace.application_bridge") as bridge, \
                    patch.object(tab, "maybe_save", return_value=True) as maybe_save:
                child = editor.open_reader()
            self.assertIs(child, bridge.return_value.launch.return_value)
            maybe_save.assert_called_once_with()
            bridge.return_value.launch.assert_called_once_with(
                editor, tab, mode="reader", handoff_source=True)

            with patch("pdfeditor.process_workspace.application_bridge") as bridge, \
                    patch.object(tab, "maybe_save", return_value=False):
                self.assertIsNone(editor.open_reader())
            bridge.assert_not_called()
            self.assertGreaterEqual(editor._tabs.indexOf(tab), 0)

    def test_successful_handoff_closes_only_the_source_tab(self):
        with self.document_windows() as (module, source):
            second_path = source.with_name("second.pdf")
            second_path.write_bytes(source.read_bytes())
            reader = module.new_window(str(source), workspace_mode="reader")
            self.settle()
            first = reader._find_open_tab(str(source))
            second = reader.open_in_tab(str(second_path))
            self.settle()
            reader._complete_workspace_handoff(first)
            self.settle()
            self.assertEqual(reader._tabs.count(), 1)
            self.assertIs(reader._tabs.widget(0), second)
            self.assertIn(reader, module._app_windows)
            self.assertTrue(reader.isVisible())

    def test_embedded_reader_has_no_editor_escape_hatch(self):
        from pdfeditor.widgets import PageView
        with self.document_windows() as (module, source):
            embedded = module.new_window(read_only=True)
            tab = embedded.open_in_tab(str(source))
            self.settle()
            self.assertIsInstance(tab.view, PageView)
            self.assertIsNone(embedded.open_editor(tab))
            self.assertIsNone(tab._open_editor_act)
            standalone = module.new_window(workspace_mode="reader")
            self.assertIsNot(standalone, embedded)
            self.assertFalse(standalone._adopt_tab(embedded, tab, 0))
            with self.assertRaises(ValueError):
                module.new_window(read_only=True, workspace_mode="editor")

    def test_empty_recovery_does_not_open_editor_at_reader_startup(self):
        with self.document_windows() as (module, source):
            reader = module.new_window(workspace_mode="reader")
            reader._recovery_store = Mock()
            reader._recovery_store.available.return_value = []
            with patch.object(reader, "open_editor") as open_editor:
                reader.show_recovery(automatic=True)
            open_editor.assert_not_called()

    def test_recovery_prompt_is_not_reentered_by_startup_timer(self):
        with self.document_windows() as (module, source):
            editor = module.new_window(workspace_mode="editor")
            with patch("pdfeditor.recovery_ui.show_recovery_dialog",
                       side_effect=lambda *args, **kwargs: editor.show_recovery(automatic=True)) as prompt:
                editor.show_recovery()
                editor.show_recovery(automatic=True)
            prompt.assert_called_once_with(editor, automatic=False)

    def test_repeated_workspace_close_and_collection_keeps_save_usable(self):
        import gc
        with self.document_windows() as (module, source):
            for _ in range(6):
                window = module.new_window(str(source), workspace_mode="editor")
                self.settle()
                self.assertTrue(window._tabs.currentWidget().save())
                window.close()
                self.settle()
                gc.collect()
                reader = module.new_window(str(source), workspace_mode="reader")
                self.settle()
                self.assertTrue(reader._tabs.currentWidget().doc.render(0, .2)[3])
                reader.close()
                self.settle()
                gc.collect()

    def test_reader_and_embedded_windows_keep_view_modes(self):
        from pdfeditor.i18n import set_language
        set_language("en")
        with self.document_windows() as (module, source):
            for options in ({"workspace_mode": "reader"}, {}, {"read_only": True}):
                with self.subTest(options=options):
                    window = module.new_window(str(source), **options)
                    self.settle()
                    tab = window._tabs.currentWidget()
                    self.assertNotIn("[Edit-only]", tab.tab_title())
                    for action, shortcut in ((tab._presentation_act, "F5"),
                                             (tab._full_screen_act, "F11")):
                        self.assertTrue(action.isVisible())
                        self.assertTrue(action.isEnabled())
                        self.assertEqual(action.shortcut().toString(), shortcut)
                        self.assertIn(action, tab._interaction_toolbar.actions())
                    window.toggle_full_screen()
                    self.assertTrue(window.isFullScreen())
                    window.toggle_full_screen()
                    window.toggle_presentation()
                    self.assertTrue(window.presentation_active)
                    window.toggle_presentation()
                    self.assertFalse(window.presentation_active)

    def test_reader_rotation_actions_are_view_only_and_thumbnails_follow(self):
        from PyQt5.QtCore import Qt
        with self.document_windows() as (module, source):
            original = source.read_bytes()
            reader = module.new_window(workspace_mode="reader")
            tab = reader.open_in_tab(str(source))
            self.settle()
            for action in (tab._rotate_cw_act, tab._rotate_ccw_act):
                self.assertTrue(action.isVisible())
                self.assertTrue(action.isEnabled())
                self.assertIn(action, tab._interaction_toolbar.actions())
            self.assertEqual(tab._rotate_cw_act.shortcut().toString(), "Ctrl+]")
            self.assertEqual(tab._rotate_ccw_act.shortcut().toString(), "Ctrl+[")
            tab._rotate_cw_act.trigger()
            self.settle()
            tab._render_visible_thumbs()
            self.assertEqual(tab.view.page_rotation(0), 90)
            self.assertGreater(tab.thumbs.item(0).data(Qt.UserRole + 1), 1)
            self.assertEqual(tab.doc._doc[0].rotation, 0)
            self.assertFalse(tab.doc._doc.is_dirty)
            self.assertFalse(tab._dirty)
            self.assertEqual(tab._undo_stack, [])
            self.assertFalse(tab._save_act.isEnabled())
            self.assertEqual(source.read_bytes(), original)
            tab._rotate_ccw_act.trigger()
            self.assertEqual(tab.view.page_rotation(0), 0)
            editor = module.new_window(str(source), workspace_mode="editor")
            self.settle()
            editing = editor._tabs.currentWidget()
            editing._rotate_cw_act.trigger()
            self.assertEqual(editing.doc._doc[0].rotation, 90)
            self.assertTrue(editing._dirty)
            editing.undo()
            self.assertEqual(editing.doc._doc[0].rotation, 0)

    def test_switching_and_closing_tabs_keeps_menu_bars_alive(self):
        from PyQt5 import sip
        from PyQt5.QtTest import QTest
        with self.document_windows() as (module, source):
            reader = module.new_window(workspace_mode="reader")
            first = reader.open_in_tab(str(source))
            other = source.with_name("second.pdf")
            other.write_bytes(source.read_bytes())
            second = reader.open_in_tab(str(other))
            self.settle()
            for tab in (first, second, first):
                reader._tabs.setCurrentWidget(tab)
                QTest.qWait(20)
                self.assertFalse(sip.isdeleted(tab._menubar))
                self.assertIs(reader.menuBar(), tab._menubar)
            reader.close_tab(first)
            QTest.qWait(30)
            self.assertFalse(sip.isdeleted(second._menubar))
            self.assertIs(reader.menuBar(), second._menubar)

    def test_editor_saves_and_refreshes_reader_without_moving_view(self):
        from PyQt5.QtWidgets import QMessageBox
        with self.document_windows() as (module, source):
            reader = module.new_window(workspace_mode="reader")
            tab = reader.open_in_tab(str(source))
            self.settle()
            tab.show_page(1)
            tab.set_zoom(2)
            tab._render_current()
            self.settle()
            tab.view.verticalScrollBar().setValue(250)
            state = tab.capture_view_state()
            editor = module.new_window(str(source), workspace_mode="editor")
            self.settle()
            editing = editor._tabs.currentWidget()
            editing.doc.add_text_box(1, (72, 100), "Saved change")
            editing.mark_dirty()
            with patch.object(QMessageBox, "critical") as errors:
                self.assertTrue(editing.save())
            errors.assert_not_called()
            self.settle()
            self.assertIn("Saved change", tab.doc._doc[1].get_text())
            self.assertEqual(tab.page_index, state["page"])
            self.assertEqual(tab.view.zoom, state["zoom"])
            self.assertAlmostEqual(tab.capture_view_state()["vertical"],
                                   state["vertical"], places=2)
            self.assertFalse(editing._dirty)
            self.assertFalse(tab._dirty)

    def test_failed_replace_preserves_edits_and_reopens_reader(self):
        with self.document_windows() as (module, source):
            original = source.read_bytes()
            reader = module.new_window(workspace_mode="reader")
            tab = reader.open_in_tab(str(source))
            self.settle()
            editor = module.new_window(str(source), workspace_mode="editor")
            self.settle()
            editing = editor._tabs.currentWidget()
            editing.doc.add_text_box(1, (72, 100), "Keep unsaved")
            editing.mark_dirty()
            with patch("pdfeditor.core.os.replace", side_effect=PermissionError("locked")), \
                    patch("pdfeditor.annots.QMessageBox.critical"):
                self.assertFalse(editing.save())
            self.settle()
            self.assertTrue(editing._dirty)
            self.assertIn("Keep unsaved", editing.doc._doc[1].get_text())
            self.assertNotIn("Keep unsaved", tab.doc._doc[1].get_text())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(source.parent.glob(".spdf-save-*")), [])
            self.assertTrue(editing.save())
            self.settle()
            self.assertIn("Keep unsaved", tab.doc._doc[1].get_text())

    def test_save_as_does_not_redirect_original_reader(self):
        with self.document_windows() as (module, source):
            original = source.read_bytes()
            reader = module.new_window(workspace_mode="reader")
            tab = reader.open_in_tab(str(source))
            self.settle()
            editor = module.new_window(str(source), workspace_mode="editor")
            self.settle()
            editing = editor._tabs.currentWidget()
            editing.doc.add_text_box(1, (72, 100), "New copy")
            editing.mark_dirty()
            target = source.with_name("copy.pdf")
            with patch("pdfeditor.annots.QFileDialog.getSaveFileName",
                       return_value=(str(target), "PDF")):
                self.assertTrue(editing.save_as_dialog())
            self.settle()
            self.assertEqual(editing.doc.path, str(target))
            self.assertEqual(tab.doc.path, str(source))
            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(target.exists())

    def test_editor_respects_pdf_edit_permissions(self):
        import fitz
        with self.document_windows() as (module, source):
            protected = source.with_name("protected.pdf")
            with fitz.open(source) as pdf:
                pdf.save(protected, encryption=fitz.PDF_ENCRYPT_AES_256,
                         owner_pw="owner", user_pw="reader",
                         permissions=fitz.PDF_PERM_COPY | fitz.PDF_PERM_PRINT)
            reader = module.new_window(workspace_mode="reader")
            with patch("pdfeditor.app.QInputDialog.getText", return_value=("reader", True)):
                tab = reader.open_in_tab(str(protected))
                self.settle()
                with patch("pdfeditor.app.QMessageBox.critical") as error:
                    editor = module.new_window(str(protected), workspace_mode="editor")
                    self.settle()
            self.assertEqual(editor._tabs.count(), 0)
            error.assert_called_once()
            self.assertTrue(tab.doc.read_only)

    def test_text_edit_properties_undo_and_failed_operation_rollback(self):
        from PyQt5.QtCore import QPointF
        from PyQt5.QtWidgets import QDialog
        with self.document_windows() as (module, source):
            editor = module.new_window(workspace_mode="editor")
            tab = editor.open_in_tab(str(source))
            self.settle()
            from PyQt5.QtGui import QColor
            tab.open_page_editor()
            tab._add_text_box_at(QPointF(72, 180))
            session = tab._inline_text
            session.input.setText("Blue text")
            session.size.setValue(18)
            session.color = QColor(0, 0, 255)
            self.assertTrue(session.commit())
            self.assertTrue(tab._dirty)
            spans = tab.doc.spans(0)
            added = next(span for span in spans if "Blue text" in span["text"])
            self.assertAlmostEqual(added["size"], 18)
            self.assertEqual(added["rgb"], (0, 0, 1))
            tab.undo()
            self.assertNotIn("Blue text", tab.doc._doc[0].get_text())
            tab.redo()
            self.assertIn("Blue text", tab.doc._doc[0].get_text())
            history = len(tab._undo_stack)

            def failing_edit():
                tab.doc.delete_page(1)
                raise ValueError("test failure after mutation")

            with patch("pdfeditor.editing.QMessageBox.warning"):
                self.assertFalse(tab._perform_text_edit(failing_edit))
            self.assertEqual(tab.doc.page_count, 2)
            self.assertEqual(len(tab._undo_stack), history)
            self.assertIn("Blue text", tab.doc._doc[0].get_text())

    def test_text_edit_dialog_defaults_and_cancelled_color(self):
        from PyQt5.QtGui import QColor
        from pdfeditor.text_edit_dialog import TextEditDialog
        dialog = TextEditDialog(text="Sample", size=14, color=(1, 0, 0), replacing=True)
        self.assertEqual(dialog.values(), ("Sample", 14, (1, 0, 0)))
        with patch("pdfeditor.text_edit_dialog.QColorDialog.getColor", return_value=QColor()):
            dialog.choose_color()
        self.assertEqual(dialog.values()[2], (1, 0, 0))
        dialog.close()

    def test_internal_module_window_disables_all_update_entry_points(self):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QAction, QStatusBar
        from pdfeditor.app import AppWindow

        with patch("pdfeditor.app.settings.ui_language", return_value="en"):
            window = AppWindow()
        menu_texts = [action.text() for action in window.findChildren(QAction)]

        self.assertFalse(window.updates_enabled)
        self.assertIsNone(window._update_service)
        self.assertIsNone(window._recovery_store)
        self.assertEqual(
            window.findChildren(
                QStatusBar, options=Qt.FindDirectChildrenOnly), [])
        self.assertFalse(window.check_for_updates(manual=True))
        self.assertNotIn("Check for Updates...", menu_texts)
        self.assertNotIn("Display Renderer", menu_texts)
        window.close()

    def test_standalone_window_keeps_update_feature(self):
        from PyQt5.QtWidgets import QAction
        from pdfeditor.app import AppWindow

        cleanup_flag = getattr(self.app, "_spdf_update_cleanup_started", None)
        if hasattr(self.app, "_spdf_update_cleanup_started"):
            del self.app._spdf_update_cleanup_started
        try:
            cleanup_patch = patch(
                "pdfeditor.app.GitHubUpdateService.cleanup_downloads")
            with patch("pdfeditor.app.settings.automatic_update_check_due",
                       return_value=False), patch(
                           "pdfeditor.app.settings.ui_language",
                           return_value="en"), cleanup_patch as cleanup:
                window = AppWindow(updates_enabled=True)
            cleanup.assert_called_once()
        finally:
            if cleanup_flag is None:
                if hasattr(self.app, "_spdf_update_cleanup_started"):
                    del self.app._spdf_update_cleanup_started
            else:
                self.app._spdf_update_cleanup_started = cleanup_flag
        menu_texts = [action.text() for action in window.findChildren(QAction)]

        self.assertTrue(window.updates_enabled)
        self.assertIsNotNone(window._update_service)
        self.assertIn("Check for Updates...", menu_texts)
        self.assertIn("Display Renderer", menu_texts)
        window.close()

    def test_unavailable_direct2d_cannot_be_selected(self):
        from PyQt5.QtWidgets import QAction
        from pdfeditor.app import AppWindow

        unavailable = SimpleNamespace(available=False, driver="none")
        with patch("pdfeditor.app.probe_d2d_backend", return_value=unavailable), \
                patch("pdfeditor.app.settings.automatic_update_check_due",
                      return_value=False), \
                patch("pdfeditor.app.settings.ui_language", return_value="en"):
            window = AppWindow(updates_enabled=True)
        actions = {action.text(): action for action in window.findChildren(QAction)}
        self.assertIn("GPU (Direct2D)", actions)
        self.assertFalse(actions["GPU (Direct2D)"].isEnabled())
        window.close()


if __name__ == "__main__":
    unittest.main()
