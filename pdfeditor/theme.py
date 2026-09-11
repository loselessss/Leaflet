"""sPDF의 Windows 11 Fluent 기반 밝은 테마."""


FLUENT_STYLESHEET = r"""
QWidget {
    color: #1f1f1f;
    selection-background-color: #0f6cbd;
    selection-color: #ffffff;
}

QMainWindow, QDialog, QWidget#startPage {
    background: #f3f3f3;
}

QLabel#heroTitle {
    color: #1a1a1a;
}

QLabel#subtitle, QLabel[role="secondary"] {
    color: #616161;
}

QFrame#startCard {
    background: #ffffff;
    border: 1px solid #ebebeb;
    border-radius: 12px;
}

QFrame#printSettingsCard, QFrame#printPreviewCard {
    background: #ffffff;
    border: 1px solid #e1e1e1;
    border-radius: 12px;
}

QFrame#printSettingsCard QLabel, QFrame#printPreviewCard QLabel {
    border: none;
    background: transparent;
}

QFrame#printSettingsCard QLabel[role="cardTitle"],
QFrame#printPreviewCard QLabel[role="cardTitle"] {
    color: #242424;
    font-size: 15px;
    font-weight: 600;
}

QPrintPreviewWidget#printPreviewWidget {
    background: #f5f5f5;
    border: 1px solid #ededed;
    border-radius: 8px;
}

QFrame#startCard QLabel[role="cardTitle"] {
    color: #242424;
    font-size: 15px;
    font-weight: 600;
}

QPushButton, QToolButton {
    min-height: 28px;
    padding: 0 10px;
    background: #fbfbfb;
    border: 1px solid #d1d1d1;
    border-radius: 6px;
    color: #1f1f1f;
}

QPushButton:hover, QToolButton:hover {
    background: #f6f6f6;
    border-color: #c7c7c7;
}

QPushButton:pressed, QToolButton:pressed {
    background: #eeeeee;
    color: #525252;
}

QPushButton:focus, QToolButton:focus {
    border-color: #0f6cbd;
}

QPushButton:disabled, QToolButton:disabled {
    background: #f5f5f5;
    border-color: #e5e5e5;
    color: #a0a0a0;
}

QPushButton[accent="true"] {
    background: #0f6cbd;
    border-color: #0f6cbd;
    color: #ffffff;
    font-weight: 600;
}

QPushButton[accent="true"]:hover {
    background: #115ea3;
    border-color: #115ea3;
}

QPushButton[accent="true"]:pressed {
    background: #0c3b5e;
}

QPushButton[danger="true"] {
    color: #c42b1c;
}

QLineEdit, QSpinBox, QInputDialog QLineEdit, QTextBrowser {
    min-height: 28px;
    padding: 0 8px;
    background: #ffffff;
    border: 1px solid #d1d1d1;
    border-bottom: 2px solid #8a8a8a;
    border-radius: 6px;
}

QTextBrowser {
    padding: 9px;
}

QLineEdit:hover, QSpinBox:hover, QTextBrowser:hover {
    border-color: #b8b8b8;
    border-bottom-color: #777777;
}

QLineEdit:focus, QSpinBox:focus, QTextBrowser:focus {
    border-color: #b8b8b8;
    border-bottom-color: #0f6cbd;
}

QComboBox {
    min-height: 28px;
    padding: 0 26px 0 8px;
    background: #ffffff;
    border: 1px solid #d1d1d1;
    border-radius: 6px;
}

QCheckBox, QRadioButton {
    spacing: 8px;
    min-height: 26px;
}

QMenuBar {
    background: transparent;
    border: 0;
    padding: 3px 8px 2px 8px;
}

QMenuBar::item {
    padding: 5px 9px;
    border-radius: 5px;
}

QMenuBar::item:selected, QMenuBar::item:pressed {
    background: rgba(0, 0, 0, 0.055);
}

QMenu {
    background: #ffffff;
    border: 1px solid #d9d9d9;
    padding: 5px;
}

QMenu::item {
    padding: 6px 28px 6px 9px;
    border-radius: 5px;
}

QMenu::item:selected {
    background: #e8f1fa;
    color: #1f1f1f;
}

QMenu::separator {
    height: 1px;
    background: #e5e5e5;
    margin: 5px 7px;
}

QToolBar {
    background: transparent;
    border: 0;
    border-bottom: 1px solid #ebebeb;
    spacing: 2px;
    padding: 5px 10px;
}

QToolBar QToolButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    border-color: transparent;
    background: transparent;
    padding: 0;
    margin: 0 1px;
    border-radius: 5px;
}

QToolBar QToolButton:hover {
    background: #e9e9e9;
}

QToolBar QToolButton:checked {
    background: #dbeaf7;
    border-color: transparent;
    color: #005a9e;
}

QToolBar::separator {
    background: #dedede;
    width: 1px;
    margin: 7px 6px;
}

QToolBar#editorCommandBar, QToolBar#command_bar {
    background: #ffffff;
    border-bottom: 1px solid #e3e7ed;
    spacing: 3px;
    padding: 9px 14px;
}

QToolBar#editorCommandBar QToolButton, QToolBar#command_bar QToolButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    border: 1px solid transparent;
    border-radius: 7px;
    margin: 0 1px;
}

QToolBar#editorCommandBar QToolButton[editorLabeled="true"] {
    min-width: 0;
    max-width: 180px;
    padding: 0 10px;
    font-weight: 600;
}

QToolBar#editorCommandBar QToolButton:hover, QToolBar#command_bar QToolButton:hover {
    background: #f0f3f7;
}

QToolBar#editorCommandBar QToolButton:checked, QToolBar#command_bar QToolButton:checked {
    background: #e8efff;
    color: #244b91;
    border: 1px solid #cfddfa;
}

QPushButton#backToReaderButton, QPushButton#openEditorModeButton {
    background: #f5f7fa;
    border: 1px solid #dce2ea;
    border-radius: 8px;
    padding: 0 13px;
    color: #243247;
    font-weight: 600;
}

QPushButton#backToReaderButton:hover, QPushButton#openEditorModeButton:hover {
    background: #eaf0fa;
    border-color: #b9cbe7;
}

QTabWidget::pane {
    border: 0;
    border-top: 1px solid #e5e5e5;
    background: #f3f3f3;
}

QTabBar {
    background: #f3f3f3;
}

QTabBar::tab {
    min-width: 104px;
    min-height: 30px;
    padding: 0 10px;
    margin: 2px 1px 0 1px;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 5px;
    color: #525252;
}

QTabBar::tab:hover:!selected {
    background: #e9e9e9;
}

QTabBar::tab:selected {
    background: rgba(255, 255, 255, 0.72);
    border-bottom-color: #0f6cbd;
    color: #1f1f1f;
}

QListWidget, QTreeWidget {
    background: #fbfbfb;
    border: 1px solid #e5e5e5;
    border-radius: 7px;
    outline: none;
    padding: 3px;
}

QListWidget::item, QTreeWidget::item {
    border-radius: 6px;
    padding: 5px;
}

QListWidget::item:hover, QTreeWidget::item:hover {
    background: #f0f0f0;
}

QListWidget::item:selected, QTreeWidget::item:selected {
    background: #e3f0fa;
    color: #1f1f1f;
}

QListWidget#startFileList::item {
    min-height: 38px;
    padding: 7px 9px;
}

QFrame#startCard QListWidget#startFileList {
    background: transparent;
    border: 0;
    padding: 0;
}

QListWidget#thumbnailRail {
    background: #f7f7f7;
    border: 0;
    border-radius: 0;
    border-right: 1px solid #e5e5e5;
}

QTreeWidget#bookmarkTree {
    background: #f7f7f7;
    border: 0;
    border-radius: 0;
    border-right: 1px solid #e5e5e5;
    padding: 5px;
}

QTreeWidget#bookmarkTree::item {
    min-height: 26px;
}

QScrollArea#documentViewport {
    background: #e9e9e9;
    border: 0;
}

QWidget#documentViewportSurface {
    background: #e9e9e9;
}

QWidget#searchBar {
    background: #fbfbfb;
    border-bottom: 1px solid #e5e5e5;
}

QWidget#searchBar QToolButton {
    min-width: 28px;
    max-width: 28px;
    padding: 0;
}

QStatusBar {
    background: #f7f7f7;
    border-top: 1px solid #e5e5e5;
    color: #525252;
}

QStatusBar::item {
    border: 0;
}

QDockWidget {
    color: #1f1f1f;
    font-weight: 600;
}

QDockWidget::title {
    background: #f7f7f7;
    border-bottom: 1px solid #e5e5e5;
    padding: 7px;
}

QSplitter::handle {
    background: #e5e5e5;
}

QSplitter::handle:horizontal {
    width: 1px;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background: #c8c8c8;
    min-height: 28px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:vertical:hover {
    background: #a8a8a8;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 2px;
}

QScrollBar::handle:horizontal {
    background: #c8c8c8;
    min-width: 28px;
    border-radius: 4px;
    margin: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: #a8a8a8;
}

QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: transparent;
    border: 0;
    width: 0;
    height: 0;
}

QAbstractScrollArea::corner {
    background: transparent;
    border: 0;
}

QProgressBar {
    min-height: 6px;
    max-height: 6px;
    background: #e5e5e5;
    border: 0;
    border-radius: 3px;
    text-align: center;
}

QProgressBar::chunk {
    background: #0f6cbd;
    border-radius: 3px;
}

QToolTip {
    color: #ffffff;
    background: #2b2b2b;
    border: 1px solid #444444;
    padding: 5px;
}
"""


def apply_fluent_theme(app):
    """모든 sPDF 창에 같은 Fluent 시각 체계를 적용한다."""
    from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette

    # Fusion은 플랫폼과 무관한 고전 Qt 모양을 강제한다. Windows가 제공하는
    # 네이티브 스타일을 유지하고, Windows 11에서만 Variable 글꼴을 고른다.
    families = set(QFontDatabase().families())
    family = (
        "Segoe UI Variable Text"
        if "Segoe UI Variable Text" in families else "Segoe UI"
    )
    app.setFont(QFont(family, 9))

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f3f3f3"))
    palette.setColor(QPalette.WindowText, QColor("#1f1f1f"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f7f7f7"))
    palette.setColor(QPalette.Text, QColor("#1f1f1f"))
    palette.setColor(QPalette.Button, QColor("#fbfbfb"))
    palette.setColor(QPalette.ButtonText, QColor("#1f1f1f"))
    palette.setColor(QPalette.Highlight, QColor("#0f6cbd"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.Link, QColor("#0f6cbd"))
    palette.setColor(QPalette.LinkVisited, QColor("#5c2e91"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#a0a0a0"))
    palette.setColor(
        QPalette.Disabled, QPalette.ButtonText, QColor("#a0a0a0"))
    app.setPalette(palette)
    app.setStyleSheet(FLUENT_STYLESHEET)
