"""Opening saved file-list entries and explicitly removing unusable entries."""
import os

from PyQt5.QtWidgets import QMessageBox

from . import settings
from .i18n import localize, tr


class FileHistoryMixin:
    def open_recent(self, path):
        if not os.path.isfile(path):
            self._offer_remove_file_entry(path, localize(
                "The file has moved, was deleted, or is unavailable.",
                "파일이 이동·삭제되었거나 현재 접근할 수 없습니다."))
            return
        tab = self.open_in_tab(path)
        if tab is None or tab.doc is not None or getattr(tab, "_listed_file_open", False):
            return tab
        tab._listed_file_open = True

        def loaded(success):
            tab.load_finished.disconnect(loaded)
            tab._listed_file_open = False
            error = getattr(tab, "_open_error", None)
            # Password cancellation and closing a pending tab are not failures.
            if not success and error:
                self._offer_remove_file_entry(path, error)

        tab.load_finished.connect(loaded)
        return tab

    def _offer_remove_file_entry(self, path, error):
        answer = QMessageBox.question(
            self, tr("열기 실패"), localize(
                "Cannot open this file:\n%s\n\n%s\n\n"
                "Remove it from Recent Files and Favorites? "
                "The original file will not be deleted.",
                "파일을 열 수 없습니다:\n%s\n\n%s\n\n"
                "최근 파일·즐겨찾기 목록에서 제거할까요? 원본 파일은 삭제하지 않습니다.")
            % (path, error), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            settings.remove_file_entry(path)
        except OSError as error:
            QMessageBox.warning(self, tr("열기 실패"), localize(
                "Could not save the updated file lists:\n%s",
                "변경한 파일 목록을 저장하지 못했습니다:\n%s") % error)
            return
        self.refresh_start_page()
