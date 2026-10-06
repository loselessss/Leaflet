"""Drag documents between tab strips or tear them off into a new window."""
import json
import os
import tempfile
import uuid

from PyQt5.QtCore import QEvent, QMimeData, QObject, QPoint, QPointF, Qt, QTimer
from PyQt5.QtGui import QColor, QCursor, QDrag, QMouseEvent, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QMenu, QTabBar

from .i18n import localize


class DragReleaseState(QObject):
    """Distinguish a desktop release from cancelling the Windows OLE drag."""

    def __init__(self, parent):
        super().__init__(parent)
        self.cancelled = False
        self.released = False
        self._native_state = None
        if os.name == "nt":
            import ctypes
            self._native_state = ctypes.windll.user32.GetAsyncKeyState
            self._native_state.argtypes = [ctypes.c_int]
            self._native_state.restype = ctypes.c_short
            self._native_state(0x1B)  # Discard presses preceding this drag.
        self.application = QApplication.instance()
        self.application.installEventFilter(self)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancelled = True
        elif event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.released = True
        return False

    def poll(self):
        # Native OLE may consume Escape without delivering a Qt key event.
        if self._native_state is not None and self._native_state(0x1B) & 0x8001:
            self.cancelled = True

    def finish(self):
        self.poll()
        released = self.released
        if self._native_state is not None:
            released = not bool(self._native_state(0x01) & 0x8000)
        return released, self.cancelled

    def close(self):
        self.timer.stop()
        self.application.removeEventFilter(self)
        self.deleteLater()


_TAB_MIME = "application/x-spdf-tab"
_dragged_tabs = {}


def _decode_tab_drag(mime):
    if not mime.hasFormat(_TAB_MIME):
        return None
    try:
        return json.loads(bytes(mime.data(_TAB_MIME)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None


class TransferTabBar(QTabBar):
    """창 안 재정렬은 Qt에 맡기고, 탭 막대 밖으로 나가면 창 간 드래그한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._pressed_tab = None
        self._drop_index = None
        self._press_offset = QPoint()

    def contextMenuEvent(self, ev):
        index = self.tabAt(ev.pos())
        if index < 0:
            ev.ignore()
            return
        tab = self.window()._tabs.widget(index)
        actions = getattr(tab, "_tab_context_actions", ())
        if not actions:
            ev.ignore()
            return
        menu = QMenu(self)
        try:
            for action in actions:
                if action is None:
                    menu.addSeparator()
                else:
                    menu.addAction(action)
            menu.addSeparator()
            shell = self.window()
            detach = menu.addAction(localize("Move tab to new window", "탭을 새 창으로 분리"))
            detach.setEnabled(tab.doc is not None and tab is not shell._presentation_tab)
            detach.triggered.connect(lambda: shell.detach_tab(tab))
            menu.addAction(shell._reopen_tab_action)
            menu.exec_(ev.globalPos())
        finally:
            menu.deleteLater()
        ev.accept()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            i = self.tabAt(ev.pos())
            self._pressed_tab = self.window()._tabs.widget(i) if i >= 0 else None
            if i >= 0:
                self._press_offset = ev.pos() - self.tabRect(i).topLeft()
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        self._pressed_tab = None

    def mouseMoveEvent(self, ev):
        tab = self._pressed_tab
        if tab is not None and ev.buttons() & Qt.LeftButton and \
                not self.rect().adjusted(-10, -10, 10, 10).contains(ev.pos()):
            self._pressed_tab = None
            # End Qt's in-bar reorder before entering the native drag loop.
            release = QMouseEvent(QEvent.MouseButtonRelease, QPointF(ev.pos()),
                                  QPointF(ev.globalPos()), Qt.LeftButton,
                                  Qt.NoButton, ev.modifiers())
            super().mouseReleaseEvent(release)
            self._start_transfer(tab)
            return
        super().mouseMoveEvent(ev)

    def _start_transfer(self, tab):
        from .app import AppWindow
        shell = self.window()
        if not isinstance(shell, AppWindow) or shell._tabs.indexOf(tab) < 0 or \
                tab.doc is None or tab is shell._presentation_tab:
            return

        token = uuid.uuid4().hex
        snapshot_path = None
        if tab._dirty:
            try:
                fd, snapshot_path = tempfile.mkstemp(
                    prefix="spdf-tab-", suffix=".pdf")
                with os.fdopen(fd, "wb") as stream:
                    stream.write(tab.doc.snapshot())
            except Exception as e:
                if snapshot_path and os.path.exists(snapshot_path):
                    os.remove(snapshot_path)
                tab.statusBar().showMessage(
                    "탭 이동용 임시 저장에 실패했습니다: %s" % e, 5000)
                return

        payload = {
            "pid": os.getpid(),
            "token": token,
            "path": tab.doc.path,
            "dirty": bool(tab._dirty),
            "read_only": shell.read_only,
            "annotations_enabled": shell.annotations_enabled,
            "autosave_annotations": shell.autosave_annotations,
            "workspace_mode": shell.workspace_mode,
            "updates_enabled": shell.updates_enabled,
            "snapshot": snapshot_path,
        }
        mime = QMimeData()
        mime.setData(_TAB_MIME, json.dumps(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        i = shell._tabs.indexOf(tab)
        if i >= 0:
            drag.setPixmap(self.grab(self.tabRect(i)))
            drag.setHotSpot(self._press_offset)

        _dragged_tabs[token] = (shell, tab)
        self._local_drop_completed = False
        state = DragReleaseState(self)
        try:
            result = drag.exec_(Qt.MoveAction)
            released, cancelled = state.finish()
            if result == Qt.IgnoreAction and released and not cancelled:
                shell.detach_tab_at_drop(tab, QCursor.pos(), self._press_offset)
        finally:
            state.close()
            _dragged_tabs.pop(token, None)
            self._set_drop_index(None)
            drag.deleteLater()

        # 같은 프로세스면 dropEvent에서 이미 위젯을 떼어 대상 창에 붙인다.
        # 아직 원래 창에 남아 있으면 다른 Leaflet 프로세스가 경로를 받은 경우다.
        moved_to_external_process = result == Qt.MoveAction and \
            shell._tabs.indexOf(tab) >= 0 and tab._shell is shell and \
            not self._local_drop_completed
        if moved_to_external_process:
            shell._finish_external_tab_move(tab)
        elif snapshot_path and os.path.exists(snapshot_path):
            # 같은 프로세스 이동이나 취소에서는 임시본을 받을 프로세스가 없다.
            os.remove(snapshot_path)

    def dragEnterEvent(self, ev):
        if self._can_accept(ev.mimeData()):
            self._set_drop_index(self._drop_index_at(ev.pos()))
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            self._set_drop_index(None)
            ev.ignore()

    def dragMoveEvent(self, ev):
        if self._can_accept(ev.mimeData()):
            self._set_drop_index(self._drop_index_at(ev.pos()))
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            self._set_drop_index(None)
            ev.ignore()

    def dragLeaveEvent(self, ev):
        self._set_drop_index(None)
        ev.accept()

    def _drop_index_at(self, pos):
        rtl = self.layoutDirection() == Qt.RightToLeft
        for index in range(self.count()):
            center = self.tabRect(index).center().x()
            if (rtl and pos.x() > center) or (not rtl and pos.x() < center):
                return index
        return self.count()

    def _set_drop_index(self, index):
        if self._drop_index != index:
            self._drop_index = index
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_index is None:
            return
        rtl = self.layoutDirection() == Qt.RightToLeft
        if self.count() == 0:
            x = self.width() - 3 if rtl else 3
        elif self._drop_index < self.count():
            rect = self.tabRect(self._drop_index)
            x = rect.right() if rtl else rect.left()
        else:
            rect = self.tabRect(self.count() - 1)
            x = rect.left() if rtl else rect.right() + 1
        x = max(3, min(self.width() - 4, x))
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#0078d7"), 2))
        painter.drawLine(x, 3, x, self.height() - 4)

    def dropEvent(self, ev):
        self._set_drop_index(None)
        payload = _decode_tab_drag(ev.mimeData())
        if payload is None or not self._can_accept(ev.mimeData()):
            ev.ignore()
            return

        index = self._drop_index_at(ev.pos())

        if self.window()._receive_tab_drop(payload, index):
            if isinstance(ev.source(), TransferTabBar):
                # The source QDrag still owns the local transfer token.
                ev.source()._local_drop_completed = True
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            ev.ignore()

    def _can_accept(self, mime):
        payload = _decode_tab_drag(mime)
        if not payload or not payload.get("path"):
            return False
        shell = self.window()
        if payload.get("pid") == os.getpid():
            entry = _dragged_tabs.get(payload.get("token"))
            return entry is not None and shell.access_policy == entry[0].access_policy \
                and shell.workspace_mode == entry[0].workspace_mode \
                and shell.updates_enabled == entry[0].updates_enabled \
                and entry[1] is not entry[0]._presentation_tab
        policy = (bool(payload.get("read_only", False)),
                  bool(payload.get("annotations_enabled", True)),
                  bool(payload.get("autosave_annotations", True)))
        if policy != shell.access_policy or payload.get("workspace_mode") != shell.workspace_mode:
            return False
        if "updates_enabled" in payload and bool(payload["updates_enabled"]) != shell.updates_enabled:
            return False
        if not os.path.isfile(payload["path"]):
            return False
        if not payload.get("dirty"):
            return True
        snapshot = payload.get("snapshot")
        if not snapshot or not self._is_transfer_snapshot(snapshot):
            return False
        return self.window()._find_open_tab(payload["path"]) is None

    @staticmethod
    def _is_transfer_snapshot(path):
        try:
            full = os.path.abspath(path)
            return os.path.dirname(full) == os.path.abspath(tempfile.gettempdir()) \
                and os.path.basename(full).startswith("spdf-tab-") \
                and full.lower().endswith(".pdf") and os.path.isfile(full)
        except (TypeError, ValueError):
            return False
