"""시작 페이지 — 문서가 안 열려 있을 때 보이는 홈 화면.

PDF 첫 페이지 미리보기와 즐겨찾기·최근 파일을 보여준다.
파일 열기/즐겨찾기 저장 로직은 여기 없다 — 시그널만 쏘고 MainWindow가
처리한다.
"""

import os

from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QLabel, QLayout, QListView, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QStyle,
    QStyledItemDelegate, QVBoxLayout, QWidget,
)

from . import settings
from .icons import fluent_icon
from .i18n import localize, tr
from .meta import APP_NAME, APP_VERSION
from .home_previews import HomePreviews


class _PreviewDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        view = self.parent()
        path = index.data(Qt.UserRole)
        painter.save()
        painter.setRenderHint(painter.Antialiasing)
        # The list itself is transparent; its stylesheet palette has no card
        # surface color. Use the application's light/dark surface palette.
        palette = QApplication.palette()
        if not path:
            painter.setPen(palette.color(QPalette.Disabled, QPalette.Text))
            painter.drawText(option.rect.adjusted(12, 0, -12, 0),
                             Qt.AlignVCenter | Qt.TextWordWrap, index.data())
            painter.restore()
            return
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        card = option.rect.adjusted(5, 5, -5, -5)
        painter.setPen(QPen(palette.color(QPalette.Highlight if selected else QPalette.Mid), 1))
        background = palette.color(QPalette.Base)
        if selected or hovered:
            background = palette.color(QPalette.Highlight)
            background.setAlpha(35 if selected else 18)
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(card), 8, 8)
        preview = card.adjusted(9, 8, -9, 0)
        preview.setHeight(view.PREVIEW_HEIGHT)
        painter.setPen(Qt.NoPen)
        painter.setBrush(palette.color(QPalette.AlternateBase))
        painter.drawRoundedRect(QRectF(preview), 4, 4)
        image, status = view.previews.lookup(path)
        if image is not None:
            size = image.size().scaled(preview.size() - QSize(8, 8), Qt.KeepAspectRatio)
            target = QRect(preview.center().x() - size.width() // 2,
                           preview.center().y() - size.height() // 2, size.width(), size.height())
            painter.drawImage(target, image)
        else:
            # A paper silhouette remains useful for missing/password-protected files.
            paper = QRect(preview.center().x() - 19, preview.top() + 17, 38, 49)
            painter.setPen(QPen(palette.color(QPalette.Mid), 1))
            painter.setBrush(palette.color(QPalette.Base))
            painter.drawRoundedRect(QRectF(paper), 2, 2)
            painter.setPen(palette.color(QPalette.Text))
            painter.drawText(paper, Qt.AlignCenter, "PDF")
            painter.setPen(palette.color(QPalette.Disabled, QPalette.Text))
            text = (localize("Password required", "암호 필요") if status == "locked" else
                    localize("No preview", "미리보기 없음") if status == "unavailable" else
                    localize("Preparing preview…", "미리보기 준비 중…"))
            painter.drawText(preview.adjusted(0, 75, 0, 0), Qt.AlignCenter, text)
        title = QRect(card.left() + 10, preview.bottom() + 8, card.width() - 20, 20)
        font = QFont(option.font)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.Text))
        painter.drawText(title, Qt.AlignVCenter, painter.fontMetrics().elidedText(
            os.path.basename(path), Qt.ElideMiddle, title.width()))
        font.setBold(False)
        font.setPointSizeF(max(8, font.pointSizeF() - 1))
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.Disabled, QPalette.Text))
        painter.drawText(title.translated(0, 21), Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(os.path.dirname(path), Qt.ElideMiddle, title.width()))
        if option.state & QStyle.State_HasFocus:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(palette.color(QPalette.Highlight), 2, Qt.DotLine))
            painter.drawRoundedRect(QRectF(card.adjusted(2, 2, -2, -2)), 7, 7)
        painter.restore()


class _FileList(QListWidget):
    """Width-adaptive PDF cards, retaining the history list's item/path API."""

    open_requested = pyqtSignal(str)
    layout_changed = pyqtSignal()
    PREVIEW_HEIGHT = 110
    CELL_HEIGHT = 178
    MIN_CELL_WIDTH = 172

    def __init__(self, empty_text, previews, parent=None):
        super().__init__(parent)
        self.previews = previews
        self.columns = 1
        self.setObjectName("startFileList")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setSpacing(0)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setItemDelegate(_PreviewDelegate(self))
        self.setMinimumHeight(56)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._empty_text = empty_text
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemClicked.connect(self._on_click)
        self.itemActivated.connect(self._on_click)
        self.verticalScrollBar().valueChanged.connect(lambda _value: self.layout_changed.emit())

    def _update_grid(self):
        width = max(1, self.viewport().width() - 2)
        columns = max(1, width // self.MIN_CELL_WIDTH)
        empty = not self.count() or not self.item(0).data(Qt.UserRole)
        size = QSize(max(1, width // columns), self.CELL_HEIGHT) if not empty else QSize(width, 56)
        changed = self.gridSize() != size
        self.columns = columns
        if changed:
            self.setGridSize(size)
        for row in range(self.count()):
            # IconMode reserves a small style margin around each item.
            hint = size - QSize(2, 2)
            if self.item(row).sizeHint() != hint:
                self.item(row).setSizeHint(hint)
                changed = True
        if changed:
            self.doItemsLayout()
            self.layout_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid()

    def wheelEvent(self, event):
        # Both sections belong to the outer scroll area, including over cards.
        event.ignore()

    def visible_paths(self):
        viewport = self.viewport().rect()
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QScrollArea):
                clip = QRect(self.viewport().mapFrom(ancestor.viewport(), QPoint()),
                             ancestor.viewport().size())
                viewport = viewport.intersected(clip)
                break
            ancestor = ancestor.parentWidget()
        # History is bounded; checking rectangles does not touch PDF contents.
        return [self.item(row).data(Qt.UserRole) for row in range(self.count())
                if self.item(row).data(Qt.UserRole) and
                self.visualItemRect(self.item(row)).intersects(viewport)]

    def populate(self, paths):
        self.clear()
        if not paths:
            it = QListWidgetItem(self._empty_text)
            it.setFlags(Qt.NoItemFlags)  # 클릭 불가 안내문
            self.addItem(it)
        else:
            for p in paths:
                it = QListWidgetItem(os.path.basename(p))
                it.setToolTip(p)
                it.setData(Qt.UserRole, p)
                self.addItem(it)
        self._update_grid()
        self.layout_changed.emit()

    def path_at(self, pos):
        it = self.itemAt(pos)
        return it.data(Qt.UserRole) if it else None

    def _on_click(self, item):
        p = item.data(Qt.UserRole)
        if p:
            self.open_requested.emit(p)


class StartPage(QWidget):
    open_file = pyqtSignal(str)
    browse = pyqtSignal()
    lists_changed = pyqtSignal()  # 즐겨찾기/최근 목록이 바뀜 (메뉴 갱신용)
    back_to_doc = pyqtSignal()    # 열어둔 문서로 돌아가기
    workspace_requested = pyqtSignal(str)

    def __init__(self, parent=None, *, workspace_mode=None, workspace_switching=False):
        super().__init__(parent)
        self.setObjectName("startPage")
        self._previews = HomePreviews(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._prepare_visible)
        self._layout_timer = QTimer(self)
        self._layout_timer.setSingleShot(True)
        self._layout_timer.timeout.connect(self._fit_favorites)
        self._favorites_expanded = False
        root = QVBoxLayout(self)
        root.setSizeConstraint(QLayout.SetNoConstraint)
        self._root_layout = root
        root.setContentsMargins(48, 34, 48, 38)
        root.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setObjectName("heroTitle")
        f = title.font()
        f.setPointSize(22)
        f.setBold(True)
        title.setFont(f)
        self.mode_label = QLabel(localize("Reader mode", "읽기 모드")
                                 if workspace_mode == "reader" else localize("Editor mode", "편집 모드"))
        self.mode_label.setObjectName("startWorkspaceMode")
        font = self.mode_label.font()
        font.setPointSize(14)
        font.setBold(True)
        self.mode_label.setFont(font)
        self.mode_label.setVisible(workspace_mode in ("reader", "editor"))
        ver = QLabel("v%s" % APP_VERSION)
        ver.setObjectName("subtitle")
        ver.setWordWrap(True)
        purpose = QLabel(localize(
            "Read and annotate in Reader; edit text, organize pages and recognize scanned text in Editor.",
            "리더에서 읽고 메모하세요. 편집기에서 글자와 페이지를 수정하고, OCR로 스캔 문자를 인식하세요."))
        if workspace_mode == "reader":
            purpose.setText(localize("Read, search and annotate PDFs in Reader mode.",
                                    "현재 읽기 모드입니다. PDF를 읽고 검색하거나 주석을 추가할 수 있습니다."))
        elif workspace_mode == "editor":
            purpose.setText(localize("Edit text, organize pages and run OCR in Editor mode.",
                                    "현재 편집 모드입니다. 글자·페이지를 수정하거나 OCR을 실행할 수 있습니다."))
        purpose.setObjectName("subtitle")
        purpose.setWordWrap(True)

        # 시작 화면에서는 주 용도인 PDF를 전면에 둔다. PDF 호환 AI 열기는
        # 파일 메뉴와 드래그 앤 드롭에서 계속 지원한다.
        btn = QPushButton("PDF 파일 열기...")
        btn.setProperty("accent", True)
        btn.setIcon(fluent_icon("open", "#ffffff"))
        btn.setMinimumWidth(132)
        btn.clicked.connect(lambda _c=False: self.browse.emit())

        # 문서를 열어둔 채 홈에 온 경우에만 보이는 '돌아가기' 버튼
        self._back_btn = QPushButton("")
        self._back_btn.setIcon(fluent_icon("back"))
        self._back_btn.clicked.connect(lambda _c=False: self.back_to_doc.emit())
        self._back_btn.hide()

        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addSpacing(16)
        title_row.addWidget(self.mode_label)
        title_row.addWidget(ver)
        title_row.addStretch(1)
        root.addLayout(title_row)
        root.addWidget(purpose)
        root.addSpacing(8)
        row = QHBoxLayout()
        row.addWidget(btn)
        target_mode = 'editor' if workspace_mode == 'reader' else 'reader'
        self.switch_mode_button = QPushButton(localize('Switch to Editor', '편집 모드로 전환')
            if target_mode == 'editor' else localize('Switch to Reader', '읽기 모드로 전환'))
        self.switch_mode_button.setObjectName('startWorkspaceSwitch')
        self.switch_mode_button.setIcon(fluent_icon('magic_wand' if target_mode == 'editor' else 'open'))
        self.switch_mode_button.setVisible(workspace_switching and workspace_mode in ('reader', 'editor'))
        self.switch_mode_button.clicked.connect(lambda _checked=False:
            self.workspace_requested.emit(target_mode))
        row.addWidget(self.switch_mode_button)
        row.addWidget(self._back_btn)
        row.addStretch(1)
        root.addLayout(row)
        root.addSpacing(8)

        self.file_scroll = QScrollArea()
        self.file_scroll.setObjectName("startFilesScroll")
        self.file_scroll.setFrameShape(QFrame.NoFrame)
        self.file_scroll.setWidgetResizable(True)
        self.file_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_scroll.verticalScrollBar().valueChanged.connect(self._schedule_previews)
        files = QWidget()
        files.setObjectName("startFilesContent")
        files.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._files_layout = QVBoxLayout(files)
        self._files_layout.setContentsMargins(0, 0, 0, 0)
        self._files_layout.setSpacing(8)
        self._files_layout.setSizeConstraint(QLayout.SetMinimumSize)
        self.file_scroll.setWidget(files)
        root.addWidget(self.file_scroll, 1)
        self.fav_list = _FileList(localize("No favorites yet — right-click a recent PDF to add one.",
            "즐겨찾기가 없습니다 — 최근 PDF를 우클릭하여 추가하세요."), self._previews)
        self.recent_list = _FileList(localize("No recent PDFs yet.", "최근 연 PDF가 없습니다."), self._previews)
        for label, lst in (("★ 즐겨찾기", self.fav_list), ("최근 파일", self.recent_list)):
            head = QLabel(tr(label))
            head.setProperty("role", "cardTitle")
            hf = head.font()
            hf.setBold(True)
            head.setFont(hf)
            if lst is self.fav_list:
                heading = QHBoxLayout()
                heading.addWidget(head)
                heading.addStretch(1)
                self.more_favorites = QPushButton()
                self.more_favorites.clicked.connect(self._toggle_favorites)
                heading.addWidget(self.more_favorites)
                self._files_layout.addLayout(heading)
            else:
                self._files_layout.addSpacing(8)
                self._files_layout.addWidget(head)
            self._files_layout.addWidget(lst)
            lst.layout_changed.connect(self._schedule_previews)
            lst.layout_changed.connect(lambda: self._layout_timer.start(0))
        self._files_layout.addStretch(1)
        self._previews.changed.connect(self._previews_changed)

        self.fav_list.open_requested.connect(self.open_file)
        self.recent_list.open_requested.connect(self.open_file)
        self.fav_list.customContextMenuRequested.connect(self._fav_menu)
        self.recent_list.customContextMenuRequested.connect(self._recent_menu)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.height() < 520
        side = 24 if self.width() < 720 else 48
        self._root_layout.setContentsMargins(
            side, 18 if compact else 34, side, 18 if compact else 38)
        self._root_layout.setSpacing(8 if compact else 12)
        self._fit_favorites()
        self._schedule_previews()

    def _fit_favorites(self):
        count = sum(bool(self.fav_list.item(row).data(Qt.UserRole))
                    for row in range(self.fav_list.count()))
        total_rows = (count + self.fav_list.columns - 1) // self.fav_list.columns
        default_rows = 1 if self.height() < 780 else 2
        rows = total_rows if self._favorites_expanded else min(default_rows, total_rows)
        for row in range(self.fav_list.count()):
            item = self.fav_list.item(row)
            hidden = bool(count and row >= rows * self.fav_list.columns)
            if item.isHidden() != hidden:
                item.setHidden(hidden)
        self.fav_list.setFixedHeight(rows * self.fav_list.CELL_HEIGHT + 2 if rows else 56)
        self.more_favorites.setVisible(total_rows > default_rows)
        self.more_favorites.setText(localize("Show less", "접기") if self._favorites_expanded else
                                    localize("Show all (%d)", "모두 보기 (%d)") % count)
        recent_count = self.recent_list.count()
        recent_rows = (recent_count + self.recent_list.columns - 1) // self.recent_list.columns
        empty = not recent_count or not self.recent_list.item(0).data(Qt.UserRole)
        self.recent_list.setFixedHeight(56 if empty else recent_rows * self.recent_list.CELL_HEIGHT + 2)

    def _toggle_favorites(self):
        self._favorites_expanded = not self._favorites_expanded
        self._fit_favorites()
        self._schedule_previews()

    def _schedule_previews(self, *_args):
        if self.isVisible():
            self._preview_timer.start(80)

    def _prepare_visible(self):
        if self.isVisible():
            self._fit_favorites()
            self._previews.request(self.fav_list.visible_paths() + self.recent_list.visible_paths())

    def _previews_changed(self):
        self.fav_list.viewport().update()
        self.recent_list.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_previews()

    def hideEvent(self, event):
        self._preview_timer.stop()
        self._layout_timer.stop()
        self._previews.stop()
        super().hideEvent(event)

    def refresh(self):
        # 즐겨찾기는 최근에 추가한 것을 위로
        try:
            settings.trim_recent_files()
        except OSError:
            # A read-only settings file must not prevent opening the home.
            pass
        favorites, recent = settings.favorites(), settings.recent_files()
        from .scene_disk_cache import prune_thumbnails
        prune_thumbnails(favorites + recent)
        self._previews.retain(favorites + recent)
        self.fav_list.populate(list(reversed(favorites)))
        self.recent_list.populate(recent)
        self._fit_favorites()
        self._schedule_previews()

    def set_current_doc(self, name):
        """열려 있는 문서 이름 — None이면 '돌아가기' 버튼을 숨긴다."""
        if name:
            self._back_btn.setText(tr("← %s(으)로 돌아가기" % name))
            self._back_btn.show()
        else:
            self._back_btn.hide()

    # --- 우클릭 메뉴 ---------------------------------------------------

    def _fav_menu(self, pos):
        p = self.fav_list.path_at(pos)
        if not p:
            return
        m = QMenu(self)
        action = m.addAction("즐겨찾기에서 제거",
                             lambda _c=False: self._unfav(p))
        action.setIcon(fluent_icon("star_filled", "#0f6cbd"))
        m.exec_(self.fav_list.mapToGlobal(pos))

    def _recent_menu(self, pos):
        p = self.recent_list.path_at(pos)
        if not p:
            return
        m = QMenu(self)
        if settings.is_favorite(p):
            action = m.addAction(
                "즐겨찾기에서 제거", lambda _c=False: self._unfav(p))
            action.setIcon(fluent_icon("star_filled", "#0f6cbd"))
        else:
            action = m.addAction(
                "즐겨찾기에 추가", lambda _c=False: self._fav(p))
            action.setIcon(fluent_icon("star"))
        remove_action = m.addAction(
            "최근 목록에서 제거", lambda _c=False: self._unrecent(p))
        remove_action.setIcon(fluent_icon("delete"))
        m.exec_(self.recent_list.mapToGlobal(pos))

    def _fav(self, p):
        settings.add_favorite(p)
        self.refresh()
        self.lists_changed.emit()

    def _unfav(self, p):
        settings.remove_favorite(p)
        self.refresh()
        self.lists_changed.emit()

    def _unrecent(self, p):
        settings.remove_recent(p)
        self.refresh()
        self.lists_changed.emit()
