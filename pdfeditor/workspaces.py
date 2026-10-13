"""Standalone workspace policy. Embedded access remains explicitly opt-in."""
from .i18n import localize


def workspace_policy(mode, read_only, annotations_enabled):
    if mode not in (None, "reader", "editor"):
        raise ValueError("Unknown workspace mode: %s" % mode)
    if mode == "reader":
        return True, True
    if mode == "editor":
        if read_only:
            raise ValueError("An editor workspace cannot be read-only.")
        return False, True
    return bool(read_only), (not read_only if annotations_enabled is None
                             else bool(annotations_enabled))


class WindowWorkspaceMixin:
    @property
    def workspace_mode(self):
        return self._workspace_mode

    def workspace_title(self):
        from .meta import APP_NAME
        suffix = {"reader": localize("Reader", "읽기"),
                  "editor": None}.get(self.workspace_mode)
        return "%s — %s" % (APP_NAME, suffix) if suffix else APP_NAME

    def open_editor(self, source=None, recovery=False):
        if self.workspace_mode != "reader":
            return None
        if source is None:
            source = self._tabs.currentWidget()
        if not recovery and source is not None and not source.maybe_save():
            return None
        if not recovery and source is not None:
            source._workspace_handoff_revision = source._recovery.revision
        from .process_workspace import application_bridge
        try:
            return application_bridge().launch(
                self, source, recovery=recovery, handoff_source=not recovery)
        except OSError as error:
            self.statusBar().showMessage(str(error), 8000)
            return None

    def open_reader(self):
        if self.workspace_mode != "editor":
            return None
        source = self._tabs.currentWidget()
        if source is not None and not source.maybe_save():
            return None
        if source is not None:
            source._workspace_handoff_revision = source._recovery.revision
        from .process_workspace import application_bridge
        try:
            return application_bridge().launch(
                self, source, mode="reader", handoff_source=True)
        except OSError as error:
            self.statusBar().showMessage(str(error), 8000)
            return None

    def _complete_workspace_handoff(self, source):
        """Close only the source document after its peer opened successfully."""
        if source is None or self._tabs.indexOf(source) < 0:
            return
        if (source._dirty and source._recovery.revision !=
                getattr(source, "_workspace_handoff_revision", -1)):
            self.statusBar().showMessage(localize(
                "The source tab remains open because it has new unsaved changes.",
                "새로운 미저장 변경이 있어 원래 탭을 유지합니다."), 6000)
            return
        self._remove_tab(source)
        if self._tabs.count() == 0:
            # Let the open acknowledgement return before destroying the window
            # and possibly ending this process.
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, self.close)
