"""Undoable bookmark editing and page crop commands."""

from PyQt5.QtWidgets import QDialog, QInputDialog, QMessageBox

from .i18n import localize, tr
from .access import editing_command


class DocumentToolsMixin:
    @editing_command
    def add_binding_guides(self):
        if self.doc is None or not self._commit_inline_text():
            return
        from .binding_guide_dialog import BindingGuideDialog
        from .binding_guides import add_guides
        dialog = BindingGuideDialog(self.doc, self.page_index, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        if self.apply_document_change(lambda: add_guides(
                self.doc, dialog.pages, **dialog.values()), structural=False):
            if dialog.save_copy.isChecked():
                self.save_as_dialog()

    @editing_command
    def apply_document_change(self, operation, structural=True):
        if self.doc is None:
            return False
        if not self._commit_inline_text():
            return False
        stacks = [list(getattr(self, name)) for name in
                  ("_undo_stack", "_redo_stack", "_undo_structural",
                   "_redo_structural")]
        snapshot = None
        try:
            self.doc.ensure_editable()
            self._push_undo(structural=structural)
            snapshot = self._undo_stack[-1]
            operation()
        except Exception as error:
            if snapshot is not None:
                self.doc.restore(snapshot)
            (self._undo_stack, self._redo_stack, self._undo_structural,
             self._redo_structural) = stacks
            self._update_edit_actions()
            self.bookmarks.set_bookmarks(self.doc.bookmarks())
            QMessageBox.warning(self, tr("문서 변경 실패"), str(error))
            return False
        if structural:
            self._after_structure_changed(keep_page=self.page_index)
        else:
            self._after_page_content_changed()
        self.mark_dirty()
        return True

    @editing_command
    def add_current_bookmark(self):
        if self.doc is None:
            return
        title, accepted = QInputDialog.getText(
            self, tr("현재 페이지 책갈피 추가"), tr("제목:"),
            text=tr("%d쪽" % (self.page_index + 1)))
        if accepted and title.strip():
            if self.apply_document_change(
                    lambda: self.doc.add_bookmark(title, self.page_index)):
                self.set_sidebar_mode("bookmarks")

    @editing_command
    def rename_bookmark(self, index, title):
        if self.doc is not None:
            self.apply_document_change(
                lambda: self.doc.rename_bookmark(index, title))

    @editing_command
    def delete_bookmark(self, index):
        if self.doc is None:
            return
        if QMessageBox.question(self, tr("책갈피 삭제"), localize(
                "Delete this bookmark and its child bookmarks?",
                "이 책갈피와 하위 책갈피를 삭제할까요?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                ) == QMessageBox.Yes:
            self.apply_document_change(lambda: self.doc.delete_bookmark(index))

    @editing_command
    def reorder_bookmarks(self, order):
        if self.doc is not None:
            self.apply_document_change(lambda: self.doc.reorder_bookmarks(order))

    @editing_command
    def crop_page_margins(self):
        if self.doc is None:
            return
        from .crop_dialog import CropDialog
        dialog = CropDialog(self.doc, self.page_index, self)
        if dialog.exec_() == QDialog.Accepted:
            fractions = dialog.preview.fractions()
            if all(abs(actual - expected) < 1e-6 for actual, expected in zip(
                    fractions, (0.0, 0.0, 1.0, 1.0))):
                return
            self.apply_document_change(lambda: self.doc.crop_pages(
                dialog.pages, fractions))

    @editing_command
    def edit_canvas_size(self):
        if self.doc is None:
            return
        from .page_setup_dialog import CanvasSizeDialog
        width, height = self.doc.page_size(self.page_index)
        dialog = CanvasSizeDialog(self, width_pt=width, height_pt=height)
        if dialog.exec_() == QDialog.Accepted:
            width, height = dialog.values()
            self.apply_document_change(
                lambda: self.doc.set_page_canvas_size(
                    self.page_index, width, height))

    @editing_command
    def edit_page_bleed(self):
        if self.doc is None:
            return
        from .page_setup_dialog import BleedDialog
        dialog = BleedDialog(
            self, margins_pt=self.doc.page_bleed_margins(self.page_index))
        if dialog.exec_() == QDialog.Accepted:
            margins = dialog.values()
            self.apply_document_change(
                lambda: self.doc.set_page_bleed(self.page_index, *margins))
