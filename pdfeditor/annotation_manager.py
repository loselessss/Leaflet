"""Modeless, document-bound annotation management without PDF rasterization."""

import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QPushButton, QSplitter, QTextEdit, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from .access import command_allowed
from .i18n import localize, tr
from .icons import fluent_icon


EDITABLE_COMMENT_KINDS = frozenset(("Text", "Highlight", "Underline", "StrikeOut", "Squiggly"))


def annotation_kind(kind):
    labels = {
        "Text": localize("Note", "메모"), "Highlight": localize("Highlight", "형광펜"),
        "Underline": localize("Underline", "밑줄"), "StrikeOut": localize("Strikeout", "취소선"),
        "Squiggly": localize("Squiggly underline", "물결 밑줄"),
    }
    return labels.get(kind, kind)


class _AnnotationItem(QTreeWidgetItem):
    def __lt__(self, other):
        if self.treeWidget().sortColumn() == 0:
            return self.data(0, Qt.UserRole)["page"] < other.data(0, Qt.UserRole)["page"]
        return super().__lt__(other)


class AnnotationManager(QDialog):
    def __init__(self, owner):
        super().__init__(owner, Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setObjectName("annotationManager")
        self.setModal(False)
        self.resize(860, 580)
        self.owner = owner
        self.document = None
        self._page = 0
        self._selection_key = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._load_next_page)

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(localize("Search content, highlighted text or author", "내용·형광펜 텍스트·작성자 검색"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        filters.addWidget(self.search, 1)
        self.kind_filter = QComboBox()
        for label, kind in ((localize("All types", "모든 주석"), "all"),
                            (localize("Notes", "메모"), "Text"),
                            (localize("Highlights", "형광펜"), "Highlight"),
                            (localize("Other annotations", "기타 주석"), "other")):
            self.kind_filter.addItem(label, kind)
        self.kind_filter.currentIndexChanged.connect(self.apply_filter)
        filters.addWidget(self.kind_filter)
        self.refresh_button = QPushButton(localize("Refresh", "새로 고침"))
        self.refresh_button.clicked.connect(self.refresh)
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)
        self.table = QTreeWidget()
        self.table.setObjectName("annotationTable")
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setUniformRowHeights(True)
        self.table.setHeaderLabels([localize("Page", "페이지"), localize("Type", "종류"),
                                    localize("Content / highlighted text", "내용 / 형광펜 텍스트"),
                                    localize("Author", "작성자")])
        self.table.setColumnWidth(0, 65)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 460)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemActivated.connect(lambda *_args: self.go_to_selected())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        splitter.addWidget(self.table)
        self.details = QTextEdit()
        self.details.setObjectName("annotationDetails")
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(localize("Select an annotation to see its full content.", "주석을 선택하면 전체 내용을 볼 수 있습니다."))
        splitter.addWidget(self.details)
        splitter.setSizes([340, 140])
        layout.addWidget(splitter, 1)
        self.count_label = QLabel()
        layout.addWidget(self.count_label)

        actions = QHBoxLayout()
        self.go_button = QPushButton(localize("Go to", "위치로 이동"))
        self.go_button.setIcon(fluent_icon("extract"))
        self.go_button.clicked.connect(self.go_to_selected)
        self.edit_button = QPushButton(localize("Edit comment…", "내용 편집…"))
        self.edit_button.setIcon(fluent_icon("edit"))
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton(tr("주석 삭제"))
        self.delete_button.setIcon(fluent_icon("delete"))
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.go_button, self.edit_button, self.delete_button):
            actions.addWidget(button)
        actions.addStretch()
        self.undo_button = QPushButton(tr("실행 취소"))
        self.redo_button = QPushButton(tr("다시 실행"))
        self.undo_button.clicked.connect(lambda: self._history(False))
        self.redo_button.clicked.connect(lambda: self._history(True))
        actions.addWidget(self.undo_button)
        actions.addWidget(self.redo_button)
        self.save_button = QPushButton(tr("저장"))
        self.save_button.setIcon(fluent_icon("save"))
        self.save_button.clicked.connect(self._save)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)

        delete_action = QAction(self.table)
        delete_action.setShortcut("Delete")
        delete_action.setShortcutContext(Qt.WidgetShortcut)
        delete_action.triggered.connect(self.delete_selected)
        self.table.addAction(delete_action)
        self._selection_changed()

    def selected(self):
        item = self.table.currentItem()
        return item.data(0, Qt.UserRole) if item is not None and not item.isHidden() else None

    def _valid_document(self):
        return self.document is not None and self.owner.doc is self.document

    def refresh(self):
        previous = self.selected()
        self._selection_key = (previous["page"], previous["xref"], previous.get("id")) if previous else None
        self._timer.stop()
        self.document = self.owner.doc
        self._page = 0
        self.table.clear()
        self.table.setSortingEnabled(False)
        name = os.path.basename(self.document.path) if self.document else ""
        title = localize("Annotation manager", "주석 관리") + (" — " + name if name else "")
        self.setProperty("_spdf_i18n_source_windowTitle", title)
        self.setWindowTitle(title)
        self._selection_changed()
        self._update_count()
        if self.document is not None and self.isVisible():
            self._timer.start(0)

    def _load_next_page(self):
        if not self.isVisible() or not self._valid_document():
            return
        try:
            annotations = self.document.annots(self._page, include_text=True)
        except Exception as error:
            self._set_count_text(localize("Unable to read annotations: ", "주석을 읽지 못했습니다: ") + str(error))
            self.table.setSortingEnabled(True)
            return
        for annotation in annotations:
            data = dict(annotation, page=self._page)
            preview = data["text"] or data.get("quote", "") or localize("(No content)", "(내용 없음)")
            item = _AnnotationItem([str(self._page + 1), annotation_kind(data["kind"]),
                                    " ".join(preview.split())[:160], data.get("author", "")])
            item.setData(0, Qt.UserRole, data)
            item.setToolTip(2, preview[:2000])
            self.table.addTopLevelItem(item)
            item.setHidden(not self._matches(data))
            if (data["page"], data["xref"], data.get("id")) == self._selection_key and not item.isHidden():
                self.table.setCurrentItem(item)
        self._page += 1
        self._update_count()
        if self._page < self.document.page_count:
            self._timer.start(1)
        else:
            self.table.setSortingEnabled(True)
            self.table.sortItems(0, Qt.AscendingOrder)
            self._selection_changed()

    def _matches(self, data):
        kind = self.kind_filter.currentData()
        if kind == "other" and data["kind"] in ("Text", "Highlight"):
            return False
        if kind not in ("all", "other") and kind != data["kind"]:
            return False
        query = self.search.text().strip().casefold()
        return not query or query in " ".join((str(data["page"] + 1), data["text"],
            data.get("quote", ""), data.get("author", ""), annotation_kind(data["kind"]))).casefold()

    def apply_filter(self, *_args):
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            item.setHidden(not self._matches(item.data(0, Qt.UserRole)))
        self._selection_changed()
        self._update_count()

    def _update_count(self):
        total = self.table.topLevelItemCount()
        visible = sum(not self.table.topLevelItem(i).isHidden() for i in range(total))
        text = localize("%d / %d annotations", "%d / %d개 주석") % (visible, total)
        if self.document is not None and self._page < self.document.page_count:
            text += localize(" · Reading page %d / %d…", " · %d / %d쪽 읽는 중…") % (self._page + 1, self.document.page_count)
        self._set_count_text(text)

    def _set_count_text(self, text):
        # Automatic widget translation must not restore an earlier count.
        self.count_label.setProperty("_spdf_i18n_source_text", text)
        self.count_label.setText(text)

    def _selection_changed(self):
        data = self.selected()
        valid = self._valid_document()
        allowed = valid and command_allowed(self.owner, "annotation")
        self.go_button.setEnabled(valid and data is not None)
        self.edit_button.setEnabled(allowed and data is not None and data["kind"] in EDITABLE_COMMENT_KINDS)
        self.delete_button.setEnabled(allowed and data is not None)
        self.save_button.setEnabled(valid and command_allowed(self.owner, "save"))
        if valid and self.document.annotation_mode:
            undo, redo = self.document.can_undo_annotation, self.document.can_redo_annotation
        else:
            undo, redo = bool(getattr(self.owner, "_undo_stack", ())), bool(getattr(self.owner, "_redo_stack", ()))
        history = valid and command_allowed(self.owner, "history")
        self.undo_button.setEnabled(history and undo)
        self.redo_button.setEnabled(history and redo)
        text = data["text"] if data else ""
        if data and data.get("quote"):
            text += ("\n\n" if text else "") + localize("Highlighted text:\n", "표시된 텍스트:\n") + data["quote"]
        self.details.setPlainText(text)

    def go_to_selected(self):
        data = self.selected()
        if self._valid_document() and data:
            self.owner.navigate_to_annotation(data["page"], data["xref"])

    def edit_selected(self):
        data = self.selected()
        if self._valid_document() and data and self.edit_button.isEnabled():
            self.owner.edit_managed_annotation(data["page"], data["xref"])

    def delete_selected(self):
        data = self.selected()
        if self._valid_document() and data and self.delete_button.isEnabled():
            self.owner.delete_managed_annotation(data["page"], data["xref"])

    def _history(self, forward):
        if self._valid_document() and command_allowed(self.owner, "history"):
            (self.owner.redo if forward else self.owner.undo)()

    def _save(self):
        if self._valid_document() and command_allowed(self.owner, "save"):
            if self.owner.save():
                self.refresh()

    def _context_menu(self, position):
        item = self.table.itemAt(position)
        if item is None:
            return
        self.table.setCurrentItem(item)
        menu = QMenu(self)
        for button, callback in ((self.go_button, self.go_to_selected), (self.edit_button, self.edit_selected),
                                  (self.delete_button, self.delete_selected)):
            action = menu.addAction(button.icon(), button.text(), callback)
            action.setEnabled(button.isEnabled())
        menu.exec_(self.table.viewport().mapToGlobal(position))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def reset(self):
        self._timer.stop()
        self.hide()
        self.document = None
        self.table.clear()
        self._selection_changed()
