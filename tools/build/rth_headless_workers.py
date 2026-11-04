"""Run before PyInstaller's Qt hook: headless jobs must not load QtCore."""
import sys

if any(flag in sys.argv for flag in (
        "--pdf-layout-worker", "--ocr-render-worker", "--gpu-scene-worker")):
    # The standard hook creates embedded qt.conf by importing QtCore, even
    # before our headless entry-point branch. ORT must remain isolated from it.
    from _pyi_rth_utils import qt

    def _skip_qt_conf(*args, **kwargs):
        pass

    qt.create_embedded_qt_conf = _skip_qt_conf
