"""EditMixin — 텍스트 편집(설계 §3.4) + 스냅샷 기반 undo/redo.

편집 모델: 편집 모드에서 span(같은 글꼴로 이어진 글자 토막)을 클릭 →
현재 글자를 지우고 같은 자리에 새 글자를 쓴다. 가까운 조각은 한 줄로
묶고, 드래그한 여러 줄은 선택한 상자 안에서만 줄을 바꾸어 교체한다.

undo/redo: PyMuPDF 저널링이 텍스트 삽입과 함께 쓰면 깨져서(연산 중 폰트
등록 불가) 문서 스냅샷(bytes) 스택으로 구현한다. 편집 전에 현재 상태를
한 장 찍어두고, 되돌리기는 그 스냅샷으로 복원한다.
"""

import fitz
from PyQt5.QtCore import QRectF, QPointF
from PyQt5.QtWidgets import QDialog, QInputDialog, QMessageBox
from .access import editing_command, history_command
from .i18n import localize

def TextEditDialog(*args, **kwargs):
    from .text_edit_dialog import TextEditDialog as Dialog
    return Dialog(*args, **kwargs)

# 스냅샷 스택 상한 — 무한히 쌓으면 큰 문서에서 메모리를 먹으므로 제한한다.
UNDO_LIMIT = 30


class EditMixin:
    def _init_edit_state(self):
        self._edit_mode = False
        self._undo_stack = []  # 편집 전 스냅샷(bytes)들
        self._redo_stack = []
        self._undo_structural = []  # 페이지 수/순서 변경 여부
        self._redo_structural = []

    def _reset_edit(self):
        self._cancel_inline_text()
        self._edit_mode = False
        self._undo_stack = []
        self._redo_stack = []
        self._undo_structural = []
        self._redo_structural = []
        self.view.canvas.set_edit_boxes([])
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.selected = None
            controller.deactivate()
            controller.refresh()

    # --- 페이지 전환 훅 -----------------------------------------------

    def show_page(self, index):
        # EditMixin이 MRO 맨 앞이므로 이 show_page가 먼저 불린다. 실제
        # 표시는 super() 체인(TextSelect→Viewer)에 맡기고, 편집 모드면 새
        # 페이지의 span 테두리를 다시 그린다.
        if not self._commit_inline_text():
            return
        super().show_page(index)
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.refresh()
        if self._edit_mode:
            self._show_edit_boxes()

    # --- 편집 모드 ----------------------------------------------------

    @editing_command
    def toggle_edit_mode(self):
        if self.doc is None:
            return
        self.set_edit_mode(not self._edit_mode)

    def set_edit_mode(self, on):
        if on and getattr(self, "read_only", False):
            return
        if on and self.is_editor_overview():
            self.open_page_editor()
            return
        if not on and not self._commit_inline_text():
            return
        self._edit_mode = on
        self._edit_act.setChecked(on)
        if on:
            self.cancel_note_mode()
            # 손 도구에서는 클릭을 이동으로 소비하므로 편집 지점을 찍을 수 없다.
            self.set_interaction_mode("select", announce=False)
            self._show_edit_boxes()
        else:
            self.view.canvas.set_edit_boxes([])
            self.view.viewport().setToolTip('')
            self.statusBar().clearMessage()

    def _show_edit_boxes(self):
        """현재 페이지의 편집 가능한 span 위치를 옅은 테두리로 표시."""
        if self.doc is None:
            return
        self._page_spans = self.doc.spans(self.page_index)
        from .text_regions import text_lines
        self._text_lines = text_lines(self._page_spans)
        matrix = self.doc._doc[self.page_index].rotation_matrix
        self.view.canvas.set_edit_boxes(
            [QRectF(r.x0, r.y0, r.width, r.height)
             for s in self._text_lines for r in [fitz.Rect(s['bbox']) * matrix]])
        self.view.viewport().setToolTip(localize(
            'Click to edit a line; drag a box around several lines to edit a paragraph.',
            '클릭: 한 줄 편집 · 여러 줄을 상자로 드래그: 문단 편집'))

    def _text_point(self, pt):
        point = fitz.Point(pt.x(), pt.y()) * self.doc._doc[self.page_index].derotation_matrix
        return QPointF(point.x, point.y)

    def _drag_text_region(self, start, end):
        from .text_regions import selected_region
        start, end = self._text_point(start), self._text_point(end)
        rect = QRectF(start, end).normalized()
        return selected_region(getattr(self, '_text_lines', []),
                               (rect.left(), rect.top(), rect.right(), rect.bottom()))

    def on_drag_selected(self, start, end):
        if not self._edit_mode:
            return super().on_drag_selected(start, end)
        if self.doc is None or getattr(self, '_inline_text', None) is not None:
            return
        region = self._drag_text_region(start, end)
        matrix = self.doc._doc[self.page_index].rotation_matrix
        self.view.canvas.set_selection([
            QRectF(r.x0, r.y0, r.width, r.height)
            for span in (region['sources'] if region else [])
            for r in [fitz.Rect(span['bbox']) * matrix]])

    @editing_command
    def edit_text_selection(self, start, end):
        if not self._edit_mode or self.doc is None:
            return
        if not self._commit_inline_text():
            return
        region = self._drag_text_region(start, end)
        if region:
            from .paragraph_text import ParagraphTextSession
            self._inline_text = ParagraphTextSession(self, self._text_point(start), region)

    # --- 클릭 → 편집 ---------------------------------------------------

    @editing_command
    def edit_span_at(self, pt):
        """편집 모드에서 canvas 클릭 시 호출(app.py 디스패처가 라우팅).

        빈 곳을 클릭하면 새 텍스트 박스를 얹는다(스캔본 자유 편집).
        """
        if self.doc is None:
            return
        if not self._commit_inline_text():
            return
        pt = self._text_point(pt)
        region = next((line for line in getattr(self, '_text_lines', [])
                       if fitz.Rect(line['bbox']).contains((pt.x(), pt.y()))), None)
        if region and len(region['sources']) > 1:
            from .paragraph_text import ParagraphTextSession
            self._inline_text = ParagraphTextSession(self, pt, region)
            return
        span = self._span_at(pt)
        if span is None:
            self._add_text_box_at(pt)
            return
        self._start_inline_text(pt, span)

    def _start_inline_text(self, pt, span=None):
        if not self._commit_inline_text():
            return
        from .inline_text import InlineTextSession
        self._inline_text = InlineTextSession(self, pt, span)

    def _commit_inline_text(self):
        session = getattr(self, "_inline_text", None)
        return session.commit() if session is not None else True

    def _cancel_inline_text(self):
        session = getattr(self, "_inline_text", None)
        if session is not None:
            session.cancel()

    @editing_command
    def resize_span_at(self, pt, factor=None):
        if self.doc is None:
            return
        span = self._span_at(pt)
        if span is None:
            return
        if factor is None:
            size, accepted = QInputDialog.getDouble(
                self, localize("Element size", "요소 크기"),
                localize("Font size:", "글자 크기:"),
                span["size"], 1.0, 1000.0, 1)
            if not accepted:
                return
        else:
            size = max(1.0, min(1000.0, span["size"] * float(factor)))
        if abs(size - span["size"]) < 0.05:
            return
        scanned = self.doc.is_scanned_area(self.page_index, span["bbox"])
        if scanned:
            color = self.doc.sample_bg_fg(self.page_index, span["bbox"])[1]
            operation = lambda: self.doc.replace_scanned_text(
                self.page_index, span["bbox"], span["origin"],
                span["text"], size, fg=color)
        else:
            operation = lambda: self.doc.replace_span(
                self.page_index, span["bbox"], span["origin"],
                span["text"], size, span["rgb"], fit=False)
        self._perform_text_edit(operation)

    @editing_command
    def _add_text_box_at(self, pt):
        """빈 자리 클릭 — 새 글자를 얹는다. 스캔본이면 배경도 함께 깔아
        아래 내용을 가린다(OCR 없이도 쓸 수 있는 자유 편집)."""
        self._start_inline_text(pt)

    def _perform_text_edit(self, operation):
        before = None
        try:
            self.doc.ensure_editable()
            before = self.doc.snapshot()
            operation()
        except Exception as error:
            if before is not None:
                self.doc.restore(before)
                self._after_page_content_changed()
            QMessageBox.warning(self, localize("Edit failed", "편집 실패"), str(error))
            return False
        self._push_undo(snapshot=before)
        self._after_page_content_changed()
        self.mark_dirty()
        return True

    def _span_at(self, pt):
        for s in getattr(self, "_page_spans", []):
            x0, y0, x1, y1 = s["bbox"]
            if x0 <= pt.x() <= x1 and y0 <= pt.y() <= y1:
                return s
        return None

    # --- undo / redo --------------------------------------------------

    def _push_undo(self, structural=False, snapshot=None):
        self._undo_stack.append(self.doc.snapshot() if snapshot is None else snapshot)
        self._undo_structural.append(structural)
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
            self._undo_structural.pop(0)
        self._redo_stack.clear()
        self._redo_structural.clear()
        self._update_edit_actions()

    @history_command
    def undo(self):
        if getattr(self, "_inline_text", None) is not None:
            self._cancel_inline_text()
            return
        if self.doc is not None and self.doc.annotation_mode:
            return self._step_annotation_history()
        if not self._undo_stack:
            return
        self._redo_stack.append(self.doc.snapshot())
        structural = self._undo_structural.pop()
        self._redo_structural.append(structural)
        self.doc.restore(self._undo_stack.pop())
        if structural:
            self._after_structure_changed(keep_page=self.page_index)
        else:
            self._after_page_content_changed()
        self.mark_dirty()
        self._update_edit_actions()

    @history_command
    def redo(self):
        self._cancel_inline_text()
        if self.doc is not None and self.doc.annotation_mode:
            return self._step_annotation_history(forward=True)
        if not self._redo_stack:
            return
        self._undo_stack.append(self.doc.snapshot())
        structural = self._redo_structural.pop()
        self._undo_structural.append(structural)
        self.doc.restore(self._redo_stack.pop())
        if structural:
            self._after_structure_changed(keep_page=self.page_index)
        else:
            self._after_page_content_changed()
        self.mark_dirty()
        self._update_edit_actions()

    def _update_edit_actions(self):
        if self.doc is not None and self.doc.annotation_mode:
            self._undo_act.setEnabled(self.doc.can_undo_annotation)
            self._redo_act.setEnabled(self.doc.can_redo_annotation)
            return
        editable = not getattr(self, "read_only", False)
        self._undo_act.setEnabled(editable and bool(self._undo_stack))
        self._redo_act.setEnabled(editable and bool(self._redo_stack))

    # --- 편집 후 갱신 --------------------------------------------------

    def _after_page_content_changed(self):
        """문서 내용이 바뀐 뒤(편집/undo/redo) 캐시를 무효화하고 다시 그린다.

        스냅샷 복원은 문서 전체를 갈아치우므로 렌더/단어/주석 캐시가 전부
        낡는다 — 한 번에 정리한다.
        """
        self._cancel_inline_text()
        self.doc.invalidate_render()
        self._cache.clear()
        self._words_cache.clear()
        if hasattr(self, "_annot_cache"):
            self._annot_cache.clear()
        self.refresh_editor_overview(reset=True)
        self._render_current()
        self.thumbs.invalidate(self.page_index)
        self._schedule_thumbs()
        if self._edit_mode:
            self._show_edit_boxes()
        if hasattr(self, "_notes_dock") and self._notes_dock.isVisible():
            self._rebuild_notes_list()
