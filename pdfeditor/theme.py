"""Windows 설정을 따르는 Fluent UI. PDF 원본 색상은 바꾸지 않는다."""


FLUENT_STYLESHEET = r"""
QWidget {
    color: #1f1f1f;
    selection-background-color: #0f6cbd;
    selection-color: #ffffff;
}

QMainWindow, QDialog, QWidget#startPage {
    background: #f3f3f3;
}

QScrollArea#startFilesScroll, QWidget#startFilesContent {
    background: transparent;
    border: 0;
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
    padding: 0;
    margin: 0;
    border: 0;
}

QListWidget#startFileList {
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


def _dark_stylesheet():
    import re
    # Keep white text on accent buttons while replacing white surfaces.
    sheet = re.sub(r'(?<![\w-])(?:selection-)?color: #ffffff;',
                   lambda m: m[0].replace('#ffffff', 'WHITE_TEXT'), FLUENT_STYLESHEET)
    colors = {
        '#1a1a1a':'#ffffff', '#1f1f1f':'#f3f3f3', '#242424':'#f3f3f3',
        '#243247':'#e5e5e5', '#244b91':'#b4d9ff', '#005a9e':'#b4d9ff',
        '#525252':'#c7c7c7', '#616161':'#b8b8b8', '#777777':'#9b9b9b',
        '#8a8a8a':'#858585', '#a0a0a0':'#777777', '#a8a8a8':'#858585',
        '#b8b8b8':'#616161', '#b9cbe7':'#416383', '#c42b1c':'#ff99a4',
        '#c7c7c7':'#555555', '#c8c8c8':'#616161', '#cfddfa':'#416383',
        '#d1d1d1':'#555555', '#d9d9d9':'#444444', '#dbeaf7':'#28435c',
        '#dce2ea':'#444444', '#dedede':'#444444', '#e1e1e1':'#444444',
        '#e3e7ed':'#383838', '#e3f0fa':'#28435c', '#e5e5e5':'#383838',
        '#e8efff':'#28435c', '#e8f1fa':'#28435c', '#e9e9e9':'#383838',
        '#eaf0fa':'#28435c', '#ebebeb':'#383838', '#ededed':'#383838',
        '#eeeeee':'#383838', '#f0f0f0':'#383838', '#f0f3f7':'#383838',
        '#f3f3f3':'#202020', '#f5f5f5':'#292929', '#f5f7fa':'#292929',
        '#f6f6f6':'#383838', '#f7f7f7':'#292929', '#fbfbfb':'#2b2b2b',
        '#ffffff':'#262626',
    }
    sheet = re.sub(r'#[0-9a-f]{6}', lambda m: colors.get(m[0], m[0]), sheet)
    return (sheet.replace('WHITE_TEXT', '#ffffff')
            .replace('rgba(0, 0, 0, 0.055)', 'rgba(255, 255, 255, 0.08)')
            .replace('rgba(255, 255, 255, 0.72)', 'rgba(255, 255, 255, 0.08)'))


DARK_STYLESHEET = _dark_stylesheet()


def reader_background():
    from PyQt5.QtGui import QColor
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance()
    return QColor('#1c1c1c' if app and app.property('leafletDark') else '#e8e8e8')


def apply_theme_colors(app, dark):
    from PyQt5.QtGui import QColor, QPalette
    app.setProperty('leafletDark', bool(dark))
    palette = QPalette()
    colors = {
        QPalette.Window: '#202020' if dark else '#f3f3f3',
        QPalette.WindowText: '#f3f3f3' if dark else '#1f1f1f',
        QPalette.Base: '#262626' if dark else '#ffffff',
        QPalette.AlternateBase: '#292929' if dark else '#f7f7f7',
        QPalette.Text: '#f3f3f3' if dark else '#1f1f1f',
        QPalette.Button: '#2b2b2b' if dark else '#fbfbfb',
        QPalette.ButtonText: '#f3f3f3' if dark else '#1f1f1f',
        QPalette.Highlight: '#0f6cbd', QPalette.HighlightedText: '#ffffff',
        QPalette.Link: '#60b4ff' if dark else '#0f6cbd',
        QPalette.LinkVisited: '#c8a7ff' if dark else '#5c2e91',
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        palette.setColor(QPalette.Disabled, role, QColor('#777777' if dark else '#a0a0a0'))
    app.setPalette(palette)
    app.setStyleSheet(DARK_STYLESHEET if dark else FLUENT_STYLESHEET)
    for window in app.topLevelWidgets():
        chrome = getattr(window, '_window_chrome', None)
        if chrome is not None:
            chrome.apply_theme(dark)


def apply_fluent_theme(app):
    """모든 sPDF 창에 같은 Fluent 시각 체계를 적용한다."""
    from PyQt5.QtGui import QFont, QFontDatabase

    # Fusion은 플랫폼과 무관한 고전 Qt 모양을 강제한다. Windows가 제공하는
    # 네이티브 스타일을 유지하고, Windows 11에서만 Variable 글꼴을 고른다.
    families = set(QFontDatabase().families())
    family = (
        "Segoe UI Variable Text"
        if "Segoe UI Variable Text" in families else "Segoe UI"
    )
    app.setFont(QFont(family, 9))

    from .system_theme import SystemThemeController
    controller = getattr(app, '_leaflet_theme_controller', None)
    if controller is None:
        controller = app._leaflet_theme_controller = SystemThemeController(app)
    controller.refresh()
