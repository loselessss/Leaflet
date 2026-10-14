"""Bounded view history and per-document reading positions."""

from PyQt5.QtCore import QTimer

from . import settings


class ViewHistory:
    def __init__(self, limit=100):
        self.limit = limit
        self.back = []
        self.forward = []

    def record(self, state):
        if not self.back or self.back[-1] != state:
            self.back.append(dict(state))
            del self.back[:-self.limit]
        self.forward.clear()

    def move(self, current, backwards=True):
        source, target = ((self.back, self.forward) if backwards else
                          (self.forward, self.back))
        if not source:
            return None
        target.append(dict(current))
        del target[:-self.limit]
        return source.pop()


class NavigationMixin:
    def _init_navigation(self):
        self._view_history = ViewHistory()
        self._view_ready = False
        self._restoring_view = False
        self._initial_reading_state = None
        self._position_timer = QTimer(self)
        self._position_timer.setSingleShot(True)
        self._position_timer.setInterval(1500)
        self._position_timer.timeout.connect(self.save_reading_position)

    def capture_view_state(self):
        if self.is_editor_overview():
            state = self._artboard_detail_state
            if state is not None and state["page"] == self.page_index:
                return dict(state)
            return {"page": self.page_index, "zoom": self.view.zoom,
                    "two_page": False, "horizontal": 0, "vertical": 0}
        hbar = self.view.horizontalScrollBar()
        vbar = self.view.verticalScrollBar()
        return {
            "page": self.page_index, "zoom": self.view.zoom,
            "two_page": self._two_page_mode,
            "horizontal": hbar.value() / max(1, hbar.maximum()),
            "vertical": vbar.value() / max(1, vbar.maximum()),
        }

    def remember_navigation(self):
        if self._view_ready and not self._restoring_view:
            self._view_history.record(self.capture_view_state())
            self._sync_navigation_actions()

    def clear_navigation_history(self):
        self._view_history = ViewHistory()
        self._sync_navigation_actions()

    def _sync_navigation_actions(self):
        for name, entries in (("_back_view_act", self._view_history.back),
                              ("_forward_view_act", self._view_history.forward)):
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(bool(entries))

    def navigate_history(self, backwards=True):
        if self.doc is None:
            return
        state = self._view_history.move(self.capture_view_state(), backwards)
        if state is not None:
            self.restore_view_state(state)
        self._sync_navigation_actions()

    def restore_view_state(self, state):
        if self.doc is None:
            return
        self._restoring_view = True
        try:
            if self.is_editor_overview():
                self.open_page_editor(int(state.get("page", 0)), edit_text=False)
            self._two_page_mode = bool(state.get("two_page", False))
            self._two_page_act.setChecked(self._two_page_mode)
            self.view.zoom = max(self.view.ZOOM_MIN, min(
                self.view.ZOOM_MAX, float(state.get("zoom", 1))))
            self._cache.clear()
            self.show_page(int(state.get("page", 0)))
            self._restore_scroll(state)
            document, page = self.doc, self.page_index
            QTimer.singleShot(0, lambda: self._restore_scroll(state)
                              if self.doc is document and
                              self.page_index == page else None)
        finally:
            self._restoring_view = False

    def _restore_scroll(self, state):
        for bar, key in ((self.view.horizontalScrollBar(), "horizontal"),
                         (self.view.verticalScrollBar(), "vertical")):
            fraction = max(0.0, min(1.0, float(state.get(key, 0))))
            bar.setValue(round(bar.maximum() * fraction))

    def schedule_reading_position(self):
        if self.doc is not None and self._view_ready:
            self._position_timer.start()

    def save_reading_position(self):
        if self.doc is None or not self._view_ready:
            return
        try:
            settings.set_reading_position(self.doc.path, self.capture_view_state())
        except OSError:
            pass  # A read-only settings folder must never prevent closing.
