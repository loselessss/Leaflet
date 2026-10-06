"""Crash-released writer locks and atomic backups (no Qt dependency)."""
from contextlib import contextmanager
import os
import shutil
import tempfile


@contextmanager
def destination_lock(path):
    if os.name == "nt":
        # Exclusive handles cannot race with another opener. Windows removes
        # the sidecar atomically on close, including process termination.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel.CreateFileW
        create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                           wintypes.HANDLE)
        create.restype = wintypes.HANDLE
        close = kernel.CloseHandle
        close.argtypes = (wintypes.HANDLE,)
        close.restype = wintypes.BOOL
        # GENERIC_READ | GENERIC_WRITE | DELETE; OPEN_ALWAYS;
        # FILE_FLAG_DELETE_ON_CLOSE | FILE_ATTRIBUTE_NORMAL.
        handle = create(os.path.realpath(path) + ".spdf-save.lock",
                        0xC0010000, 0, None, 4, 0x04000080, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            close(handle)
        return
    # Keep the small lock inode: unlinking it permits two simultaneous owners.
    stream = open(os.path.realpath(path) + ".spdf-save.lock", "a+b")
    locked = False
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            stream.seek(0)
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def atomic_backup(path):
    fd, temporary = tempfile.mkstemp(prefix=".spdf-backup-", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "wb") as output, open(path, "rb") as source:
            shutil.copyfileobj(source, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path + ".bak")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def discard_backup(path):
    """Remove the transaction backup only after a successful save.

    A cleanup error must not turn an already completed save into a failure.
    In particular, a backup held open by another application is left intact.
    """
    try:
        os.unlink(os.fspath(path) + ".bak")
    except OSError:
        pass
