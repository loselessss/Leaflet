import time
import unittest
from unittest.mock import patch

from tests import test_embedded_mode as fixtures


@unittest.skipUnless(fixtures.HAS_PYQT5, "PyQt5 required")
class AnnotationManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        fixtures.EmbeddedModeTests.setUp(self)
        backend = patch("pdfeditor.settings.render_backend", return_value="cpu")
        backend.start()
        self.addCleanup(backend.stop)

    def windows(self):
        return fixtures.EmbeddedModeTests.document_windows(self)

    def settle(self, manager):
        from PyQt5.QtTest import QTest
        deadline = time.monotonic() + 5
        while manager._timer.isActive() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(1)
        self.assertFalse(manager._timer.isActive())

    def open_manager(self, module, source, **kwargs):
        window = module.new_window(**kwargs)
        tab = window.open_in_tab(str(source))
        for _ in range(4):
            self.app.processEvents()
        tab.toggle_notes_panel()
        manager = tab._annotation_manager
        self.settle(manager)
        return window, tab, manager

    def select(self, manager, predicate):
        from PyQt5.QtCore import Qt
        for index in range(manager.table.topLevelItemCount()):
            item = manager.table.topLevelItem(index)
            if predicate(item.data(0, Qt.UserRole)):
                manager.table.setCurrentItem(item)
                return item
        self.fail("Annotation was not listed")

    def visible_count(self, manager):
        return sum(not manager.table.topLevelItem(i).isHidden()
                   for i in range(manager.table.topLevelItemCount()))

    def test_modeless_window_searches_notes_and_highlighted_text(self):
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            tab.doc.add_highlight(0, [(70, 58, 190, 78)])
            tab.doc.add_note(1, 80, 100, "Reviewer comment")
            tab._annotation_changed()
            self.settle(manager)
            self.assertTrue(manager.isWindow())
            self.assertFalse(manager.isModal())
            self.assertIs(manager.owner, tab)
            self.assertEqual(manager.table.topLevelItemCount(), 3)
            from pdfeditor.i18n import translate_tree
            translate_tree(manager)
            self.assertIn("3 / 3", manager.count_label.text())
            manager.search.setText("sentence")
            self.assertEqual(self.visible_count(manager), 1)
            self.select(manager, lambda item: item["kind"] == "Highlight")
            self.assertIn("Read this sentence.", manager.details.toPlainText())
            manager.search.clear()
            manager.kind_filter.setCurrentIndex(1)
            self.assertEqual(self.visible_count(manager), 2)
            manager.kind_filter.setCurrentIndex(2)
            self.assertEqual(self.visible_count(manager), 1)
            translate_tree(manager)
            self.assertIn("1 / 3", manager.count_label.text())
            tab.toggle_notes_panel()
            self.assertIs(tab._annotation_manager, manager)
            self.assertTrue(manager.isVisible())

    def test_comment_edit_delete_undo_and_pdf_save_preserve_highlight(self):
        from PyQt5.QtWidgets import QMessageBox
        import fitz
        with self.windows() as (module, source):
            original = source.read_bytes()
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            tab.doc.add_highlight(0, [(70, 58, 190, 78)])
            tab._annotation_changed()
            self.settle(manager)
            self.select(manager, lambda data: data["kind"] == "Highlight")
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText", return_value=("Check this result", True)):
                manager.edit_selected()
            self.settle(manager)
            marked = next(item for item in tab.doc.annots(0) if item["kind"] == "Highlight")
            self.assertEqual(marked["text"], "Check this result")
            self.assertEqual(source.read_bytes(), original)
            self.select(manager, lambda data: data["kind"] == "Highlight")
            with patch("pdfeditor.annots.QMessageBox.question", return_value=QMessageBox.Yes):
                manager.delete_selected()
            self.settle(manager)
            self.assertEqual(len(tab.doc.annots(0)), 1)
            manager.undo_button.click()
            self.settle(manager)
            self.assertEqual(len(tab.doc.annots(0)), 2)
            self.assertEqual(tab.doc.annots(0)[1]["text"], "Check this result")
            manager.redo_button.click()
            self.settle(manager)
            self.assertEqual(len(tab.doc.annots(0)), 1)
            manager.undo_button.click()
            self.settle(manager)
            manager.save_button.click()
            self.assertFalse(tab._dirty)
            with fitz.open(source) as pdf:
                page = pdf[0]
                annotations = list(page.annots())
                self.assertEqual(annotations[1].info["content"], "Check this result")
                self.assertEqual(annotations[1].type[1], "Highlight")

    def test_manager_navigation_and_mutations_stay_with_original_document(self):
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            tab.doc.add_note(1, 80, 100, "Original tab only")
            tab._annotation_changed()
            self.settle(manager)
            self.select(manager, lambda data: data["page"] == 1)
            other_source = source.with_name("other.pdf")
            other_source.write_bytes(source.read_bytes())
            other = window.open_in_tab(str(other_source))
            for _ in range(4):
                self.app.processEvents()
            with patch.object(tab.view, "ensure_rect_visible") as ensure:
                manager.go_to_selected()
                ensure.assert_called_once()
            self.assertIs(window._tabs.currentWidget(), tab)
            self.assertEqual(tab.page_index, 1)
            self.assertEqual(other.page_index, 0)
            self.assertEqual(other.doc.annots(1), [])

    def test_view_only_manager_cannot_edit_delete_or_save(self):
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, read_only=True, annotations_enabled=False)
            self.select(manager, lambda _data: True)
            self.assertTrue(manager.go_button.isEnabled())
            for button in (manager.edit_button, manager.delete_button, manager.save_button):
                self.assertFalse(button.isEnabled())
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText") as edit:
                manager.edit_selected()
                manager.delete_selected()
                edit.assert_not_called()
            self.assertFalse(tab._dirty)

    def test_editor_manager_uses_document_history_and_returns_from_artboards(self):
        from PyQt5.QtWidgets import QMessageBox
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, workspace_mode="editor")
            self.select(manager, lambda _data: True)
            manager.go_to_selected()
            self.assertFalse(tab.is_editor_overview())
            with patch("pdfeditor.annots.QInputDialog.getMultiLineText", return_value=("Editor revision", True)):
                manager.edit_selected()
            self.settle(manager)
            self.assertEqual(tab.doc.annots(0)[0]["text"], "Editor revision")
            manager.undo_button.click()
            self.settle(manager)
            self.assertEqual(tab.doc.annots(0)[0]["text"], "Existing note")
            self.select(manager, lambda _data: True)
            with patch("pdfeditor.annots.QMessageBox.question", return_value=QMessageBox.No):
                manager.delete_selected()
            self.assertEqual(len(tab.doc.annots(0)), 1)

    def test_sidebar_close_hides_whole_panel_and_can_reopen_bookmarks(self):
        from pdfeditor import settings
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            for mode in ("thumbnails", "bookmarks"):
                tab.set_sidebar_mode(mode)
                self.assertFalse(tab._sidebar_container.isHidden())
                tab._sidebar_close_button.click()
                self.assertEqual(tab._sidebar_mode, "none")
                self.assertTrue(tab._sidebar_container.isHidden())
                self.assertTrue(tab._sidebar_stack.isHidden())
                self.assertTrue(tab._sidebar_actions["none"].isChecked())
                self.assertEqual(settings.sidebar_mode(), "none")
            tab.set_sidebar_mode("bookmarks")
            self.assertFalse(tab._sidebar_container.isHidden())
            self.assertIs(tab._sidebar_stack.currentWidget(), tab.bookmarks)
            from pdfeditor.i18n import translate_tree
            translate_tree(tab._sidebar_container)
            self.assertEqual(tab._sidebar_title.text(), "Bookmarks")

    def test_author_search_and_numeric_page_sort(self):
        import fitz
        from PyQt5.QtCore import Qt
        with self.windows() as (module, source):
            with fitz.open(source) as pdf:
                while len(pdf) < 11:
                    pdf.new_page()
                for page_index in (2, 10):
                    page = pdf[page_index]
                    note = page.add_text_annot((90, 90), "Review this page")
                    note.set_info(title="Reviewer B" if page_index == 10 else "Reviewer A")
                    note.update()
                pdf.saveIncr()
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            self.assertEqual([manager.table.topLevelItem(i).data(0, Qt.UserRole)["page"]
                              for i in range(3)], [0, 2, 10])
            manager.search.setText("reviewer b")
            self.assertEqual(self.visible_count(manager), 1)
            self.select(manager, lambda data: data["page"] == 10)
            self.assertEqual(manager.selected()["author"], "Reviewer B")

    def test_closed_document_stops_indexing_and_disables_stale_actions(self):
        with self.windows() as (module, source):
            window, tab, manager = self.open_manager(module, source, workspace_mode="reader")
            self.select(manager, lambda _data: True)
            tab.close_doc()
            self.assertFalse(manager.isVisible())
            self.assertFalse(manager._timer.isActive())
            self.assertIsNone(manager.document)
            self.assertFalse(manager.edit_button.isEnabled())
            manager.go_to_selected()
            manager.edit_selected()


if __name__ == "__main__":
    unittest.main()
