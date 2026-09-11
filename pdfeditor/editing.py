"""EditMixin — 텍스트 편집(설계 §3.4) + 스냅샷 기반 undo/redo.

편집 모델: 편집 모드에서 span(같은 글꼴로 이어진 글자 토막)을 클릭 →
현재 글자를 지우고 같은 자리에 새 글자를 쓴다. PDF는 문단/리플로우가
없으므로 그 줄 안에서만 교체된다.

undo/redo: PyMuPDF 저널링이 텍스트 삽입과 함께 쓰면 깨져서(연산 중 폰트
등록 불가) 문서 스냅샷(bytes) 스택으로 구현한다. 편집 전에 현재 상태를
한 장 찍어두고, 되돌리기는 그 스냅샷으로 복원한다.
"""

from PyQt5.QtCore import QRectF
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
        self._edit_mode = on
        self._edit_act.setChecked(on)
        if on:
            self.cancel_note_mode()
            # 손 도구에서는 클릭을 이동으로 소비하므로 편집 지점을 찍을 수 없다.
            self.set_interaction_mode("select", announce=False)
            self._show_edit_boxes()
        else:
            self.view.canvas.set_edit_boxes([])
            self.statusBar().clearMessage()

    def _show_edit_boxes(self):
        """현재 페이지의 편집 가능한 span 위치를 옅은 테두리로 표시."""
        if self.doc is None:
            return
        self._page_spans = self.doc.spans(self.page_index)
        self.view.canvas.set_edit_boxes(
            [QRectF(s["bbox"][0], s["bbox"][1],
                    s["bbox"][2] - s["bbox"][0], s["bbox"][3] - s["bbox"][1])
             for s in self._page_spans])

    # --- 클릭 → 편집 ---------------------------------------------------

    @editing_command
    def edit_span_at(self, pt):
        """편집 모드에서 canvas 클릭 시 호출(app.py 디스패처가 라우팅).

        빈 곳을 클릭하면 새 텍스트 박스를 얹는다(스캔본 자유 편집).
        """
        if self.doc is None:
            return
        span = self._span_at(pt)
        if span is None:
            self._add_text_box_at(pt)
            return
        scanned = self.doc.is_scanned_area(self.page_index, span["bbox"])
        color = (self.doc.sample_bg_fg(self.page_index, span["bbox"])[1]
                 if scanned else span["rgb"])
        dialog = TextEditDialog(self, text=span["text"], size=span["size"],
                                color=color, replacing=True)
        if dialog.exec_() != QDialog.Accepted:
            return
        new_text, size, rgb = dialog.values()
        if (new_text == span["text"] and abs(size - span["size"]) < 0.05
                and all(abs(a - b) < 1 / 255 for a, b in zip(rgb, color))):
            return
        if scanned:
            operation = lambda: self.doc.replace_scanned_text(
                self.page_index, span["bbox"], span["origin"],
                new_text, size, fg=rgb)
        else:
            operation = lambda: self.doc.replace_span(
                self.page_index, span["bbox"], span["origin"], new_text, size, rgb)
        self._perform_text_edit(operation)

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
        dialog = TextEditDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        text, size, color = dialog.values()
        if not text.strip():
            return
        point = (pt.x(), pt.y())
        bg = None
        if self.doc.is_scanned_area(self.page_index, (pt.x(), pt.y() - 10,
                                                      pt.x() + 60, pt.y() + 4)):
            bg, _fg = self.doc.sample_bg_fg(
                self.page_index, (pt.x(), pt.y() - 10, pt.x() + 60, pt.y() + 4))
        self._perform_text_edit(lambda: self.doc.add_text_box(
            self.page_index, point, text, size=size, bg=bg, fg=color))

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
