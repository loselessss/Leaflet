"""Window-local closed-tab history and lossless tab separation."""
from collections import deque

from PyQt5.QtCore import QPoint, QTimer
from PyQt5.QtWidgets import QAction, QApplication

from .i18n import localize


class TabLifecycleMixin:
    def _init_tab_lifecycle(self):
        self._closed_tabs = deque(maxlen=20)
        self._reopening_tab = False
        self._reopen_tab_action = QAction(
            localize("Reopen closed tab", "닫은 탭 다시 열기"), self)
        self._reopen_tab_action.setShortcut("Ctrl+Shift+T")
        self._reopen_tab_action.triggered.connect(self.reopen_closed_tab)
        self.addAction(self._reopen_tab_action)
        self._update_reopen_action()

    def _update_reopen_action(self):
        self._reopen_tab_action.setEnabled(
            bool(self._closed_tabs) and not self._reopening_tab)

    def _remember_closed_tab(self, tab):
        if tab.doc is not None and tab.doc.path:
            self._closed_tabs.append((str(tab.doc.path), tab.capture_view_state()))
            self._update_reopen_action()

    def reopen_closed_tab(self):
        if not self._closed_tabs or self._reopening_tab:
            return
        entry = self._closed_tabs[-1]
        path, state = entry
        existing = self._find_open_tab(path)
        if existing is not None:
            self.open_in_tab(path)
            self._closed_tabs.pop()
            self._update_reopen_action()
            return
        self._reopening_tab = True
        self._update_reopen_action()
        tab = self.open_in_tab(path)
        self._reopen_loading_tab = tab
        tab._pending_view_state = dict(state)

        def loaded(success):
            tab.load_finished.disconnect(loaded)
            self._reopening_tab = False
            self._reopen_loading_tab = None
            # A failed open (including a cancelled password prompt) is retryable.
            if success:
                for index, candidate in enumerate(self._closed_tabs):
                    if candidate is entry:
                        del self._closed_tabs[index]
                        break
            self._update_reopen_action()

        tab.load_finished.connect(loaded)

    def _cancel_pending_reopen(self, tab):
        if getattr(self, "_reopen_loading_tab", None) is tab:
            # Closing before the deferred loader runs must not disable the
            # shortcut forever. The original history entry remains retryable.
            tab.load_finished.emit(False)

    def detach_tab_at_drop(self, tab, position, hotspot):
        from .app import AppWindow
        for window in QApplication.topLevelWidgets():
            if isinstance(window, AppWindow) and window.isVisible() and \
                    window.frameGeometry().contains(position):
                return
        return self.detach_tab(tab, position, hotspot)

    def detach_tab(self, tab, position=None, hotspot=None):
        if (self._tabs.indexOf(tab) < 0 or tab.doc is None or
                tab is self._presentation_tab):
            return
        state = tab.capture_view_state()
        destination = self.new_window()
        size = self.normalGeometry().size() if self.isMaximized() else self.size()
        destination.resize(size)
        if not destination._adopt_tab(self, tab, 0):
            destination.close()
            return
        tab._restore_scroll(state)
        QTimer.singleShot(0, lambda: tab._restore_scroll(state)
                          if tab._shell is destination else None)
        if position is not None:
            bar = destination._tabs.tabBar()
            origin = bar.mapTo(destination, QPoint(0, 0))
            point = position - origin - (hotspot or QPoint())
            screen = QApplication.screenAt(position) or destination.screen()
            if screen is not None:
                available = screen.availableGeometry()
                point.setX(max(available.left(), min(point.x(),
                    max(available.left(), available.right() - destination.width() + 1))))
                point.setY(max(available.top(), min(point.y(),
                    max(available.top(), available.bottom() - destination.height() + 1))))
            destination.move(point)
        return destination
