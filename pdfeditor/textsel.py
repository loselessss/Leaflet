"""TextSelectMixin — 텍스트 선택/복사(§3.2) + 검색(Ctrl+F). v0.2.

단어 좌표는 페이지당 한 번만 뽑아 캐시한다 — 드래그 중 매 이벤트마다
get_text를 부르면 큰 페이지에서 버벅인다.
"""

from PyQt5.QtCore import QRectF, Qt

from .i18n import tr, localize
from PyQt5.QtWidgets import QApplication, QProgressDialog

from .selection import payload_from_words


def _ordered_words(words):
    return sorted(words, key=lambda word: (word[5], word[6], word[7]))


def _word_index_at(words, point, padding=3.0):
    """point가 닿은 단어 인덱스. 글자 가장자리에는 작은 여유를 둔다."""
    for index, word in enumerate(words):
        rect = QRectF(word[0], word[1], word[2] - word[0], word[3] - word[1])
        if rect.adjusted(-padding, -padding, padding, padding).contains(point):
            return index
    return None


def _nearest_word_index(words, point):
    """드래그 끝이 단어 사이 공백이어도 읽기 흐름의 가장 가까운 단어 선택."""
    best_index, best_distance = None, None
    for index, word in enumerate(words):
        x = min(max(point.x(), word[0]), word[2])
        y = min(max(point.y(), word[1]), word[3])
        distance = (point.x() - x) ** 2 + (point.y() - y) ** 2
        if best_distance is None or distance < best_distance:
            best_index, best_distance = index, distance
    return best_index


def words_in_text_flow(words, start, end):
    """시작 단어부터 끝 단어까지 읽기 순서로 연속 선택한다."""
    ordered = _ordered_words(words)
    start_index = _word_index_at(ordered, start)
    if start_index is None:
        return []
    end_index = _word_index_at(ordered, end)
    if end_index is None:
        end_index = _nearest_word_index(ordered, end)
    if end_index is None:
        return []
    lo, hi = sorted((start_index, end_index))
    return ordered[lo:hi + 1]


def words_to_text(words):
    """시각적 줄바꿈은 잇고 PDF 문단 블록 사이만 줄바꿈한다."""
    blocks = []
    current_block = None
    lines = []
    current_line = None
    line_words = []

    def finish_line():
        if line_words:
            lines.append(" ".join(line_words))

    def finish_block():
        finish_line()
        if lines:
            text = lines[0]
            for line in lines[1:]:
                text += line if text.endswith("-") else " " + line
            blocks.append(text)

    for word in _ordered_words(words):
        block, line = word[5], word[6]
        if current_block is not None and block != current_block:
            finish_block()
            lines = []
            line_words = []
            current_line = None
        elif current_line is not None and line != current_line:
            finish_line()
            line_words = []
        current_block = block
        current_line = line
        line_words.append(word[4])
    finish_block()
    return "\n".join(blocks)


class TextSelectMixin:
    def _init_textsel_state(self):
        self._words_cache = {}   # page -> word 목록
        self._selected = []      # 현재 선택된 word 튜플들
        self._search_query = ""
        self._search_hits = []   # (page, QRectF) 목록
        self._search_pos = -1
        self._selection_document_id = ""

    def _reset_textsel(self):
        self._cancel_layout_copy()
        self._words_cache.clear()
        self._selected = []
        self._search_query = ""
        self._search_hits = []
        self._search_pos = -1

    # --- 페이지 전환 훅 ------------------------------------------------

    def show_page(self, index):
        # MRO상 ViewerMixin.show_page가 실제 표시를 한 뒤, 이 페이지에
        # 해당하는 오버레이(선택은 초기화, 검색은 재적용)를 얹는다.
        if index != getattr(self, "page_index", None):
            self._cancel_layout_copy()
        super().show_page(index)
        self._clear_selection()
        self._apply_search_overlay()

    # --- 선택 ----------------------------------------------------------

    def _page_words(self, page):
        ws = self._words_cache.get(page)
        if ws is None:
            ws = self.doc.words(page) if self.doc else []
            self._words_cache[page] = ws
        return ws

    def on_drag_selected(self, start, end):
        """드래그 시작·끝 단어 사이를 읽기 순서대로 연속 선택."""
        if self.doc is None:
            return
        self._selected = words_in_text_flow(
            self._page_words(self.page_index), start, end)
        self._show_selection()

    def on_word_picked(self, pt):
        """더블클릭 — 그 지점의 단어 하나 선택."""
        if self.doc is None:
            return
        self._selected = [
            w for w in self._page_words(self.page_index)
            if w[0] <= pt.x() <= w[2] and w[1] <= pt.y() <= w[3]
        ]
        self._show_selection()

    def select_all(self):
        if self.doc is None:
            return
        self._selected = list(self._page_words(self.page_index))
        self._show_selection()

    def _show_selection(self):
        self.view.canvas.set_selection(
            [QRectF(w[0], w[1], w[2] - w[0], w[3] - w[1]) for w in self._selected])
        n = len(self._selected)
        if n:
            self.statusBar().showMessage("%d개 단어 선택 — Ctrl+C로 복사" % n, 3000)
        elif self.doc is not None and not self.doc.has_text(self.page_index):
            self.statusBar().showMessage(
                "이 페이지에는 텍스트 레이어가 없습니다 (스캔본) — OCR 필요", 3000)
        self._emit_selection_changed()

    def _clear_selection(self):
        self._selected = []
        self.view.canvas.set_selection([])
        self._emit_selection_changed()

    def set_selection_document_id(self, document_id):
        """Set the host application's stable document identifier."""
        self._selection_document_id = str(document_id or "")

    def selection_payload(self):
        """Return the current selection through the public transfer contract."""
        if self.doc is None:
            return None
        return payload_from_words(
            self._selected,
            pdf_page=self.page_index + 1,
            document_id=self._selection_document_id,
            document_path=self.doc.path,
            requires_ocr=not self.doc.has_text(self.page_index),
        )

    def _emit_selection_changed(self):
        signal = getattr(self, "selection_changed", None)
        if signal is not None:
            signal.emit(self.selection_payload())

    def copy_selection(self):
        if not self._selected:
            return
        text = words_to_text(self._selected)
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("복사됨 (%d자)" % len(text), 3000)

    def _cancel_layout_copy(self):
        job = getattr(self, "_layout_copy_job", None)
        self._layout_copy_job = None
        if job is not None:
            job.cancel()
        dialog = getattr(self, "_layout_copy_dialog", None)
        self._layout_copy_dialog = None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    def copy_in_reading_order(self):
        if self.doc is None or getattr(self, "_closing_doc", False):
            return
        import pymupdf
        if not self.doc._doc.permissions & pymupdf.PDF_PERM_COPY:
            self.statusBar().showMessage(localize(
                "This PDF does not allow copying text.", "이 PDF는 텍스트 복사를 허용하지 않습니다."), 6000)
            return
        self._cancel_layout_copy()
        from .layout_copy import LayoutCopyJob
        document, page = self.doc, self.page_index
        generation = document.render_generation
        selected = list(self._selected) or None
        if not selected and not self._page_words(page):
            self.statusBar().showMessage(localize(
                "No text on this page. Run OCR first.", "텍스트가 없는 페이지입니다. 먼저 OCR을 실행해 주세요."), 6000)
            return
        try:
            job = LayoutCopyJob(document, page, selected, self)
        except Exception as error:
            self.statusBar().showMessage(str(error), 6000)
            return
        self._layout_copy_job = job
        dialog = QProgressDialog(localize("Analyzing reading order…", "읽기 순서 분석 중…"),
                                 tr("취소"), 0, 0, self)
        self._layout_copy_dialog = dialog
        dialog.setWindowTitle(localize("Copy in reading order", "읽기 순서로 복사"))
        dialog.setWindowModality(Qt.WindowModal)
        dialog.canceled.connect(self._cancel_layout_copy)

        def finished(text, error):
            if self._layout_copy_job is not job:
                return
            self._layout_copy_job = None
            self._layout_copy_dialog = None
            dialog.close()
            dialog.deleteLater()
            if (self.doc is not document or self.page_index != page or
                    document.render_generation != generation or getattr(self, "_closing_doc", False)):
                return
            if error:
                self.statusBar().showMessage(localize(
                    "Reading-order analysis failed: ", "읽기 순서 분석 실패: ") + error, 6000)
            elif text:
                QApplication.clipboard().setText(text)
                self.statusBar().showMessage(localize(
                    "Copied (%d characters)", "복사됨 (%d자)") % len(text), 3000)

        job.completed.connect(finished)
        dialog.show()
        job.start()

    # --- 검색 ----------------------------------------------------------

    def search_start(self, query):
        """새 검색 — 전체 페이지에서 일치 목록을 만들고 현재 페이지
        이후의 첫 결과로 이동. 같은 질의로 다시 부르면 다음 결과로."""
        query = query.strip()
        if not query or self.doc is None:
            return
        if query == self._search_query and self._search_hits:
            self.search_next()
            return
        self._search_query = query
        self._search_hits = []
        for p in range(self.doc.page_count):
            for x0, y0, x1, y1 in self.doc.search(p, query):
                self._search_hits.append((p, QRectF(x0, y0, x1 - x0, y1 - y0)))
        if not self._search_hits:
            self._search_pos = -1
            self._apply_search_overlay()
            self._update_search_count()
            self.statusBar().showMessage("검색 결과 없음: %s" % query, 3000)
            return
        # 현재 페이지 이후의 첫 결과부터 (없으면 처음으로 감기)
        self._search_pos = 0
        for i, (p, _r) in enumerate(self._search_hits):
            if p >= self.page_index:
                self._search_pos = i
                break
        self._goto_hit()

    def search_next(self):
        if self._search_hits:
            self._search_pos = (self._search_pos + 1) % len(self._search_hits)
            self._goto_hit()

    def search_prev(self):
        if self._search_hits:
            self._search_pos = (self._search_pos - 1) % len(self._search_hits)
            self._goto_hit()

    def search_clear(self):
        self._search_query = ""
        self._search_hits = []
        self._search_pos = -1
        self._apply_search_overlay()
        self._update_search_count()

    def _goto_hit(self):
        page, rect = self._search_hits[self._search_pos]
        if page != self.page_index:
            self.show_page(page)  # 안에서 _apply_search_overlay가 불린다
        else:
            self._apply_search_overlay()
        self.view.ensure_rect_visible(rect)
        self._update_search_count()

    def _apply_search_overlay(self):
        """현재 페이지의 검색 일치를 오버레이로 — 현재 항목은 다른 색."""
        rects = [r for p, r in self._search_hits if p == self.page_index]
        cur = None
        if 0 <= self._search_pos < len(self._search_hits):
            p, r = self._search_hits[self._search_pos]
            if p == self.page_index:
                cur = r
        self.view.canvas.set_search(rects, cur)

    def _update_search_count(self):
        # 검색바의 "n/N" 라벨 — app.py가 만들어둔다.
        if not self._search_hits:
            self._search_count.setText(tr("0건"))
        else:
            self._search_count.setText(
                "%d / %d" % (self._search_pos + 1, len(self._search_hits)))
