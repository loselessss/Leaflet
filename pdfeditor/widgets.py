"""재사용 위젯 — PageCanvas/PageView(메인 페이지 뷰), ThumbList(썸네일)."""

from PyQt5.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QImage, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QApplication, QListWidget, QListWidgetItem,
    QScrollArea, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTreeWidget, QTreeWidgetItem, QWidget, QMenu,
)

from .i18n import tr

THUMB_W = 120  # 썸네일 가로 픽셀
THUMB_H = int(THUMB_W * 1.5)
THUMB_ITEM_H = THUMB_H + 28
THUMB_MIN_W = 72
THUMB_MAX_W = 360
THUMB_LABEL_H = 22
THUMB_ITEM_EXTRA_H = 32
THUMB_SPREAD_ROLE = Qt.UserRole + 2

# 오버레이 색 — 선택은 파랑, 검색은 노랑, 현재 검색 항목은 주황
SEL_COLOR = QColor(0, 120, 215, 70)
SEARCH_COLOR = QColor(255, 200, 0, 80)
SEARCH_CUR_COLOR = QColor(255, 120, 0, 110)
EDIT_BOX_COLOR = QColor(0, 160, 90, 160)  # 편집 가능한 span 테두리(초록)
BOOKMARK_PAGE_ROLE = Qt.UserRole + 10
BOOKMARK_INDEX_ROLE = Qt.UserRole + 11


class BookmarkTree(QTreeWidget):
    """Hierarchical PDF outline that emits zero-based destination pages."""

    page_selected = pyqtSignal(int)
    add_requested = pyqtSignal()
    rename_requested = pyqtSignal(int, str)
    delete_requested = pyqtSignal(int)
    reorder_requested = pyqtSignal(object)

    def __init__(self, parent=None, *, read_only=False):
        super().__init__(parent)
        self._read_only = bool(read_only)
        self.setObjectName("bookmarkTree")
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.itemActivated.connect(self._activate)
        self.itemClicked.connect(self._activate)
        self.itemChanged.connect(self._renamed)
        self.setDragDropMode(QAbstractItemView.NoDragDrop if self._read_only
                             else QAbstractItemView.InternalMove)
        if self._read_only:
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)

    def set_bookmarks(self, entries):
        self.blockSignals(True)
        self.clear()
        parents = []
        for index, (level, title, page) in enumerate(entries):
            level = max(1, int(level))
            item = QTreeWidgetItem([str(title or tr("(제목 없음)"))])
            page_index = int(page) - 1
            item.setData(0, BOOKMARK_PAGE_ROLE, page_index)
            item.setData(0, BOOKMARK_INDEX_ROLE, index)
            if not self._read_only:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
            else:
                item.setFlags(item.flags() & ~(Qt.ItemIsEditable |
                                               Qt.ItemIsDragEnabled |
                                               Qt.ItemIsDropEnabled))
            if page_index >= 0:
                item.setToolTip(0, tr("%d쪽" % (page_index + 1)))
            if level == 1 or not parents:
                self.addTopLevelItem(item)
                parents = [item]
            else:
                parent_index = min(level - 2, len(parents) - 1)
                parents[parent_index].addChild(item)
                parents = parents[:parent_index + 1] + [item]
        if not entries:
            empty = QTreeWidgetItem([tr("책갈피 없음")])
            empty.setFlags(empty.flags() & ~Qt.ItemIsEnabled)
            self.addTopLevelItem(empty)
        self.expandToDepth(0)
        self.blockSignals(False)

    def _renamed(self, item, column):
        if self._read_only:
            return
        index = item.data(0, BOOKMARK_INDEX_ROLE)
        if index is not None:
            title = item.text(0)
            QTimer.singleShot(0, lambda: self.rename_requested.emit(int(index), title))

    def _context_menu(self, position):
        if self._read_only:
            return
        from .icons import fluent_icon
        menu = QMenu(self)
        action = menu.addAction(fluent_icon("add_file"),
                                tr("현재 페이지 책갈피 추가"))
        action.triggered.connect(self.add_requested)
        item = self.itemAt(position)
        if item is not None and item.data(0, BOOKMARK_INDEX_ROLE) is not None:
            action = menu.addAction(fluent_icon("edit"), tr("책갈피 이름 변경"))
            action.triggered.connect(lambda: self.editItem(item, 0))
            action = menu.addAction(fluent_icon("delete"), tr("책갈피 삭제"))
            index = int(item.data(0, BOOKMARK_INDEX_ROLE))
            action.triggered.connect(lambda: self.delete_requested.emit(index))
        menu.exec_(self.viewport().mapToGlobal(position))

    def dropEvent(self, event):
        if self._read_only:
            event.ignore()
            return
        self.blockSignals(True)
        try:
            super().dropEvent(event)
        finally:
            self.blockSignals(False)
        order = []

        def visit(parent, level):
            for i in range(parent.childCount()):
                item = parent.child(i)
                index = item.data(0, BOOKMARK_INDEX_ROLE)
                if index is not None:
                    order.append((level, int(index)))
                    visit(item, level + 1)

        visit(self.invisibleRootItem(), 1)
        if order:
            QTimer.singleShot(0, lambda: self.reorder_requested.emit(order))

    def _activate(self, item, _column=0):
        page = item.data(0, BOOKMARK_PAGE_ROLE)
        if page is not None and int(page) >= 0:
            self.page_selected.emit(int(page))

    def select_page(self, page):
        root = self.invisibleRootItem()
        stack = [root.child(i) for i in range(root.childCount())]
        best = None
        best_page = -1
        while stack:
            item = stack.pop(0)
            item_page = item.data(0, BOOKMARK_PAGE_ROLE)
            if (item_page is not None and best_page <= int(item_page) <= page):
                best = item
                best_page = int(item_page)
            stack[0:0] = [item.child(i) for i in range(item.childCount())]
        self.setCurrentItem(best)


def thumbnail_layout_rects(item_rect, icon_size, aspect):
    """Return non-overlapping image and page-number rectangles."""
    item_rect = QRectF(item_rect)
    if item_rect.isEmpty():
        return QRectF(), QRectF()

    padding = 5.0
    gap = 3.0
    content = item_rect.adjusted(padding, padding, -padding, -padding)
    label_height = min(float(THUMB_LABEL_H), max(0.0, content.height()))
    label_rect = QRectF(
        content.left(), content.bottom() - label_height + 1,
        content.width(), label_height)

    available_height = max(0.0, label_rect.top() - gap - content.top())
    box_width = min(float(icon_size.width()), content.width())
    box_height = min(float(icon_size.height()), available_height)
    if box_width <= 0 or box_height <= 0:
        return QRectF(), label_rect

    aspect = max(0.0001, float(aspect or 1.0))
    if aspect >= box_width / box_height:
        image_width = box_width
        image_height = image_width / aspect
    else:
        image_height = box_height
        image_width = image_height * aspect
    image_rect = QRectF(
        content.center().x() - image_width / 2,
        content.top() + (available_height - image_height) / 2,
        image_width,
        image_height,
    )
    return image_rect, label_rect


class ThumbnailDelegate(QStyledItemDelegate):
    """Keep thumbnail images out of the dedicated page-number band."""

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        icon = QIcon(styled.icon)

        if index.data(THUMB_SPREAD_ROLE):
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(237, 246, 252))
            painter.drawRoundedRect(QRectF(option.rect).adjusted(
                1, 1, -1, -1), 6, 6)
            painter.restore()

        # Preserve the active style's hover, selection, focus and drag state.
        styled.icon = QIcon()
        styled.text = ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, styled, painter, styled.widget)

        aspect = float(index.data(Qt.UserRole + 1) or 1.0)
        view = self.parent()
        image_rect, _label_rect = thumbnail_layout_rects(
            option.rect, view.iconSize(), aspect)

        painter.save()
        if not icon.isNull() and not image_rect.isEmpty():
            icon.paint(painter, image_rect.toRect(), Qt.AlignCenter)
        painter.restore()


def qimage_from_render(w, h, stride, samples, device_pixel_ratio=1.0):
    """core.Document.render() 결과를 QImage로.

    copy()가 필요한 이유: samples는 PyMuPDF가 소유한 버퍼라 pixmap이
    해제되면 사라진다. QImage는 기본적으로 버퍼를 참조만 하므로 복사본을
    쥐고 있어야 나중에 그릴 때 깨지지 않는다.
    """
    image = QImage(samples, w, h, stride, QImage.Format_RGB888).copy()
    image.setDevicePixelRatio(max(1.0, float(device_pixel_ratio)))
    return image


class PageCanvas(QWidget):
    """페이지 비트맵 + 선택/검색 하이라이트 오버레이.

    오버레이 좌표는 전부 PDF 좌표계(zoom=1)로 저장한다 — 줌이 바뀌어도
    그릴 때만 배율을 곱하면 되므로 하이라이트가 그대로 유지된다.
    """

    drag_selected = pyqtSignal(QPointF, QPointF)  # 드래그 시작/현재 (PDF 좌표)
    drag_finished = pyqtSignal(QPointF, QPointF)
    selection_cleared = pyqtSignal()
    word_picked = pyqtSignal(QPointF)   # 더블클릭 지점 (PDF 좌표)
    clicked = pyqtSignal(QPointF)       # 드래그 없는 단순 클릭 (메모 배치/열기)
    ctrl_clicked = pyqtSignal(QPointF)  # 링크 열기용 Ctrl+단순 클릭
    context_requested = pyqtSignal(QPointF, object)  # (PDF 좌표, 전역 좌표)
    hovered = pyqtSignal(QPointF, object)  # 마우스 이동 (메모 툴팁용)
    pan_requested = pyqtSignal(QPoint)  # 손 도구 드래그의 화면 좌표 이동량
    page_activated = pyqtSignal(int)    # 두 장 보기에서 조작 대상 페이지 변경

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = None
        self._pages = []  # (page index, QPixmap, logical QRectF)
        self._active_page = 0
        self.zoom = 1.0
        self._sel_rects = []
        self._search_rects = []
        self._search_cur = None
        self._edit_boxes = []
        self._drag_start = None
        self._dragged = False
        self._interaction_mode = "select"
        self._pan_last_global = None
        self.setCursor(Qt.IBeamCursor)
        self.setMouseTracking(True)  # 버튼 안 눌러도 hovered가 오도록

    # --- 표시 내용 ----------------------------------------------------

    def set_image(self, img, zoom):
        self.set_images([(0, img)], zoom, 0)

    def set_images(self, images, zoom, active_page):
        """Display one or two page images with independent page coordinates."""
        self.zoom = zoom
        self._active_page = active_page
        self._pages = []
        left = 0.0
        max_height = 0.0
        gap = 16.0
        for page, image in images:
            pixmap = QPixmap.fromImage(image)
            ratio = max(1.0, pixmap.devicePixelRatio())
            width = pixmap.width() / ratio
            height = pixmap.height() / ratio
            rect = QRectF(left, 0.0, width, height)
            self._pages.append((page, pixmap, rect))
            left += width + gap
            max_height = max(max_height, height)
        self._pix = self._pages[0][1] if self._pages else None
        total_width = max(0.0, left - gap) if self._pages else 0.0
        self.resize(QSize(round(total_width), round(max_height)))
        self.update()

    def clear(self):
        self._pix = None
        self._pages = []
        self._sel_rects = []
        self._search_rects = []
        self._search_cur = None
        self._edit_boxes = []
        self._drag_start = None
        self._pan_last_global = None
        self.resize(QSize(0, 0))
        self.refresh_cursor()
        self.update()

    def set_selection(self, rects):
        self._sel_rects = rects
        self.update()

    def set_search(self, rects, current=None):
        self._search_rects = rects
        self._search_cur = current
        self.update()

    def set_edit_boxes(self, rects):
        self._edit_boxes = rects
        self.update()

    @property
    def interaction_mode(self):
        return self._interaction_mode

    def set_interaction_mode(self, mode):
        if mode not in ("select", "hand"):
            raise ValueError("알 수 없는 상호작용 모드: %s" % mode)
        self._interaction_mode = mode
        self._drag_start = None
        self._pan_last_global = None
        self.refresh_cursor()

    def refresh_cursor(self):
        self.setCursor(
            Qt.OpenHandCursor if self._interaction_mode == "hand"
            else Qt.IBeamCursor)

    def paintEvent(self, _ev):
        if self._pix is None:
            return
        p = QPainter(self)
        # 분수 DPI/배율에서 물리 픽셀과 논리 픽셀의 경계가 어긋나더라도
        # 최근접 픽셀 확대처럼 계단지지 않도록 부드럽게 보간한다.
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for _page, pixmap, rect in self._pages:
            p.drawPixmap(round(rect.left()), round(rect.top()), pixmap)
        self.paint_overlays(p)
        p.end()

    def paint_overlays(self, p, *, zoom=None, origin=None):
        """Paint PDF-coordinate overlays on the Qt fallback surface."""
        p.setPen(Qt.NoPen)
        z = self.zoom if zoom is None else zoom
        origin = self.active_page_rect().topLeft() if origin is None else origin
        for rects, color in ((self._search_rects, SEARCH_COLOR),
                             (self._sel_rects, SEL_COLOR)):
            p.setBrush(color)
            for r in rects:
                p.drawRect(QRectF(origin.x() + r.x() * z,
                                  origin.y() + r.y() * z,
                                  r.width() * z, r.height() * z))
        if self._search_cur is not None:
            r = self._search_cur
            p.setBrush(SEARCH_CUR_COLOR)
            p.drawRect(QRectF(origin.x() + r.x() * z,
                              origin.y() + r.y() * z,
                              r.width() * z, r.height() * z))
        # 편집 가능한 span은 채우지 않고 테두리만 그린다(글자를 가리지 않게)
        if self._edit_boxes:
            p.setBrush(Qt.NoBrush)
            p.setPen(EDIT_BOX_COLOR)
            for r in self._edit_boxes:
                p.drawRect(QRectF(origin.x() + r.x() * z,
                                  origin.y() + r.y() * z,
                                  r.width() * z, r.height() * z))

    # --- 마우스 → PDF 좌표 --------------------------------------------

    def active_page_rect(self):
        for page, _pixmap, rect in self._pages:
            if page == self._active_page:
                return QRectF(rect)
        if self.width() > 0 and self.height() > 0:
            return QRectF(0, 0, self.width(), self.height())
        return QRectF()

    def _page_point(self, pos):
        point = QPointF(pos)
        for page, _pixmap, rect in self._pages:
            if rect.contains(point):
                return page, QPointF(
                    (point.x() - rect.left()) / self.zoom,
                    (point.y() - rect.top()) / self.zoom)
        return None

    def _activate_at(self, pos):
        target = self._page_point(pos)
        if target is None:
            return None
        page, point = target
        if page != self._active_page:
            self._active_page = page
            self.page_activated.emit(page)
        return point

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._pix is not None:
            point = self._activate_at(ev.pos())
            if point is None:
                return
            if (self._interaction_mode == "hand" and
                    not (ev.modifiers() & Qt.ControlModifier)):
                self._pan_last_global = ev.globalPos()
                self.setCursor(Qt.ClosedHandCursor)
                ev.accept()
                return
            self._drag_start = point
            self._dragged = False
            self.selection_cleared.emit()

    def mouseMoveEvent(self, ev):
        if self._pan_last_global is not None:
            current = ev.globalPos()
            self.pan_requested.emit(current - self._pan_last_global)
            self._pan_last_global = current
        elif self._drag_start is not None:
            target = self._page_point(ev.pos())
            if target is not None and target[0] == self._active_page:
                self._dragged = True
                self.drag_selected.emit(self._drag_start, target[1])
        elif self._pix is not None:
            target = self._page_point(ev.pos())
            if target is not None and target[0] == self._active_page:
                self.hovered.emit(target[1], ev.globalPos())

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if self._pan_last_global is not None:
                self._pan_last_global = None
                self.refresh_cursor()
                ev.accept()
                return
            # 드래그 없이 눌렀다 뗀 것만 '클릭' — 선택 드래그와 구분한다.
            if self._drag_start is not None and self._dragged:
                target = self._page_point(ev.pos())
                start = self._drag_start
                self._drag_start = None
                if target is not None and target[0] == self._active_page:
                    self.drag_finished.emit(start, target[1])
            if self._drag_start is not None and not self._dragged:
                target = self._page_point(ev.pos())
                if target is not None and target[0] == self._active_page:
                    if ev.modifiers() & Qt.ControlModifier:
                        self.ctrl_clicked.emit(target[1])
                    else:
                        self.clicked.emit(target[1])
            self._drag_start = None

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._pix is not None and \
                self._interaction_mode == "select":
            point = self._activate_at(ev.pos())
            if point is not None:
                self.word_picked.emit(point)

    def contextMenuEvent(self, ev):
        if self._pix is not None:
            point = self._activate_at(ev.pos())
            if point is not None:
                self.context_requested.emit(point, ev.globalPos())


class PageView(QScrollArea):
    """PageCanvas를 감싸는 스크롤 영역. 줌은 Ctrl+휠.

    setWidgetResizable(False)여야 한다 — True면 스크롤 영역이 캔버스
    크기를 뷰포트에 맞춰버려서, 확대 시 이미지가 잘리고 스크롤바가 안
    생긴다. 크기는 캔버스가 이미지에 맞춰 스스로 정한다.
    """

    zoom_changed = pyqtSignal(float)
    page_flip = pyqtSignal(int)  # +1 다음 장, -1 이전 장
    viewport_changed = pyqtSignal()

    ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
    # 마우스 휠 한 칸 = 120. 트랙패드는 잘게 쪼개 보내므로 누적해서 이 값을
    # 넘을 때만 페이지를 넘긴다(안 그러면 트랙패드에서 몇 장씩 훌쩍 넘어감).
    FLIP_THRESHOLD = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("documentViewport")
        self.viewport().setObjectName("documentViewportSurface")
        self.canvas = PageCanvas()
        self.setWidget(self.canvas)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        self.zoom = 1.0
        self._flip_accum = 0
        self.canvas.pan_requested.connect(self._pan_canvas)
        self.horizontalScrollBar().valueChanged.connect(
            lambda _value: self.viewport_changed.emit())
        self.verticalScrollBar().valueChanged.connect(
            lambda _value: self.viewport_changed.emit())

    def set_interaction_mode(self, mode):
        self.canvas.set_interaction_mode(mode)

    def _pan_canvas(self, delta):
        """종이를 끌어가는 방향으로 보이도록 스크롤 값은 반대로 움직인다."""
        hbar = self.horizontalScrollBar()
        vbar = self.verticalScrollBar()
        hbar.setValue(hbar.value() - delta.x())
        vbar.setValue(vbar.value() - delta.y())

    def set_image(self, img):
        self.canvas.set_image(img, self.zoom)
        self.viewport_changed.emit()

    def set_images(self, images, active_page):
        self.canvas.set_images(images, self.zoom, active_page)
        self.viewport_changed.emit()

    def clear(self):
        self.canvas.clear()
        self.viewport_changed.emit()

    def visible_page_rect(self):
        """현재 뷰포트가 차지하는 페이지 비율(0~1 좌표)을 반환한다."""
        page = self.canvas.active_page_rect()
        canvas = self.canvas.size()
        viewport = self.viewport().size()
        if page.isEmpty() or canvas.width() <= 0 or canvas.height() <= 0:
            return None
        visible = QRectF(
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
            viewport.width(), viewport.height())
        intersection = page.intersected(visible)
        if intersection.isEmpty():
            return None
        x = max(0.0, (intersection.left() - page.left()) / page.width())
        y = max(0.0, (intersection.top() - page.top()) / page.height())
        width = min(1.0, intersection.width() / page.width())
        height = min(1.0, intersection.height() / page.height())
        rect = QRectF(x, y, min(1.0, width), min(1.0, height))
        if rect.width() >= 0.999 and rect.height() >= 0.999:
            return None
        return rect

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()

    def ensure_rect_visible(self, rect):
        """PDF 좌표 rect가 보이도록 스크롤."""
        z = self.zoom
        origin = self.canvas.active_page_rect().topLeft()
        cx = int(origin.x() + (rect.x() + rect.width() / 2) * z)
        cy = int(origin.y() + (rect.y() + rect.height() / 2) * z)
        self.ensureVisible(cx, cy, 120, 120)

    def center_on_page_fraction(self, point):
        """0~1 페이지 좌표의 지점이 뷰포트 중앙에 오도록 이동한다."""
        page = self.canvas.active_page_rect()
        viewport = self.viewport().size()
        if page.isEmpty():
            return
        x = max(0.0, min(1.0, float(point.x())))
        y = max(0.0, min(1.0, float(point.y())))
        self.horizontalScrollBar().setValue(
            round(page.left() + x * page.width() - viewport.width() / 2))
        self.verticalScrollBar().setValue(
            round(page.top() + y * page.height() - viewport.height() / 2))
        self.viewport_changed.emit()

    def wheelEvent(self, ev):
        # Ctrl+휠은 큰 단계, Alt+휠은 1% 미세 단계 줌.
        if ev.modifiers() & Qt.ControlModifier:
            step = 1.25 if ev.angleDelta().y() > 0 else 1 / 1.25
            new = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self.zoom * step))
            if new != self.zoom:
                self.zoom = new
                self.zoom_changed.emit(new)
            ev.accept()
            return
        if ev.modifiers() & Qt.AltModifier:
            step = 0.01 if ev.angleDelta().y() > 0 else -0.01
            new = round(max(
                self.ZOOM_MIN, min(self.ZOOM_MAX, self.zoom + step)) * 100
            ) / 100.0
            if new != self.zoom:
                self.zoom = new
                self.zoom_changed.emit(new)
            ev.accept()
            return

        dy = ev.angleDelta().y()
        bar = self.verticalScrollBar()
        at_top = bar.value() <= bar.minimum()
        at_bottom = bar.value() >= bar.maximum()

        # 페이지가 스크롤 여지가 있으면(확대 상태) 먼저 그 방향으로 스크롤하고,
        # 끝(위/아래)에 닿아 있을 때만 페이지를 넘긴다. 확대 안 된 상태는
        # min==max라 at_top·at_bottom이 둘 다 참이므로 바로 넘어간다.
        if (dy < 0 and at_bottom) or (dy > 0 and at_top):
            # dy<0(아래로) → 다음 장, dy>0(위로) → 이전 장. 부호대로 누적.
            self._flip_accum += dy
            if self._flip_accum <= -self.FLIP_THRESHOLD:
                self.page_flip.emit(1)
                self._flip_accum = 0
            elif self._flip_accum >= self.FLIP_THRESHOLD:
                self.page_flip.emit(-1)
                self._flip_accum = 0
            ev.accept()
        else:
            self._flip_accum = 0  # 도중에 방향을 틀면 누적 초기화
            super().wheelEvent(ev)

    def reset_flip(self):
        """페이지가 바뀌면 누적 초기화 — 다음 장에서 곧바로 또 넘어가지 않게."""
        self._flip_accum = 0


class ThumbList(QListWidget):
    """썸네일 사이드바. 렌더는 하지 않고 자리만 잡아둔다 — 실제 그림은
    ViewerMixin이 화면에 보이는 항목만 채운다(레이지 렌더, 설계 §3.1).

    일반 문서 화면에서는 탐색만 담당한다. 페이지 순서 변경은 선택·삽입 위치를
    명확히 확인할 수 있는 페이지 구성 화면에서만 제공한다."""

    page_selected = pyqtSignal(int)
    page_position_requested = pyqtSignal(int, QPointF)
    thumbnail_width_changed = pyqtSignal(int)

    # 뷰포트 크기를 모를 때(레이아웃 전) 렌더할 최대 항목 수 — 여기서
    # count-1까지 그려버리면 대용량 PDF에서 전 페이지를 렌더하게 된다.
    FALLBACK_WINDOW = 20

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rendered_rows = set()
        self.setObjectName("thumbnailRail")
        self.setMinimumWidth(96)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)
        self.setDragEnabled(False)
        self.setAcceptDrops(False)
        self.setDropIndicatorShown(False)
        self.setMouseTracking(True)
        self.currentRowChanged.connect(self._on_row)
        self._navigation_press = None
        self._marker_dragging = False
        self._marker_drag_offset = QPointF()
        self._viewport_page = -1
        self._viewport_rect = None
        self._spread_rows = set()
        self._thumb_width = 0
        self._apply_responsive_size()

    def _on_row(self, row):
        if row >= 0:
            self.page_selected.emit(row)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            marker = self._viewport_marker_rect()
            if not marker.isEmpty() and marker.contains(QPointF(event.pos())):
                image_rect = self._thumbnail_image_rect(self._viewport_page)
                self._marker_dragging = True
                self._navigation_press = None
                self._marker_drag_offset = QPointF(
                    (event.pos().x() - marker.left()) / image_rect.width(),
                    (event.pos().y() - marker.top()) / image_rect.height(),
                )
                self.setCursor(Qt.ClosedHandCursor)
                event.accept()
                return
            self._navigation_press = QPoint(event.pos())
        else:
            self._navigation_press = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._marker_dragging:
            target = self._marker_drag_target(event.pos())
            if target is not None:
                self.page_position_requested.emit(self._viewport_page, target)
            event.accept()
            return
        if self._navigation_press is not None and (
                event.pos() - self._navigation_press
        ).manhattanLength() >= QApplication.startDragDistance():
            self._navigation_press = None
        marker = self._viewport_marker_rect()
        self.setCursor(
            Qt.OpenHandCursor
            if not marker.isEmpty() and marker.contains(QPointF(event.pos()))
            else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._marker_dragging:
            target = self._marker_drag_target(event.pos())
            self._marker_dragging = False
            if target is not None:
                self.page_position_requested.emit(self._viewport_page, target)
            marker = self._viewport_marker_rect()
            self.setCursor(
                Qt.OpenHandCursor
                if marker.contains(QPointF(event.pos()))
                else Qt.ArrowCursor)
            event.accept()
            return
        navigation_press = self._navigation_press
        self._navigation_press = None
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton or navigation_press is None:
            return
        target = self.thumbnail_point_at(event.pos())
        if target is not None:
            row, point = target
            self.page_position_requested.emit(row, point)

    def leaveEvent(self, event):
        if not self._marker_dragging:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def reset_pages(self, count):
        """페이지 수만큼 빈 항목 생성 — 아이콘은 나중에 채워진다."""
        self.clear()
        self._rendered_rows.clear()
        self._spread_rows.clear()
        for i in range(count):
            it = QListWidgetItem("%d" % (i + 1))
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            # 아직 렌더되지 않은 항목도 완성된 썸네일과 같은 높이를 가져야
            # 전체 스크롤 범위와 보이는 행 계산이 중간에서 바뀌지 않는다.
            it.setSizeHint(QSize(
                self._thumb_width + 16,
                self.iconSize().height() + THUMB_ITEM_EXTRA_H))
            it.setData(Qt.UserRole, False)  # 렌더 완료 여부
            it.setData(Qt.UserRole + 1, 1.0)  # 페이지 가로/세로 비율
            it.setData(THUMB_SPREAD_ROLE, False)
            self.addItem(it)

    def set_spread_pages(self, pages):
        """Highlight every thumbnail currently visible in the page spread."""
        rows = {int(page) for page in pages if 0 <= int(page) < self.count()}
        if rows == self._spread_rows:
            return
        changed = self._spread_rows | rows
        self._spread_rows = rows
        for row in changed:
            item = self.item(row)
            if item is not None:
                item.setData(THUMB_SPREAD_ROLE, row in rows)
                self.viewport().update(self.visualItemRect(item))

    def visible_rows(self):
        """현재 화면에 보이는 항목 행 번호 — 이 범위만 렌더하면 된다."""
        if self.count() == 0:
            return []
        top = self._row_near_viewport_edge(from_top=True)
        bot = self._row_near_viewport_edge(from_top=False)
        if top < 0:
            top = 0
        if bot < 0:
            # 레이아웃 전이라 판단 불가 — 상한을 두지 않으면 전 페이지 렌더.
            bot = min(top + self.FALLBACK_WINDOW, self.count() - 1)
        return list(range(top, min(bot + 2, self.count())))

    def _row_near_viewport_edge(self, from_top):
        """항목 사이 여백을 피해 뷰포트 가장자리와 가까운 실제 행을 찾는다.

        QListWidget 항목은 좌우와 위아래에 여백이 있어 rect().topLeft()처럼
        x=0인 점을 indexAt에 넘기면 스크롤 위치와 무관하게 -1이 나온다.
        중앙 x에서 가장자리부터 안쪽으로 훑어 첫 항목을 찾는다.
        """
        rect = self.viewport().rect()
        x = rect.center().x()
        if from_top:
            positions = range(rect.top(), rect.bottom() + 1)
        else:
            positions = range(rect.bottom(), rect.top() - 1, -1)
        for y in positions:
            row = self.indexAt(QPoint(x, y)).row()
            if row >= 0:
                return row
        return -1

    def set_thumb(self, row, img, rendered_width=None):
        it = self.item(row)
        if it is not None:
            it.setIcon(QIcon(QPixmap.fromImage(img)))
            ratio = max(1.0, img.devicePixelRatio())
            logical_w = img.width() / ratio
            logical_h = img.height() / ratio
            it.setData(Qt.UserRole, rendered_width or round(logical_w))
            it.setData(Qt.UserRole + 1,
                       logical_w / logical_h if logical_h else 1.0)
            self._rendered_rows.add(row)

    def evict_thumbnails_outside(self, first, last):
        """Release rendered pixmaps outside the nearby thumbnail window."""
        for row in list(self._rendered_rows):
            if first <= row <= last:
                continue
            item = self.item(row)
            if item is not None:
                item.setIcon(QIcon())
                item.setData(Qt.UserRole, False)
            self._rendered_rows.discard(row)

    def is_rendered(self, row, width=None):
        it = self.item(row)
        if not it:
            return False
        rendered_width = it.data(Qt.UserRole)
        return bool(rendered_width) if width is None else rendered_width == width

    def invalidate(self, row):
        """페이지 내용이 바뀌었을 때(주석 추가 등) 다시 그리게 표시."""
        it = self.item(row)
        if it is not None:
            it.setData(Qt.UserRole, False)
            self._rendered_rows.discard(row)

    def thumbnail_width(self):
        return self._thumb_width or THUMB_W

    def _apply_responsive_size(self):
        viewport_width = self.viewport().width()
        width = max(THUMB_MIN_W, min(THUMB_MAX_W, viewport_width - 20))
        if width == self._thumb_width:
            return
        self._thumb_width = width
        height = round(width * 1.5)
        self.setIconSize(QSize(width, height))
        for row in range(self.count()):
            self.item(row).setSizeHint(
                QSize(width + 16, height + THUMB_ITEM_EXTRA_H))
        self.thumbnail_width_changed.emit(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_size()

    def set_viewport_marker(self, page, rect):
        if page == self._viewport_page and rect == self._viewport_rect:
            return
        old = self._viewport_page
        self._viewport_page = page
        self._viewport_rect = QRectF(rect) if rect is not None else None
        if old >= 0 and self.item(old):
            self.viewport().update(self.visualItemRect(self.item(old)))
        if page >= 0 and self.item(page):
            self.viewport().update(self.visualItemRect(self.item(page)))

    def _thumbnail_image_rect(self, row):
        """항목 안에서 실제 페이지 그림이 표시되는 정확한 사각형."""
        item = self.item(row)
        if item is None or item.icon().isNull():
            return QRectF()
        item_rect = QRectF(self.visualItemRect(item))
        if item_rect.isEmpty():
            return QRectF()
        return thumbnail_layout_rects(
            item_rect, self.iconSize(), item.data(Qt.UserRole + 1))[0]

    def _thumbnail_label_rect(self, row):
        """Return the dedicated page-number band used by the delegate."""
        item = self.item(row)
        if item is None:
            return QRectF()
        item_rect = QRectF(self.visualItemRect(item))
        if item_rect.isEmpty():
            return QRectF()
        return thumbnail_layout_rects(
            item_rect, self.iconSize(), item.data(Qt.UserRole + 1))[1]

    def thumbnail_point_at(self, pos):
        """썸네일 클릭 위치를 (행, 0~1 페이지 좌표)로 변환한다."""
        item = self.itemAt(pos)
        if item is None:
            return None
        row = self.row(item)
        image_rect = self._thumbnail_image_rect(row)
        point = QPointF(pos)
        if image_rect.isEmpty() or not image_rect.contains(point):
            return None
        return row, QPointF(
            (point.x() - image_rect.left()) / image_rect.width(),
            (point.y() - image_rect.top()) / image_rect.height(),
        )

    def _viewport_marker_rect(self):
        """Return the visible blue viewport marker in thumbnail coordinates."""
        if self._viewport_rect is None or self._viewport_page < 0:
            return QRectF()
        image_rect = self._thumbnail_image_rect(self._viewport_page)
        if image_rect.isEmpty():
            return QRectF()
        return QRectF(
            image_rect.left() + self._viewport_rect.x() * image_rect.width(),
            image_rect.top() + self._viewport_rect.y() * image_rect.height(),
            self._viewport_rect.width() * image_rect.width(),
            self._viewport_rect.height() * image_rect.height())

    def _marker_drag_target(self, pos):
        """Convert a dragged marker position to the page point to center."""
        if self._viewport_rect is None or self._viewport_page < 0:
            return None
        image_rect = self._thumbnail_image_rect(self._viewport_page)
        if image_rect.isEmpty():
            return None
        point = QPointF(
            (pos.x() - image_rect.left()) / image_rect.width(),
            (pos.y() - image_rect.top()) / image_rect.height())
        width = min(1.0, max(0.0, self._viewport_rect.width()))
        height = min(1.0, max(0.0, self._viewport_rect.height()))
        left = max(0.0, min(1.0 - width,
                           point.x() - self._marker_drag_offset.x()))
        top = max(0.0, min(1.0 - height,
                          point.y() - self._marker_drag_offset.y()))
        return QPointF(left + width / 2, top + height / 2)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setPen(self.palette().color(QPalette.Text))
        for row in self.visible_rows():
            item = self.item(row)
            if item is None:
                continue
            label_rect = self._thumbnail_label_rect(row)
            if label_rect.intersects(QRectF(self.viewport().rect())):
                painter.drawText(label_rect, Qt.AlignCenter, item.text())
        painter.end()

        if self._viewport_rect is None or self._viewport_page < 0:
            return
        item = self.item(self._viewport_page)
        if item is None or item.icon().isNull():
            return
        item_rect = self.visualItemRect(item)
        if not item_rect.intersects(self.viewport().rect()):
            return
        marker = self._viewport_marker_rect()
        if marker.isEmpty():
            return
        painter = QPainter(self.viewport())
        painter.setBrush(QColor(0, 120, 215, 45))
        painter.setPen(QPen(QColor(0, 100, 210), 2))
        painter.drawRect(marker)
        painter.end()
