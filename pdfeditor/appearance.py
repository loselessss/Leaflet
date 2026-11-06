"""Visible, persistent appearance controls for standalone Leaflet windows."""
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QActionGroup, QApplication, QMenu, QMessageBox, QToolButton

from . import settings
from .i18n import localize
from .icons import fluent_icon


class AppearanceMenu(QMenu):
    def __init__(self, parent=None):
        super().__init__(localize('Dark mode', '다크 모드'), parent)
        self.setObjectName('appearanceMenu')
        self.setIcon(fluent_icon('moon'))
        self.setToolTipsVisible(True)
        menu = self
        group = QActionGroup(menu)
        group.setExclusive(True)
        self.mode_actions = {}
        for mode, label in (
                ('system', localize('Follow Windows settings', 'Windows 설정 따르기')),
                ('light', localize('Light mode', '밝은 모드')),
                ('dark', localize('Dark mode (include document)', '다크 모드 (문서 포함)')),
                ('dark_ui', localize('Dark mode (exclude document)', '다크 모드 (문서 제외)'))):
            action = menu.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked, mode=mode: self._select(mode))
            self.mode_actions[mode] = action
        from .theme import apply_fluent_theme
        app = QApplication.instance()
        if getattr(app, '_leaflet_theme_controller', None) is None:
            apply_fluent_theme(app)
        self.controller = app._leaflet_theme_controller
        self.controller.appearance_changed.connect(self._sync)
        self._sync()

    def _sync(self):
        mode = self.controller.mode or 'system'
        if mode == 'dark' and not settings.document_night():
            mode = 'dark_ui'
        self.mode_actions[mode].setChecked(True)

    def _select(self, mode):
        try:
            if mode in ('dark', 'dark_ui'):
                settings.set_theme_mode('dark', document=mode == 'dark')
            else:
                settings.set_theme_mode(mode)
        except OSError as error:
            QMessageBox.warning(self, localize('Appearance', '화면 테마'), str(error))
            self._sync()
            return
        self.controller.refresh()


class ThemeButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('themeRibbonButton')
        self.setText(localize('Dark mode', '다크 모드'))
        self.setAccessibleName(self.text())
        self.setIcon(fluent_icon('moon'))
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setCheckable(True)
        self.setToolTip(localize(
            'Switch light/dark mode. More options: View → Dark mode.',
            '밝은 모드와 다크 모드를 전환합니다. 세부 설정: 보기 → 다크 모드'))
        self.appearance_menu = AppearanceMenu(self)
        self.controller = self.appearance_menu.controller
        self.mode_actions = self.appearance_menu.mode_actions
        self.clicked.connect(lambda checked:
            self.appearance_menu._select(
                ('dark' if settings.document_night() else 'dark_ui') if checked else 'light'))
        self.controller.appearance_changed.connect(self._sync)
        self._sync()

    def _sync(self):
        self.setChecked(bool(self.controller.dark))
        choice = localize('include document', '문서 포함') if settings.document_night() else localize('exclude document', '문서 제외')
        self.setToolTip(localize('Dark mode (%s). Right-click to choose include/exclude document.',
            '다크 모드 (%s). 우클릭으로 문서 포함·제외 선택') % choice)

    def contextMenuEvent(self, event):
        self.appearance_menu.exec_(event.globalPos())
        event.accept()


def add_appearance_menu(parent):
    menu = AppearanceMenu(parent)
    parent.addMenu(menu)
    return menu


def add_theme_button(toolbar, before):
    button = ThemeButton(toolbar)
    toolbar.insertWidget(before, button)
    return button
