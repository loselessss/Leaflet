"""Visible, persistent appearance controls for standalone Leaflet windows."""
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QActionGroup, QApplication, QMenu, QMessageBox, QToolButton

from . import settings
from .i18n import localize
from .icons import fluent_icon


class ThemeButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('themeRibbonButton')
        self.setText(localize('Dark mode', '다크 모드'))
        self.setAccessibleName(self.text())
        self.setIcon(fluent_icon('moon'))
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setCheckable(True)
        self.setPopupMode(QToolButton.MenuButtonPopup)
        self.setToolTip(localize(
            'Switch light/dark mode. Open the arrow menu to follow Windows settings.',
            '밝은 모드와 다크 모드를 전환합니다. 화살표 메뉴에서 Windows 설정 따르기도 선택할 수 있습니다.'))
        # Override the ribbon's icon-only width so the label remains visible.
        width = self.fontMetrics().horizontalAdvance(self.text()) + 54
        self.setMinimumWidth(width)
        self.setStyleSheet('min-width: %dpx; max-width: %dpx;' % (width, width + 16))
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        self.mode_actions = {}
        for mode, label in (
                ('system', localize('Follow Windows settings', 'Windows 설정 따르기')),
                ('light', localize('Light mode', '밝은 모드')),
                ('dark', localize('Dark mode', '다크 모드'))):
            action = menu.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda _checked, mode=mode: self._select(mode))
            self.mode_actions[mode] = action
        self.setMenu(menu)
        self.clicked.connect(lambda checked: self._select('dark' if checked else 'light'))
        from .theme import apply_fluent_theme
        app = QApplication.instance()
        if getattr(app, '_leaflet_theme_controller', None) is None:
            apply_fluent_theme(app)
        self.controller = app._leaflet_theme_controller
        self.controller.appearance_changed.connect(self._sync)
        self._sync()

    def _sync(self):
        self.setChecked(bool(self.controller.dark))
        self.mode_actions[self.controller.mode or 'system'].setChecked(True)

    def _select(self, mode):
        try:
            settings.set_theme_mode(mode)
        except OSError as error:
            QMessageBox.warning(self, localize('Appearance', '화면 테마'), str(error))
            self._sync()
            return
        self.controller.refresh()


def add_theme_button(toolbar, before):
    button = ThemeButton(toolbar)
    toolbar.insertWidget(before, button)
    return button
