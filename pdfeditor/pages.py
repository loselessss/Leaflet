"""PagesMixin — 페이지 회전/삭제/순서변경/병합/추출(설계 §3.5).

되돌리기는 EditMixin의 스냅샷 스택을 그대로 쓴다(_push_undo) — 구조
변경도 문서 전체 스냅샷이므로 같은 방식으로 되돌아간다.
"""

import os

from PyQt5.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from .filetypes import DOCUMENT_OPEN_FILTER
from .access import editing_command
from .i18n import localize, tr

from .core import PasswordRequired
from .page_ranges import page_group_label, parse_page_groups


def PageOrganizerDialog(*args, **kwargs):
    from .page_organizer import PageOrganizerDialog as Dialog
    return Dialog(*args, **kwargs)


def page_order_after_move(page_count, selected, insertion_index):
    """선택 페이지를 안정적으로 묶어 insertion_index 앞에 놓은 새 순서."""
    selected = sorted(set(int(index) for index in selected))
    if not selected or any(index < 0 or index >= page_count for index in selected):
        raise ValueError("옮길 페이지가 올바르지 않습니다.")
    insertion_index = max(0, min(int(insertion_index), page_count))
    remaining = [index for index in range(page_count) if index not in selected]
    adjusted = insertion_index - sum(index < insertion_index for index in selected)
    adjusted = max(0, min(adjusted, len(remaining)))
    order = remaining[:adjusted] + selected + remaining[adjusted:]
    return order, list(range(adjusted, adjusted + len(selected)))


class _MergeCancelled(Exception):
    pass


class PagesMixin:
    @editing_command
    def show_page_organizer(self):
        if self.doc is None:
            return
        dialog = PageOrganizerDialog(
            self, grid=self._shell.workspace_mode == "editor")
        dialog.exec_()

    @editing_command
    def import_outline_text(self):
        if self.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, tr("TXT 책갈피 가져오기"), "", "Text files (*.txt)")
        if not path:
            return
        try:
            from .outline_import import parse_outline_text, read_outline_file
            entries = parse_outline_text(
                read_outline_file(path), self.doc.page_count)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("TXT 책갈피 가져오기"), str(error))
            return
        if self.doc.bookmarks() and QMessageBox.question(
                self, tr("TXT 책갈피 가져오기"), localize(
                    "Replace the document's existing bookmarks?",
                    "문서의 기존 책갈피를 바꿀까요?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        if self.apply_document_change(
                lambda: self.doc.replace_bookmarks(entries)):
            self.set_sidebar_mode("bookmarks")
            self.statusBar().showMessage(
                tr("%d개 책갈피를 가져왔습니다." % len(entries)), 4000)

    @editing_command
    def add_watermark_dialog(self):
        if self.doc is None:
            return
        from .tool_dialogs import WatermarkDialog
        dialog = WatermarkDialog(
            self.page_index, self.doc.page_count, self)
        if dialog.exec_() != dialog.Accepted:
            return
        self.apply_document_change(
            lambda: self.doc.add_watermark(
                dialog.pages, dialog.text.text(), dialog.font_size.value(),
                dialog.opacity.value() / 100.0, dialog.angle.value()),
            structural=False)

    @editing_command
    def export_pdf_images(self):
        if self.doc is None:
            return
        from .tool_dialogs import ExportImagesDialog
        dialog = ExportImagesDialog(
            self.page_index, self.doc.page_count, self)
        if dialog.exec_() != dialog.Accepted:
            return
        folder = QFileDialog.getExistingDirectory(
            self, tr("이미지 저장 폴더"), os.path.dirname(self.doc.path))
        if not folder:
            return
        image_format = dialog.format.currentData()
        extension = "jpg" if image_format == "jpeg" else "png"
        base = os.path.splitext(os.path.basename(self.doc.path))[0]
        outputs = [os.path.join(
            folder, "%s_page_%04d.%s" % (base, page + 1, extension))
            for page in dialog.pages]
        existing = [path for path in outputs if os.path.exists(path)]
        if existing and QMessageBox.question(
                self, tr("파일 덮어쓰기"), localize(
                    "%d image files already exist. Overwrite them?" % len(existing),
                    "같은 이름의 이미지 %d개가 있습니다. 덮어쓸까요?" % len(existing)),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            from .conversions import write_image_atomic
            for page, output in zip(dialog.pages, outputs):
                write_image_atomic(self.doc.page_image_bytes(
                    page, image_format, dialog.dpi.value()), output)
        except Exception as error:
            QMessageBox.critical(
                self, tr("PDF를 이미지로"), str(error))
            return
        self.statusBar().showMessage(localize(
            "%d images saved to %s" % (len(outputs), folder),
            "%d개 이미지 저장됨: %s" % (len(outputs), folder)), 6000)

    @editing_command
    def organizer_move_pages(self, rows, at):
        if self.doc is None:
            return None
        try:
            order, new_rows = page_order_after_move(
                self.doc.page_count, rows, at)
        except ValueError as error:
            QMessageBox.warning(self, "페이지 이동", str(error))
            return None
        if order == list(range(self.doc.page_count)):
            return new_rows
        if not self.apply_document_change(lambda: self.doc.reorder_pages(order)):
            return None
        self.show_page(new_rows[0])
        self.statusBar().showMessage(
            "%d개 페이지를 %d페이지 위치로 이동" %
            (len(new_rows), new_rows[0] + 1), 3000)
        return new_rows

    @editing_command
    def organizer_delete_pages(self, rows):
        rows = sorted(set(rows))
        self._push_undo(structural=True)
        self.doc.delete_pages(rows)
        keep = min(rows[0], self.doc.page_count - 1)
        self._after_structure_changed(keep_page=keep)
        self.mark_dirty()
        self.statusBar().showMessage(
            "%d개 페이지 삭제" % len(rows), 3000)
        return keep

    @editing_command
    def organizer_insert_pdfs(self, paths, at):
        if self.doc is None or not paths:
            return 0
        at = max(0, min(at, self.doc.page_count))
        undo_before = list(self._undo_stack)
        redo_before = list(self._redo_stack)
        undo_structural_before = list(self._undo_structural)
        redo_structural_before = list(self._redo_structural)
        self._push_undo(structural=True)
        snapshot = self._undo_stack[-1]
        total = 0
        try:
            for path in paths:
                password = None
                while True:
                    try:
                        count = self.doc.insert_pdf(
                            path, at=at + total, password=password)
                        break
                    except PasswordRequired:
                        password, ok = QInputDialog.getText(
                            self, "암호 필요",
                            "%s 파일의 비밀번호를 입력하세요."
                            % os.path.basename(path), QLineEdit.Password)
                        if not ok:
                            raise _MergeCancelled()
                total += count
        except _MergeCancelled:
            self.doc.restore(snapshot)
            self._undo_stack = undo_before
            self._redo_stack = redo_before
            self._undo_structural = undo_structural_before
            self._redo_structural = redo_structural_before
            self._update_edit_actions()
            return 0
        except Exception as error:
            self.doc.restore(snapshot)
            self._undo_stack = undo_before
            self._redo_stack = redo_before
            self._undo_structural = undo_structural_before
            self._redo_structural = redo_structural_before
            self._update_edit_actions()
            QMessageBox.critical(
                self, "PDF 추가 실패",
                "PDF를 추가할 수 없습니다.\n\n%s" % error)
            return 0
        self._after_structure_changed(keep_page=at)
        self.mark_dirty()
        self.statusBar().showMessage(
            "%d개 파일에서 %d페이지 추가" % (len(paths), total), 5000)
        return total

    # --- 회전 ----------------------------------------------------------

    @editing_command
    def rotate_page_cw(self):
        self._rotate(90)

    @editing_command
    def rotate_page_ccw(self):
        self._rotate(-90)

    @editing_command
    def _rotate(self, deg):
        if self.doc is None:
            return
        self._push_undo()
        self.doc.rotate_page(self.page_index, deg)
        self._after_page_content_changed()
        self.mark_dirty()
        # 회전하면 페이지 비율이 바뀌므로 창 너비 맞춤을 다시 계산
        self.zoom_fit()

    # --- 삭제 ----------------------------------------------------------

    @editing_command
    def delete_current_page(self):
        if self.doc is None:
            return
        if self.doc.page_count <= 1:
            QMessageBox.information(
                self, "삭제 불가", "마지막 한 페이지는 삭제할 수 없습니다.")
            return
        ret = QMessageBox.question(
            self, "페이지 삭제",
            "%d쪽을 삭제할까요? (Ctrl+Z로 되돌릴 수 있습니다)"
            % (self.page_index + 1))
        if ret != QMessageBox.Yes:
            return
        self._push_undo(structural=True)
        self.doc.delete_page(self.page_index)
        self._after_structure_changed(keep_page=self.page_index)
        self.mark_dirty()

    # --- 병합 / 분리 / 추출 ----------------------------------------------

    @editing_command
    def merge_pdf(self):
        if self.doc is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "병합할 PDF/Illustrator 파일 선택 (여러 파일 선택 가능)",
            "", tr(DOCUMENT_OPEN_FILTER))
        if not paths:
            return
        # 현재 페이지 '뒤'에 끼워넣는 게 직관적
        at = self.page_index + 1
        keep_page = self.page_index
        undo_before = list(self._undo_stack)
        redo_before = list(self._redo_stack)
        undo_structural_before = list(self._undo_structural)
        redo_structural_before = list(self._redo_structural)
        self._push_undo(structural=True)
        snapshot = self._undo_stack[-1]
        total_pages = 0
        try:
            for path in paths:
                password = None
                while True:
                    try:
                        count = self.doc.insert_pdf(path, at=at, password=password)
                        break
                    except PasswordRequired:
                        password, ok = QInputDialog.getText(
                            self, "암호 필요",
                            "%s 파일의 비밀번호를 입력하세요." % os.path.basename(path),
                            QLineEdit.Password)
                        if not ok:
                            raise _MergeCancelled()
                at += count
                total_pages += count
        except _MergeCancelled:
            self.doc.restore(snapshot)
            self._undo_stack = undo_before
            self._redo_stack = redo_before
            self._undo_structural = undo_structural_before
            self._redo_structural = redo_structural_before
            self._update_edit_actions()
            self._after_structure_changed(keep_page=keep_page)
            self.statusBar().showMessage("PDF 병합이 취소되었습니다.", 3000)
            return
        except Exception as e:
            # 여러 파일 중 하나라도 실패하면 앞에서 삽입한 파일까지 되돌린다.
            self.doc.restore(snapshot)
            self._undo_stack = undo_before
            self._redo_stack = redo_before
            self._undo_structural = undo_structural_before
            self._redo_structural = redo_structural_before
            self._update_edit_actions()
            self._after_structure_changed(keep_page=keep_page)
            QMessageBox.critical(
                self, "병합 실패", "PDF를 병합할 수 없습니다.\n\n%s" % e)
            return
        first_inserted_page = self.page_index + 1
        self._after_structure_changed(keep_page=first_inserted_page)
        self.mark_dirty()
        self.statusBar().showMessage(
            "%d개 파일, %d페이지 병합됨" % (len(paths), total_pages), 5000)

    @editing_command
    def split_pdf(self):
        """입력한 페이지 그룹을 각각 별도 PDF로 저장한다."""
        if self.doc is None:
            return
        spec, ok = QInputDialog.getText(
            self, "PDF 분리",
            "분리할 페이지 범위를 입력하세요.\n"
            "* = 모든 페이지를 낱장으로 분리\n"
            "세미콜론(;)마다 별도 PDF: 1-3;4,6;7-9",
            QLineEdit.Normal, "*")
        if not ok:
            return
        try:
            groups = parse_page_groups(spec, self.doc.page_count)
        except ValueError as e:
            QMessageBox.warning(self, "범위 확인", str(e))
            return

        folder = QFileDialog.getExistingDirectory(
            self, "분리한 PDF를 저장할 폴더", os.path.dirname(self.doc.path))
        if not folder:
            return

        base = os.path.splitext(os.path.basename(self.doc.path))[0]
        outputs = []
        for number, indices in enumerate(groups, start=1):
            name = "%s_split_%02d_%s.pdf" % (
                base, number, page_group_label(indices))
            outputs.append(os.path.join(folder, name))

        existing = [path for path in outputs if os.path.exists(path)]
        if existing:
            answer = QMessageBox.question(
                self, "파일 덮어쓰기",
                "같은 이름의 파일 %d개가 있습니다. 모두 덮어쓸까요?" % len(existing))
            if answer != QMessageBox.Yes:
                return

        completed = 0
        try:
            for indices, out_path in zip(groups, outputs):
                self.doc.extract_pages(indices, out_path)
                completed += 1
        except Exception as e:
            QMessageBox.critical(
                self, "분리 실패",
                "%d개 파일을 저장한 뒤 중단되었습니다.\n\n%s" % (completed, e))
            return
        self.statusBar().showMessage(
            "%d개 PDF로 분리됨: %s" % (len(outputs), folder), 7000)

    @editing_command
    def extract_current_page(self):
        """현재 페이지만 새 PDF로 저장 — 원본은 그대로."""
        if self.doc is None:
            return
        base = os.path.splitext(os.path.basename(self.doc.path))[0]
        suggest = os.path.join(os.path.dirname(self.doc.path),
                               "%s_p%d.pdf" % (base, self.page_index + 1))
        path, _ = QFileDialog.getSaveFileName(
            self, "현재 페이지 추출", suggest, "PDF 파일 (*.pdf)")
        if not path:
            return
        try:
            self.doc.extract_pages([self.page_index], path)
        except Exception as e:
            QMessageBox.critical(
                self, "추출 실패", "저장할 수 없습니다.\n\n%s" % e)
            return
        self.statusBar().showMessage("추출됨: %s" % path, 5000)

    # --- 구조 변경 후 갱신 -------------------------------------------------

    def _after_structure_changed(self, keep_page=0):
        """페이지 수/순서가 바뀐 뒤 — 썸네일을 다시 만들고 위치를 보정한다.

        _after_page_content_changed(내용만 바뀜)와 달리 썸네일 목록 자체를
        새로 만들어야 한다.
        """
        self.doc.invalidate_render()
        self.clear_navigation_history()
        self._cache.clear()
        self._words_cache.clear()
        if hasattr(self, "_annot_cache"):
            self._annot_cache.clear()
        # 검색 결과는 페이지 번호가 어긋나므로 버린다(좌표가 안 맞음)
        self.search_clear()

        count = self.doc.page_count
        self.thumbs.blockSignals(True)
        self.thumbs.reset_pages(count)
        self.thumbs.blockSignals(False)
        self.bookmarks.set_bookmarks(self.doc.bookmarks())
        self._restoring_view = True
        try:
            self.show_page(max(0, min(keep_page, count - 1)))
        finally:
            self._restoring_view = False
        self._schedule_thumbs()
        self.refresh_editor_overview(reset=True)
        self._notes_changed()
