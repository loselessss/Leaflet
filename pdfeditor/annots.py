"""Annotation commands, document-bound management and save/undo integration."""

import os

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtWidgets import (
    QFileDialog, QInputDialog, QMenu, QMessageBox, QToolTip,
)

from .i18n import localize, tr
from .access import annotation_command, saving_command

from .filetypes import is_illustrator_document, is_eps_document, suggested_pdf_path

from .icons import fluent_icon
from .save_options import choose_save_options


def _set_unsaved_button_texts(dialog):
    """Qt/Windows 언어와 무관하게 sPDF UI 언어로 버튼을 표시한다."""
    dialog.button(QMessageBox.Save).setText(tr("저장"))
    dialog.button(QMessageBox.Discard).setText(tr("저장 안 함"))
    dialog.button(QMessageBox.Cancel).setText(tr("취소"))


class AnnotMixin:
    def _init_annot_state(self):
        self._dirty = False
        self._note_mode = False   # True면 다음 클릭이 메모 배치
        # 페이지별 주석 목록 캐시 — 마우스 호버마다 PyMuPDF에 물어보면
        # 매 이동 이벤트에 객체를 새로 만들게 되므로 여기서 재사용한다.
        self._annot_cache = {}
        self._annotation_manager = None

    def _reset_annots(self):
        self._dirty = False
        self._note_mode = False
        self._annot_cache.clear()
        if self._annotation_manager is not None:
            self._annotation_manager.reset()

    def _annots_cached(self, page):
        a = self._annot_cache.get(page)
        if a is None:
            a = self.doc.annots(page) if self.doc else []
            self._annot_cache[page] = a
        return a

    def _notes_changed(self):
        """주석이 바뀌었을 때 캐시를 비우고 열린 관리 창을 갱신한다."""
        self._annot_cache.clear()
        if self._annotation_manager is not None and self._annotation_manager.isVisible():
            self._annotation_manager.refresh()

    # --- 변경 추적 -----------------------------------------------------

    def mark_dirty(self):
        self._dirty = True
        self._update_title()
        recovery = getattr(self, "_recovery", None)
        if recovery is not None:
            recovery.changed()

    def maybe_save(self):
        """Ask about unsaved changes, including an active inline edit."""
        if not self._commit_inline_text():
            return False
        if not self._dirty or self.doc is None:
            return True
        annotation_mode = self.doc.annotation_mode and not self.doc.annotations_in_pdf
        if annotation_mode:
            self._annotation_timer.stop()
            if self._shell.autosave_annotations and self._save_annotations(show_error=False):
                return True
        dialog = QMessageBox(
            QMessageBox.Question,
            tr("저장되지 않은 변경"),
            tr("저장하지 않은 주석이 있습니다. 저장할까요?"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            self,
        )
        dialog.setDefaultButton(QMessageBox.Save)
        _set_unsaved_button_texts(dialog)
        if annotation_mode:
            dialog.setText(localize(
                "Annotations have not been saved separately. Save them before closing?",
                "아직 별도로 저장하지 못한 주석이 있습니다. 닫기 전에 저장할까요?"))
            dialog.button(QMessageBox.Save).setText(localize("Save annotations", "주석 저장"))
        ret = dialog.exec_()
        if ret == QMessageBox.Save:
            return self.save()
        return ret == QMessageBox.Discard

    # --- 저장 -----------------------------------------------------------

    @saving_command
    def save(self):
        if not self._commit_inline_text():
            return False
        if self.doc is None:
            return False
        if self.doc.annotation_mode and not self.doc.annotations_in_pdf:
            return self._save_annotations()
        if (is_illustrator_document(self.doc.path) or is_eps_document(self.doc.path) or
                getattr(self, "_recovered_unsaved", False)):
            return self.save_as_dialog()
        from .save_options_core import has_illustrator_editing_data
        compatibility = None
        if has_illustrator_editing_data(self.doc._doc):
            options = choose_save_options(self, compatibility_only=True)
            if options is None:
                return False
            compatibility = options[2]
        try:
            if compatibility is None:
                self._save_document_file(self.doc.path)
            else:
                self._save_document_file(self.doc.path, illustrator_compatible=compatibility)
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", "저장할 수 없습니다.\n\n%s" % e)
            return False
        self._dirty = False
        self._recovery.clear()
        self._update_title()
        self.statusBar().showMessage("저장됨: %s" % self.doc.path, 3000)
        return True

    @saving_command
    def save_as_dialog(self):
        if not self._commit_inline_text():
            return False
        if self.doc is None:
            return False
        if self.doc.annotation_mode and not self.doc.annotations_in_pdf:
            return self._export_annotations_dialog()
        path, _ = QFileDialog.getSaveFileName(
            self, "다른 이름으로 저장", suggested_pdf_path(self.doc.path),
            "PDF 파일 (*.pdf)")
        if not path:
            return False
        path = suggested_pdf_path(path)
        from .save_options_core import has_illustrator_editing_data
        if self.doc.annotations_in_pdf:
            options = (choose_save_options(self, compatibility_only=True)
                       if has_illustrator_editing_data(self.doc._doc) else (False, False, None))
        else:
            options = choose_save_options(self)
        if options is None:
            return False
        try:
            self._save_document_file(path, remove_metadata=options[0],
                                     remove_editing_data=options[1],
                                     illustrator_compatible=options[2] if len(options) > 2 else None)
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", "저장할 수 없습니다.\n\n%s" % e)
            return False
        # 이후 Ctrl+S는 새 경로에 저장되도록 현재 문서를 갈아탄다.
        self.doc.path = path
        self._dirty = False
        self._recovered_unsaved = False
        self._recovery.clear()
        self._sync_favorite_action()
        self._update_title()
        self.statusBar().showMessage("저장됨: %s" % path, 3000)
        return True

    def _save_document_file(self, path, *, remove_metadata=False, remove_editing_data=False,
                            illustrator_compatible=None):
        options = {} if illustrator_compatible is None else {"illustrator_compatible": illustrator_compatible}
        if self.doc.annotations_in_pdf:
            revision = self.doc.save_reader_pdf(path, **options)
        else:
            revision = self.doc.save_as(path, remove_metadata=remove_metadata,
                                        remove_editing_data=remove_editing_data, **options)
        if remove_editing_data:
            self.refresh_editor_overview()
        if self._shell.workspace_mode in ("reader", "editor"):
            from .document_snapshot import file_revision
            from .process_workspace import application_bridge
            try:
                application_bridge().saved(path, revision or file_revision(path))
            except OSError as error:
                self.statusBar().showMessage(str(error), 8000)

    # --- 형광펜 ----------------------------------------------------------

    @annotation_command
    def highlight_selection(self):
        """선택된 단어들에 형광펜 — 줄 단위로 합쳐서 띄엄띄엄해 보이지 않게."""
        if self.doc is None:
            return
        if not self._selected:
            self.statusBar().showMessage("먼저 텍스트를 드래그로 선택하세요", 3000)
            return
        lines = {}
        for w in self._selected:
            key = (w[5], w[6])
            r = lines.get(key)
            if r is None:
                lines[key] = [w[0], w[1], w[2], w[3]]
            else:
                r[0] = min(r[0], w[0]); r[1] = min(r[1], w[1])
                r[2] = max(r[2], w[2]); r[3] = max(r[3], w[3])
        if not self.doc.annotation_mode:
            self._push_undo()
        self.doc.add_highlight(self.page_index, [tuple(r) for r in lines.values()])
        self._clear_selection()
        self.refresh_page(self.page_index)
        self._annotation_changed()

    # --- 메모 ------------------------------------------------------------

    @annotation_command
    def start_note_mode(self):
        if self.doc is None:
            return
        if self.is_editor_overview():
            self.open_page_editor(edit_text=False)
        # 메모 위치 클릭이 손 도구의 이동으로 소비되지 않게 선택 도구로 전환.
        self.set_interaction_mode("select", announce=False)
        self._note_mode = True
        self.statusBar().showMessage("메모를 붙일 위치를 클릭하세요 (Esc 취소)")

    def cancel_note_mode(self):
        self._note_mode = False
        self.statusBar().clearMessage()

    def on_canvas_clicked(self, pt):
        if self._note_mode:
            self._note_mode = False
            self.statusBar().clearMessage()
            self._add_note_at(pt)
            return
        # 메모 아이콘 클릭 → 바로 열어서 보기/편집
        if self.doc is not None:
            a = self._annot_at(pt)
            if a is not None and a["kind"] == "Text":
                self.edit_annot(a)

    def on_canvas_hover(self, pt, global_pos):
        """메모 아이콘 위에 마우스를 올리면 내용 툴팁."""
        if self.doc is None:
            return
        if self.view.canvas.interaction_mode == "hand":
            QToolTip.hideText()
            self.view.canvas.refresh_cursor()
            return
        a = self._annot_at(pt)
        if a is not None and a["kind"] == "Text" and a["text"]:
            QToolTip.showText(global_pos, a["text"], self.view.canvas)
            self.view.canvas.setCursor(Qt.PointingHandCursor)
        else:
            QToolTip.hideText()
            self.view.canvas.refresh_cursor()

    @annotation_command
    def _add_note_at(self, pt):
        text, ok = QInputDialog.getMultiLineText(self, "메모 추가", "내용:")
        if not ok or not text.strip():
            return
        if not self.doc.annotation_mode:
            self._push_undo()
        self.doc.add_note(self.page_index, pt.x(), pt.y(), text)
        self.refresh_page(self.page_index)
        self._annotation_changed()

    def _annot_at(self, pt):
        """지점 위 주석 — 메모 아이콘이 작으므로 히트 판정을 약간 넉넉하게."""
        PAD = 3
        for a in self._annots_cached(self.page_index):
            x0, y0, x1, y1 = a["rect"]
            if x0 - PAD <= pt.x() <= x1 + PAD and y0 - PAD <= pt.y() <= y1 + PAD:
                return a
        return None

    def edit_annot(self, a):
        if a["kind"] == "Text":
            if not self.annotations_enabled:
                dialog = QMessageBox(self)
                dialog.setWindowTitle(tr("메모 모아보기"))
                dialog.setTextFormat(Qt.PlainText)
                dialog.setText(a["text"])
                dialog.setTextInteractionFlags(Qt.TextSelectableByMouse)
                dialog.exec_()
                return
            text, ok = QInputDialog.getMultiLineText(
                self, "메모 편집", "내용:", a["text"])
            if ok:
                if not self.doc.annotation_mode:
                    self._push_undo()
                self.doc.set_note_text(self.page_index, a["xref"], text)
                self.refresh_page(self.page_index)
                self._annotation_changed()

    @annotation_command
    def delete_annot(self, a):
        if not self.doc.annotation_mode:
            self._push_undo()
        self.doc.delete_annot(self.page_index, a["xref"])
        self.refresh_page(self.page_index)
        self._annotation_changed()

    # --- 별도 주석 관리 창 --------------------------------------------------

    def toggle_notes_panel(self):
        if self.doc is None:
            return
        if self._annotation_manager is None:
            from .annotation_manager import AnnotationManager
            self._annotation_manager = AnnotationManager(self)
        self._annotation_manager.show()
        self._annotation_manager.raise_()
        self._annotation_manager.activateWindow()

    def _managed_annotation(self, page, xref):
        if self.doc is None or not 0 <= page < self.doc.page_count:
            return None
        return next((item for item in self.doc.annots(page) if item["xref"] == xref), None)

    def navigate_to_annotation(self, page, xref):
        annotation = self._managed_annotation(page, xref)
        if annotation is None:
            return False
        self._shell._tabs.setCurrentWidget(self)
        if self.is_editor_overview():
            self.open_page_editor(page, edit_text=False)
        else:
            self.show_page(page)
        if self.page_index != page:
            return False  # An inline edit may have prevented page navigation.
        rect = annotation["rect"]
        self.view.ensure_rect_visible(
            QRectF(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]))
        self._shell.raise_()
        return True

    @annotation_command
    def edit_managed_annotation(self, page, xref):
        from .annotation_manager import EDITABLE_COMMENT_KINDS
        annotation = self._managed_annotation(page, xref)
        if annotation is None or annotation["kind"] not in EDITABLE_COMMENT_KINDS:
            return
        document = self.doc
        text, ok = QInputDialog.getMultiLineText(
            self._annotation_manager or self, localize("Edit annotation comment", "주석 내용 편집"),
            localize("Content:", "내용:"), annotation["text"])
        if not ok or text == annotation["text"] or self.doc is not document:
            return
        current = self._managed_annotation(page, xref)
        if current is None or current.get("id") != annotation.get("id"):
            return
        try:
            if not document.annotation_mode:
                self._push_undo()
            document.set_note_text(page, xref, text)
        except Exception as error:
            QMessageBox.warning(self, localize("Annotation edit failed", "주석 편집 실패"), str(error))
            return
        self.refresh_page(page)
        self._annotation_changed()

    @annotation_command
    def delete_managed_annotation(self, page, xref):
        annotation = self._managed_annotation(page, xref)
        if annotation is None:
            return
        document = self.doc
        parent = self._annotation_manager or self
        answer = QMessageBox.question(parent, tr("주석 삭제"),
            localize("Delete the selected annotation on page %d?", "%d쪽의 선택한 주석을 삭제할까요?") % (page + 1),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes or self.doc is not document:
            return
        current = self._managed_annotation(page, xref)
        if current is None or current.get("id") != annotation.get("id"):
            return
        try:
            if not document.annotation_mode:
                self._push_undo()
            document.delete_annot(page, xref)
        except Exception as error:
            QMessageBox.warning(self, tr("주석 삭제"), str(error))
            return
        self.refresh_page(page)
        self._annotation_changed()

    # --- 우클릭 메뉴 -------------------------------------------------------

    def on_context_menu(self, pt, global_pos):
        if self.doc is None:
            return
        menu = QMenu(self)
        if getattr(self, "_edit_mode", False):
            span = self._span_at(pt)
            if span is not None:
                action = menu.addAction(
                    localize("Element size...", "요소 크기..."),
                    lambda _c=False, p=pt: self.resize_span_at(p))
                action.setIcon(fluent_icon("edit"))
                menu.addAction(
                    localize("Increase element 10%", "요소 10% 확대"),
                    lambda _c=False, p=pt: self.resize_span_at(p, 1.1))
                menu.addAction(
                    localize("Decrease element 10%", "요소 10% 축소"),
                    lambda _c=False, p=pt: self.resize_span_at(p, 0.9))
                menu.exec_(global_pos)
                return
        if not self.annotations_enabled:
            if self._selected:
                menu.addAction(tr("복사"), self.copy_selection)
            note = self._annot_at(pt)
            if note is not None and note["kind"] == "Text":
                menu.addAction(tr("메모 모아보기"),
                               lambda: self.edit_annot(note))
            if menu.actions():
                menu.exec_(global_pos)
            return
        if self._selected:
            action = menu.addAction(
                "선택 영역 형광펜",
                lambda _c=False: self.highlight_selection())
            action.setIcon(fluent_icon("highlight"))
        a = self._annot_at(pt)
        if a is not None:
            if a["kind"] == "Text":
                # 메모 내용 미리보기 한 줄 + 편집
                first = a["text"].splitlines()[0] if a["text"] else ""
                if len(first) > 30:
                    first = first[:30] + "…"
                action = menu.addAction(
                    "메모 편집: %s" % first,
                    lambda _c=False, a=a: self.edit_annot(a))
                action.setIcon(fluent_icon("edit"))
            action = menu.addAction(
                "주석 삭제", lambda _c=False, a=a: self.delete_annot(a))
            action.setIcon(fluent_icon("delete"))
        else:
            action = menu.addAction(
                "여기에 메모 추가",
                lambda _c=False, p=pt: self._add_note_at(p))
            action.setIcon(fluent_icon("note"))
        if menu.actions():
            menu.exec_(global_pos)
