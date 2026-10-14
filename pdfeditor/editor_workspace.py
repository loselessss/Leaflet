"""Standalone editing helpers shared with the separate page organizer."""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QSpinBox, QToolBar, QVBoxLayout, QWidget,
)

from .i18n import localize
from .icons import fluent_icon


class EditorWorkspaceMixin:
    def build_editor_command_bar(self):
        """Compact, grouped editor commands using the existing document actions."""
        bar = QToolBar(localize("Editor tools", "편집 도구"), self)
        bar.setObjectName("editorCommandBar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(20, 20))
        bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self._reader_mode_button = self._mode_button(
            localize("Back to reader", "리더로 돌아가기"), "back")
        self._reader_mode_button.setObjectName("backToReaderButton")
        self._reader_mode_button.setToolTip(localize(
            "Return to the reader; unsaved changes are checked before switching.",
            "미저장 변경을 확인한 뒤 현재 문서를 리더로 전환합니다."))
        self._reader_mode_button.clicked.connect(self._shell.open_reader)
        bar.addWidget(self._reader_mode_button)
        bar.addSeparator()
        bar.addAction(self._open_act)
        bar.addAction(self._save_act)
        bar.addSeparator()
        bar.addAction(self._undo_act)
        bar.addAction(self._redo_act)
        bar.addSeparator()
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            menu = self.menuBar().addMenu(localize("Object", "개체"))
            for action in (controller.action, controller.rectangle_action, controller.image_action):
                menu.addAction(action)
                bar.addAction(action)
                button = bar.widgetForAction(action)
                button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            menu.addSeparator()
            menu.addAction(controller.dock.toggleViewAction())
            bar.addSeparator()
        for action in (self._hand_tool_act, self._select_tool_act, self._edit_act):
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self._artboard_act)
        bar.addAction(self._pages_act)
        for action, label in (
                (self._artboard_act, localize("Artboards", "아트보드")),
                (self._edit_act, localize("Edit text", "텍스트 편집")),
                (self._pages_act, localize("Pages", "페이지 구성"))):
            button = bar.widgetForAction(action)
            button.setProperty("editorLabeled", True)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(label)
            button.style().unpolish(button)
            button.style().polish(button)
            # The toolbar's icon-only width rule otherwise truncates labels.
            width = button.fontMetrics().horizontalAdvance(label) + bar.iconSize().width() + 16
            button.setStyleSheet("min-width: %dpx; max-width: 180px;" % max(90, width))
        bar.addAction(self._rotate_ccw_act)
        bar.addAction(self._rotate_cw_act)
        bar.addSeparator()
        bar.addAction(self._search_act)
        bar.addAction(self._fit_width_act)
        bar.addAction(self._fit_page_act)
        return bar

    def _init_editor_workspace(self, viewer):
        self._page_grid = None
        self._workspace_header = None
        self._editor_overview = False
        self._artboard_view = None
        self._artboard_act = None
        self._artboard_detail_state = None
        if self._shell.workspace_mode == "editor":
            from .editor_object_ui import ObjectController
            self._object_controller = ObjectController(self)
            self.view.object_controller = self._object_controller
        return viewer

    def add_editor_mode_button(self, tool_bar):
        self._editor_mode_button = self._mode_button(
            localize("Edit mode", "편집 모드"), "edit")
        self._editor_mode_button.setObjectName("openEditorModeButton")
        self._editor_mode_button.setToolTip(localize(
            "Open the page organizer in an editor window (Ctrl+E)",
            "편집 창의 페이지 구성으로 열기 (Ctrl+E)"))
        self._editor_mode_button.clicked.connect(lambda: self._shell.open_editor(self))
        tool_bar.addWidget(self._editor_mode_button)
        tool_bar.addSeparator()

    @staticmethod
    def _mode_button(text, icon, *, accent=False):
        button = QPushButton(text)
        button.setMinimumHeight(34)
        button.setIconSize(QSize(20, 20))
        button.setProperty("accent", accent)
        button.setIcon(fluent_icon(icon, "#ffffff" if accent else "#242424"))
        return button

    def is_editor_overview(self):
        return self._editor_overview

    def active_workspace_view(self):
        return self._artboard_view if self.is_editor_overview() else self.view

    def build_artboard_action(self, menu):
        if self._shell.workspace_mode == "editor":
            self._artboard_act = self._act(menu, "아트보드", "Ctrl+Shift+A",
                                          self.toggle_artboards, "two_page")
            self._artboard_act.setCheckable(True)

    def toggle_artboards(self):
        if self.is_editor_overview():
            self.open_page_editor()
        else:
            self.show_editor_overview()
        self._sync_editor_workspace_actions()

    def _create_artboards(self):
        from .artboards import ArtboardView
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(12, 6, 12, 6)
        self._artboard_label = QLabel()
        header.addWidget(self._artboard_label)
        header.addStretch()
        for label, slot in ((localize("Edit page", "페이지 편집"), lambda: self.open_page_editor()),
                            (localize("Fit all", "전체 맞춤"), lambda: self._artboard_view.fit_all())):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, action=slot: action())
            header.addWidget(button)
        header.addWidget(QLabel(localize("Columns", "열")))
        columns = QSpinBox()
        columns.setRange(1, 8)
        columns.setValue(3)
        header.addWidget(columns)
        arrange = QPushButton(localize("Arrange", "정렬"))
        arrange.clicked.connect(lambda: self._artboard_view.arrange(columns.value()))
        header.addWidget(arrange)
        layout.addLayout(header)
        view = self._artboard_view = ArtboardView(panel)
        layout.addWidget(view, 1)
        view.page_selected.connect(self._select_overview_page)
        view.page_activated.connect(lambda page: self.open_page_editor(page))
        view.context_requested.connect(self._artboard_context_menu)
        view.zoom_changed.connect(lambda _zoom: self._update_page_label())
        view.render_failed.connect(lambda _error: self.statusBar().showMessage(localize(
            "Could not prepare a page preview.", "페이지 미리보기를 준비하지 못했습니다."), 4000))
        self._artboard_panel = panel
        self._editor_canvas_stack.addWidget(panel)

    def _artboard_context_menu(self, page, position):
        menu = QMenu(self)
        menu.addAction(localize("Edit page", "페이지 편집"), lambda: self.open_page_editor(page))
        menu.addAction(localize("Page size", "페이지 크기"), self.edit_canvas_size)
        menu.addAction(self._pages_act)
        menu.exec_(position)

    def _select_overview_page(self, row):
        self.show_page(row)

    def refresh_editor_overview(self, *, reset=False):
        if self.is_editor_overview():
            view = self._artboard_view
            changed = view.selected_page != self.page_index
            view.set_document(self.doc, self.page_index, reset=reset)
            if changed:
                view.select_page(self.page_index, ensure_visible=True)
            self._artboard_label.setText(localize("Page %d / %d", "페이지 %d / %d") % (
                self.page_index + 1, self.doc.page_count))
            return
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.refresh()

    def show_editor_overview(self):
        if self._shell.workspace_mode != "editor" or self.doc is None or self.is_editor_overview():
            return
        if not self._commit_inline_text():
            self._sync_editor_workspace_actions()
            return
        self._artboard_detail_state = self.capture_view_state()
        self.set_edit_mode(False)
        self.cancel_note_mode()
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.deactivate()
            controller.dock.hide()
        self.view.stop_rendering()
        self._zoom_render_timer.stop()
        if self._artboard_view is None:
            self._create_artboards()
        self._editor_overview = True
        self._two_page_mode = False
        self._two_page_act.setChecked(False)
        self._editor_canvas_stack.setCurrentWidget(self._artboard_panel)
        self.refresh_editor_overview()
        if not self._artboard_view._camera_ready:
            self._artboard_view.fit_initial()
        self.set_interaction_mode("select", announce=False)
        self._sync_editor_workspace_actions()
        self.update_thumbnail_viewport_marker()
        self._update_page_label()
        self._artboard_view.setFocus()

    def open_page_editor(self, page=None, *, edit_text=True):
        if self._shell.workspace_mode != "editor" or self.doc is None:
            return
        page = self.page_index if page is None else int(page)
        page = max(0, min(page, self.doc.page_count - 1))
        self._editor_overview = False
        self._editor_canvas_stack.setCurrentWidget(self.view)
        self._two_page_mode = False
        self._two_page_act.setChecked(False)
        state = self._artboard_detail_state
        if state is not None and state["page"] == page:
            self.view.zoom = state["zoom"]
        else:
            self._set_fit_zoom(page)
        self.show_page(page)
        if state is not None and state["page"] == page:
            self._restore_scroll(state)
        self._artboard_detail_state = None
        self.set_edit_mode(edit_text)
        self._sync_editor_workspace_actions()
        self._schedule_thumbs()
        self.view.setFocus()

    def _sync_editor_workspace_actions(self):
        action = getattr(self, "_artboard_act", None)
        if action is not None:
            action.setChecked(self.is_editor_overview())
        if hasattr(self, "_pages_act"):
            self._pages_act.setCheckable(False)
            self._pages_act.setToolTip(localize(
                "Open page organization in a separate window (Ctrl+Shift+P)",
                "페이지 구성을 별도 창으로 열기 (Ctrl+Shift+P)"))
        if hasattr(self, "_zoom_input"):
            self._zoom_input.setVisible(True)
