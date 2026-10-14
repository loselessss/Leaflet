"""Annotation-only UI persistence; never autosaves into the original PDF."""

import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from .access import command_allowed
from .i18n import localize, tr


class AnnotationPersistenceMixin:
    @property
    def annotations_enabled(self):
        if self.doc is not None:
            return self.doc.annotations_enabled
        return self._shell.annotations_enabled

    def _init_annotation_persistence(self):
        self._annotation_timer = QTimer(self)
        self._annotation_timer.setSingleShot(True)
        self._annotation_timer.setInterval(800)
        self._annotation_timer.timeout.connect(self._autosave_annotations)

    def _annotation_changed(self):
        self.mark_dirty()
        self._notes_changed()
        self._update_edit_actions()
        if (self.doc.annotation_mode and not self.doc.annotations_in_pdf
                and self._shell.autosave_annotations):
            self._annotation_timer.start()

    def _autosave_annotations(self):
        if (self.doc is not None and self.doc.annotation_mode
                and not self.doc.annotations_in_pdf and self.doc.annotations_dirty):
            self._save_annotations(show_error=False)

    def _save_annotations(self, show_error=True):
        self._annotation_timer.stop()
        try:
            self.doc.save_annotations()
        except Exception as error:
            message = localize(
                "Annotations could not be saved. Your changes are still open. "
                "Retry saving or export an annotated PDF.\n\n",
                "주석을 저장하지 못했습니다. 변경 내용은 현재 창에 남아 있습니다. "
                "저장을 다시 시도하거나 주석 포함 PDF로 내보내세요.\n\n") + str(error)
            self.statusBar().showMessage(message)
            if show_error:
                QMessageBox.warning(self, tr("저장 실패"), message)
            return False
        self._dirty = False
        self._update_title()
        self.statusBar().showMessage(localize(
            "Annotations saved separately. The original PDF is unchanged.",
            "주석을 별도로 저장했습니다. 원본 PDF는 변경하지 않았습니다."), 4000)
        return True

    def _export_annotations_dialog(self):
        stem = os.path.splitext(self.doc.path)[0]
        path, _ = QFileDialog.getSaveFileName(
            self, localize("Save PDF with annotations", "주석 포함 PDF 저장"),
            stem + ".annotated.pdf", "PDF (*.pdf)")
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        from .save_options import choose_save_options
        from .save_options_core import has_illustrator_editing_data
        options = {}
        if has_illustrator_editing_data(self.doc._doc):
            choice = choose_save_options(self, compatibility_only=True)
            if choice is None:
                return False
            options["illustrator_compatible"] = choice[2]
        try:
            self.doc.export_annotated_pdf(path, **options)
        except Exception as error:
            QMessageBox.warning(self, tr("저장 실패"), str(error))
            return False
        self.statusBar().showMessage(localize(
            "Annotated PDF exported: ", "주석 포함 PDF 저장됨: ") + path, 4000)
        return True

    def _sync_annotation_access(self):
        from PyQt5.QtWidgets import QAction
        for action in self.findChildren(QAction):
            kind = action.property("spdfAccessKind")
            if kind in ("annotation", "save", "history"):
                allowed = command_allowed(self, kind)
                action.setVisible(allowed)
                action.setEnabled(allowed)
        self._update_edit_actions()
        if self.doc.annotation_error:
            QMessageBox.warning(self, localize("Annotations unavailable", "주석 사용 불가"),
                                localize("The PDF is open for viewing only.\n\n",
                                         "PDF 보기만 가능합니다.\n\n") + self.doc.annotation_error)

    def _step_annotation_history(self, forward=False):
        try:
            if not self.doc.step_annotation_history(forward):
                return
        except Exception as error:
            QMessageBox.warning(self, tr("실행 취소"), str(error))
            return
        self._after_page_content_changed()
        self._annotation_changed()
