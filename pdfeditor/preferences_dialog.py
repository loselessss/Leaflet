"""Preferences window backed by the existing settings actions."""

from PyQt5.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                            QFormLayout, QGroupBox, QLabel, QMenu, QPushButton,
                            QScrollArea, QVBoxLayout, QWidget)

from .i18n import localize


class PreferencesDialog(QDialog):
    def __init__(self, shell, open_defaults):
        super().__init__(shell)
        self.setWindowTitle(localize("Preferences", "환경설정"))
        self.resize(560, 600)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        hint = QLabel(localize(
            "Changes are saved immediately. Language and renderer changes require a restart.",
            "변경 사항은 즉시 저장됩니다. 언어와 렌더러 변경은 다시 실행하면 적용됩니다."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        sections = QVBoxLayout(content)
        # Keep the action owner alive: callbacks preserve existing permissions,
        # hardware checks, persistence and immediate-update behavior.
        self.actions_menu = QMenu(self)
        shell._add_language_menu(self.actions_menu)
        for action in self.actions_menu.actions():
            if action.menu():
                sections.addWidget(self._section(action.menu()))
        system = QGroupBox(localize("System integration", "시스템 연결"))
        system_layout = QVBoxLayout(system)
        defaults = QPushButton(localize(
            "PDF default app / browser settings…", "PDF 기본 앱 / 브라우저 설정…"))
        defaults.clicked.connect(open_defaults)
        system_layout.addWidget(defaults)
        sections.addWidget(system)
        sections.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText(localize("Close", "닫기"))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _section(self, menu):
        box = QGroupBox(menu.title())
        form = QFormLayout(box)
        form.setSpacing(12)
        groups = set()
        for action in menu.actions():
            if action.isSeparator():
                continue
            if action.menu():
                form.addRow(self._section(action.menu()))
            elif action.actionGroup() and action.actionGroup().isExclusive():
                group = action.actionGroup()
                if group in groups:
                    continue
                groups.add(group)
                choices = group.actions()
                combo = QComboBox()
                for index, choice in enumerate(choices):
                    combo.addItem(choice.text())
                    combo.model().item(index).setEnabled(choice.isEnabled())
                    combo.model().item(index).setToolTip(choice.toolTip())
                    if choice.isChecked():
                        combo.setCurrentIndex(index)
                combo.setAccessibleName(menu.title())
                combo.activated[int].connect(
                    lambda index, choices=choices: choices[index].trigger())
                form.addRow(combo)
            elif action.isCheckable():
                check = QCheckBox(action.text())
                check.setChecked(action.isChecked())
                check.setEnabled(action.isEnabled())
                check.setToolTip(action.toolTip())
                check.clicked.connect(lambda _checked, action=action: action.trigger())
                form.addRow(check)
        return box
