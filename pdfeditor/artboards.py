"""Editor artboard overview: PDF-sized boards and bounded visible previews.

Board positions belong to the view, never to PDF page coordinates or page order.
The existing editor owns all document edits and undo/redo.
"""

from collections import OrderedDict
import math

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QTransform
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView

from .widgets import qimage_from_render

PREVIEW_CACHE_BYTES = 32 * 1024 * 1024
PREVIEW_MAX_PIXELS = 500_000
MAX_VISIBLE_PREVIEWS = 64


class _Board(QGraphicsItem):
    def __init__(self, view, page, size):
        super().__init__()
        self.view, self.page = view, page
        self.rect = QRectF(0, 0, *size)
        self.setFlag(QGraphicsItem.ItemIsFocusable)
        self.label = QGraphicsSimpleTextItem(self)
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.label.setFont(QFont("Segoe UI", 9))
        self.label.setBrush(QColor("#566270"))
        self.label.setPos(0, -28)
        self.label.setText("%d · %g × %g mm" % (
            page + 1, round(size[0] * 25.4 / 72, 1), round(size[1] * 25.4 / 72, 1)))

    def boundingRect(self):
        return self.rect.adjusted(-3, -3, 3, 3)

    def paint(self, painter, option, widget=None):
        painter.fillRect(self.rect, Qt.white)
        cached = self.view._previews.get(self.page)
        if cached is not None:
            painter.drawImage(self.rect, cached[1])
        selected = self.page == self.view.selected_page
        pen = QPen(QColor("#0876cf" if selected else "#b8bec6"), 2 if selected else 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect)


class ArtboardView(QGraphicsView):
    page_selected = pyqtSignal(int)
    page_activated = pyqtSignal(int)
    context_requested = pyqtSignal(int, object)
    zoom_changed = pyqtSignal(float)
    layout_changed = pyqtSignal()
    render_failed = pyqtSignal(str)
    ZOOM_MIN = .005
    ZOOM_MAX = 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorArtboardView")
        self.setScene(QGraphicsScene(self))
        self.setBackgroundBrush(QColor("#e7e9ec"))
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self._document = None
        self._generation = None
        self._boards = []
        self._previews = OrderedDict()
        self._cache_bytes = 0
        self.cache_limit = PREVIEW_CACHE_BYTES
        self._failed = set()
        self.selected_page = 0
        self.columns = 3
        self.zoom = 1.0
        self._camera_ready = False
        self._pan = None
        self._layout_drag = None
        self._space = False
        self.hand_mode = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_next)
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(lambda _value: self._schedule_render())

    def set_document(self, document, page=0, *, reset=False):
        identity = (id(document), getattr(document, "render_generation", None))
        if not reset and identity == self._generation:
            self.select_page(page)
            return
        new_document = document is not self._document
        positions = [board.pos() for board in self._boards]
        old_count = len(self._boards)
        self.stop_rendering()
        self._previews.clear()
        self._cache_bytes = 0
        self._failed.clear()
        self._layout_drag = None
        self._pan = None
        self.scene().clear()
        self._boards = []
        self._document, self._generation = document, identity
        if document is None:
            self._camera_ready = False
            self.scene().setSceneRect(QRectF())
            return
        for index in range(document.page_count):
            board = _Board(self, index, document.page_size(index))
            self.scene().addItem(board)
            self._boards.append(board)
        if new_document or old_count != len(self._boards):
            self._camera_ready = False
            self.arrange(self.columns)
        else:
            for board, position in zip(self._boards, positions):
                board.setPos(position)
            self._update_scene_rect()
        self.select_page(page)
        self._schedule_render()

    def arrange(self, columns):
        self.columns = max(1, min(8, int(columns)))
        widths = [0.0] * self.columns
        for index, board in enumerate(self._boards):
            column = index % self.columns
            widths[column] = max(widths[column], board.rect.width())
        lefts = [0.0]
        for width in widths[:-1]:
            lefts.append(lefts[-1] + width + 90)
        top = 0.0
        for first in range(0, len(self._boards), self.columns):
            row = self._boards[first:first + self.columns]
            for column, board in enumerate(row):
                board.setPos(lefts[column], top)
            top += max(board.rect.height() for board in row) + 110
        self._update_scene_rect()
        self._schedule_render()
        self.layout_changed.emit()

    def _update_scene_rect(self):
        bounds = self.scene().itemsBoundingRect()
        self.scene().setSceneRect(bounds.adjusted(-100, -100, 100, 100))

    def select_page(self, page, *, ensure_visible=False):
        if not self._boards:
            return
        old = self.selected_page
        self.selected_page = max(0, min(int(page), len(self._boards) - 1))
        for index in {old, self.selected_page}:
            if 0 <= index < len(self._boards):
                self._boards[index].update()
        if ensure_visible:
            self.ensureVisible(self._boards[self.selected_page], 30, 30)
        self._schedule_render()

    def _fit(self, rect):
        if rect.isEmpty():
            return
        available = self.viewport().size()
        scale = min(max(1, available.width() - 64) / rect.width(),
                    max(1, available.height() - 64) / rect.height())
        self.set_zoom(scale)
        self.centerOn(rect.center())
        self._camera_ready = True

    def fit_initial(self):
        if not self._boards:
            return
        first = self.selected_page - self.selected_page % self.columns
        bounds = QRectF()
        for board in self._boards[first:first + self.columns * 2]:
            bounds = bounds.united(board.sceneBoundingRect())
        self._fit(bounds.adjusted(-20, -45, 20, 20))

    def fit_all(self):
        if self._boards:
            self._fit(self.scene().itemsBoundingRect().adjusted(-20, -45, 20, 20))

    def fit_selected(self, *, width_only=False):
        if not self._boards:
            return
        rect = self._boards[self.selected_page].sceneBoundingRect()
        if width_only:
            self.set_zoom(max(1, self.viewport().width() - 64) / rect.width())
            self.centerOn(rect.center())
        else:
            self._fit(rect.adjusted(-20, -45, 20, 20))

    def set_zoom(self, zoom, anchor=None):
        zoom = float(zoom)
        if not math.isfinite(zoom):
            return
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if anchor is None:
            anchor = self.viewport().rect().center()
        before = self.mapToScene(anchor)
        self.zoom = zoom
        self.setTransform(QTransform.fromScale(zoom, zoom))
        delta = self.mapToScene(anchor) - before
        self.translate(delta.x(), delta.y())
        self.zoom_changed.emit(self.zoom)
        self._schedule_render(120)

    def visible_pages(self):
        pages = set()
        for item in self.items(self.viewport().rect()):
            while item.parentItem() is not None:
                item = item.parentItem()
            if isinstance(item, _Board):
                pages.add(item.page)
        center = self.mapToScene(self.viewport().rect().center())
        return sorted(pages, key=lambda page: (
            (self._boards[page].sceneBoundingRect().center() - center).manhattanLength()))[:MAX_VISIBLE_PREVIEWS]

    def _preview_request(self, page):
        rect = self._boards[page].rect
        longest = max(rect.width(), rect.height())
        desired = longest * self.zoom * max(1.0, self.devicePixelRatioF())
        tier = next((edge for edge in (160, 320, 640, 1000) if edge >= desired), 1000)
        scale = min(tier / max(1, longest),
                    math.sqrt(PREVIEW_MAX_PIXELS / max(1, rect.width() * rect.height())))
        return tier, scale

    def _schedule_render(self, delay=30):
        if getattr(self, "_document", None) is not None and self.isVisible():
            self._timer.start(delay)

    def _render_next(self):
        if self._document is None or not self.isVisible():
            return
        visible = self.visible_pages()
        # Keep only the nearest previews that fit as a working set. Otherwise
        # an overview of many pages would endlessly evict and rerender itself.
        budget = self.cache_limit
        working = []
        for page in visible:
            _tier, scale = self._preview_request(page)
            rect = self._boards[page].rect
            cached = self._previews.get(page)
            estimate = max(cached[2] if cached else 0,
                           4 * (math.ceil(rect.width() * scale) + 1) *
                           (math.ceil(rect.height() * scale) + 1))
            if estimate > budget:
                continue
            budget -= estimate
            working.append(page)
        for page in working:
            tier, scale = self._preview_request(page)
            cached = self._previews.get(page)
            if cached is not None and cached[0] >= tier:
                self._previews.move_to_end(page)
                continue
            if (page, tier) in self._failed:
                continue
            try:
                image = qimage_from_render(*self._document.render(page, scale))
                size = image.bytesPerLine() * image.height()
                if size > self.cache_limit:
                    self._failed.add((page, tier))
                    continue
                previous = self._previews.pop(page, None)
                if previous:
                    self._cache_bytes -= previous[2]
                while self._previews and self._cache_bytes + size > self.cache_limit:
                    evicted, entry = self._previews.popitem(last=False)
                    self._cache_bytes -= entry[2]
                    self._boards[evicted].update()
                self._previews[page] = (tier, image, size)
                self._cache_bytes += size
                self._boards[page].update()
            except Exception as error:
                self._failed.add((page, tier))
                self.render_failed.emit(str(error))
            self._schedule_render()
            return  # Yield between previews; never eagerly render every page.

    def stop_rendering(self):
        self._timer.stop()

    def hideEvent(self, event):
        self.stop_rendering()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._schedule_render()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.25 ** (event.angleDelta().y() / 120)), event.pos())
            event.accept()
        else:
            super().wheelEvent(event)

    def _board_at(self, position):
        item = self.itemAt(position)
        header = isinstance(item, QGraphicsSimpleTextItem)
        while item is not None and item.parentItem() is not None:
            item = item.parentItem()
        return (item, header) if isinstance(item, _Board) else (None, False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and
                                                (self._space or self.hand_mode)):
            self._pan = event.pos()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        board, header = self._board_at(event.pos())
        if board is not None and event.button() == Qt.LeftButton:
            self.select_page(board.page)
            self.page_selected.emit(board.page)
            if header:
                self._layout_drag = (board, self.mapToScene(event.pos()), board.pos())
            self.setFocus()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            delta = event.pos() - self._pan
            self._pan = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        elif self._layout_drag is not None:
            board, start, origin = self._layout_drag
            board.setPos(origin + self.mapToScene(event.pos()) - start)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan is not None or self._layout_drag is not None:
            moved = self._layout_drag is not None
            self._pan = self._layout_drag = None
            self.viewport().setCursor(Qt.OpenHandCursor if self.hand_mode or self._space else Qt.ArrowCursor)
            if moved:
                self._update_scene_rect()
                self.layout_changed.emit()
                self._schedule_render()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        board, _header = self._board_at(event.pos())
        if board is not None and event.button() == Qt.LeftButton:
            self._layout_drag = None
            self.select_page(board.page)
            self.page_activated.emit(board.page)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        board, _header = self._board_at(event.pos())
        if board is not None:
            self.select_page(board.page)
            self.page_selected.emit(board.page)
            self.context_requested.emit(board.page, event.globalPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space:
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
            if self._boards:
                self.page_activated.emit(self.selected_page)
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = {Qt.Key_Left: -1, Qt.Key_Right: 1,
                    Qt.Key_Up: -self.columns, Qt.Key_Down: self.columns}[key]
            self.select_page(self.selected_page + step, ensure_visible=True)
            self.page_selected.emit(self.selected_page)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(Qt.OpenHandCursor if self.hand_mode else Qt.ArrowCursor)
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._space = False
        self._pan = self._layout_drag = None
        self.viewport().setCursor(Qt.OpenHandCursor if self.hand_mode else Qt.ArrowCursor)
        super().focusOutEvent(event)
