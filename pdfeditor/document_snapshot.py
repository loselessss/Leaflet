"""Private, disk-backed input copies: never hold a reader handle on the source.

The copy retains encryption and consumes disk, not a whole-PDF RAM buffer.
Only immutable files cross the copy worker / GUI boundary; MuPDF stays on Qt.
"""
import os
import shutil
import tempfile
import atexit
import threading

_pending_cleanup = []
_cleanup_guard = threading.Lock()


def cleanup_snapshots():
    # A failed MuPDF open can retain its input handle through the exception's
    # traceback. Retry after the exception unwinds; never abort a Qt callback.
    with _cleanup_guard:
        pending = list(_pending_cleanup)
        _pending_cleanup.clear()
    for directory in pending:
        try:
            directory.cleanup()
        except OSError:
            with _cleanup_guard:
                _pending_cleanup.append(directory)


atexit.register(cleanup_snapshots)


def file_revision(path):
    try:
        stat = os.stat(path)
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]
    except FileNotFoundError:
        return None


class DocumentSnapshot:
    def __init__(self, source):
        self.directory = tempfile.TemporaryDirectory(prefix="spdf-document-")
        self.path = os.path.join(self.directory.name, "document.pdf")
        try:
            before = file_revision(source)
            if os.path.splitext(os.fspath(source))[1].lower() == ".eps":
                from .eps import convert_eps
                # Use a private input too: conversion may run in a worker while
                # the source is replaced by another application.
                eps_input = os.path.join(self.directory.name, "source.eps")
                shutil.copyfile(source, eps_input)
                convert_eps(eps_input, self.path)
                os.unlink(eps_input)
            else:
                shutil.copyfile(source, self.path)
            self.revision = file_revision(source)
            if before != self.revision:
                raise OSError("Document changed while copying; retry opening it.")
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            self.directory.cleanup()
        except OSError:
            with _cleanup_guard:
                if self.directory not in _pending_cleanup:
                    _pending_cleanup.append(self.directory)
