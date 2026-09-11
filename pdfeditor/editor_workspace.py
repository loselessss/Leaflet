"""Standalone editing helpers shared with the separate page organizer."""

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QPushButton, QToolBar

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
        bar.addAction(self._pages_act)
        for action, label in (
                (self._edit_act, localize("Edit text", "텍스트 편집")),
                (self._pages_act, localize("Pages", "페이지 구성"))):
            button = bar.widgetForAction(action)
            button.setProperty("editorLabeled", True)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(label)
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
        return False

    def _select_overview_page(self, row):
        pass

    def refresh_editor_overview(self, *, reset=False):
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.refresh()

    def show_editor_overview(self):
        self.show_page_organizer()

    def open_page_editor(self, page=None, *, edit_text=True):
        if self._shell.workspace_mode != "editor" or self.doc is None:
            return
        page = self.page_index if page is None else int(page)
        page = max(0, min(page, self.doc.page_count - 1))
        self._editor_overview = False
        self._two_page_mode = False
        self._two_page_act.setChecked(False)
        self._set_fit_zoom(page)
        self.show_page(page)
        self.set_edit_mode(edit_text)
        self._sync_editor_workspace_actions()
        self._schedule_thumbs()
        self.view.setFocus()

    def _sync_editor_workspace_actions(self):
        if hasattr(self, "_pages_act"):
            self._pages_act.setCheckable(False)
            self._pages_act.setToolTip(localize(
                "Open page organization in a separate window (Ctrl+Shift+P)",
                "페이지 구성을 별도 창으로 열기 (Ctrl+Shift+P)"))
        if hasattr(self, "_zoom_input"):
            self._zoom_input.setVisible(True)
