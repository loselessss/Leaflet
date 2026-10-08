"""Test-only control of a real sPDF entry point. Never shipped/imported by app.

All destructive failure injection targets only this fixture's own PID. The
caller provides a temporary directory; user settings/documents are never used.
"""
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(os.environ["SPDF_PROCESS_TEST_DIR"]).resolve()
OWN = ROOT / str(os.getpid())
OWN.mkdir()
scratch = ROOT / "private-temp"
scratch.mkdir(exist_ok=True)
tempfile.tempdir = str(scratch)
if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
crash_log = open(OWN / "failure.log", "w")
faulthandler.enable(crash_log)


def fail_callback(kind, value, trace):
    traceback.print_exception(kind, value, trace, file=crash_log)
    crash_log.flush()
    os._exit(70)


sys.excepthook = fail_callback
os.environ["SPDF_UI_LANGUAGE"] = "en"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SPDF_DISABLE_GPU"] = "1"

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox
from pdfeditor import app, paths, settings

settings.PATH = str(ROOT / "settings.json")
settings._OLD_PATH = str(ROOT / "absent")
paths.user_data_dir = lambda: str(ROOT)
# Avoid modal UI in unattended tests; log unexpected application errors.
QMessageBox.critical = lambda *args: (OWN / "error.txt").write_text(str(args[1:]), encoding="utf-8")

shell = None
last_command = None
result = {}


def write_report(**extra):
    from pdfeditor.process_workspace import application_bridge
    bridge = application_bridge()
    tab = shell._tabs.currentWidget() if shell else None
    report = dict(pid=os.getpid(), mode=shell.workspace_mode if shell else None,
                  endpoint=bridge.endpoint, token=bridge.token,
                  updates=shell.updates_enabled if shell else None,
                  command=last_command, result=result,
                  document=bool(tab and tab.doc),
                  editor_dialog_loaded="pdfeditor.text_edit_dialog" in sys.modules,
                  organizer_loaded="pdfeditor.page_organizer" in sys.modules)
    if tab and tab.doc:
        report.update(path=tab.doc.path, page=tab.page_index, zoom=tab.view.zoom,
                      overview=tab.is_editor_overview(), dirty=tab._dirty,
                      text="".join(p.get_text() for p in tab.doc._doc),
                      recovery_session=str(tab._recovery.store.session) if tab._recovery.store else None)
    report.update(extra)
    temporary = OWN / "report.tmp"
    temporary.write_text(json.dumps(report), encoding="utf-8")
    for attempt in range(50):
        try:
            os.replace(temporary, OWN / "report.json")
            break
        except PermissionError:
            time.sleep(0.002)  # Test observer may briefly hold a Windows handle.


def pause(phase):
    write_report(phase=phase)
    while True:
        time.sleep(0.05)  # Deliberately hangs only this test process.


def tick():
    global last_command, result
    command_file = OWN / "command.json"
    if not command_file.exists():
        write_report()
        return
    command = json.loads(command_file.read_text(encoding="utf-8"))
    command_file.unlink()
    last_command = command["id"]
    op = command["op"]
    tab = shell._tabs.currentWidget()
    result = {}
    if op == "edit":
        tab.apply_document_change(lambda: tab.doc.add_text_box(1, (40, 100), "Process edit"))
    elif op == "save":
        result["saved"] = tab.save()
    elif op == "save_as":
        with patch("pdfeditor.annots.QFileDialog.getSaveFileName", return_value=(str(ROOT / "copy.pdf"), "PDF")), \
                patch("pdfeditor.annots.choose_save_options", return_value=(False, False)):
            result["saved"] = tab.save_as_dialog()
    elif op == "checkpoint":
        tab._recovery.checkpoint()
    elif op == "open_reader":
        child = shell.open_reader()
        result["child_pid"] = child.pid
    elif op == "close":
        tab._dirty = False
        write_report(closing=True)
        shell.close()
        return
    elif op == "hang":
        pause("hang")
    elif op == "crash":
        # Native access violation, not a Python exception. Error dialogs are
        # suppressed above, with faulthandler evidence in this PID's folder.
        crash_log.write("Injecting native access violation in test-owned PID %s\n" % os.getpid())
        faulthandler.dump_traceback(file=crash_log)
        crash_log.flush()
        faulthandler._sigsegv()
    elif op == "save_phase":
        phase = command["phase"]
        import pdfeditor.save_transaction as transaction
        from contextlib import contextmanager
        real_lock, real_replace = transaction.destination_lock, os.replace
        @contextmanager
        def lock(path):
            with real_lock(path):
                if phase == "writer_lock":
                    pause(phase)
                yield
        def replace(source, destination):
            try:
                is_pdf = os.path.samefile(destination, ROOT / "source.pdf")
            except OSError:
                is_pdf = (os.path.normcase(os.path.abspath(destination)) ==
                          os.path.normcase(os.path.abspath(ROOT / "source.pdf")))
            if is_pdf and phase == "before_replace":
                pause(phase)
            real_replace(source, destination)
            if is_pdf and phase == "after_replace":
                pause(phase)
        if phase == "before_save":
            pause(phase)
        with patch.object(transaction, "destination_lock", lock), patch("os.replace", replace):
            tab.save()
    write_report()


original_new_window = app.new_window


def test_window(*args, **kwargs):
    global shell
    application = QApplication.instance()
    application._spdf_recovery_prompted = True
    shell = original_new_window(*args, **kwargs)
    # Bypass unstable Qt DLL teardown only after actual closeEvent cleanup.
    application.aboutToQuit.connect(lambda: os._exit(0))
    timer = QTimer(application)
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    application._fixture_timer = timer
    return shell


app.new_window = test_window
from pdfeditor.__main__ import main
main()
