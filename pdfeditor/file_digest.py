"""Bounded background hashing of files; never access a MuPDF document here."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
import hashlib
import os
import threading


_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="leaflet-hash")


def revision(stat):
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _hash_file(path, expected, cancelled):
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            before = os.fstat(stream.fileno())
            # Windows stat/fstat can report different ctime semantics.
            # Compare descriptor size/mtime and verify path ctime separately.
            if revision(before)[:2] != expected[:2] or revision(os.stat(path)) != expected:
                return None
            while not cancelled.is_set():
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    after = os.fstat(stream.fileno())
                    current = os.stat(path)
                    if (revision(after)[:2] == expected[:2]
                            and revision(current) == expected
                            and (before.st_dev, before.st_ino) ==
                            (current.st_dev, current.st_ino)):
                        return digest.hexdigest()
                    return None
                digest.update(chunk)
    except OSError:
        return None
    return None


class FileDigest:
    def __init__(self, path, expected):
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._pending = OrderedDict()
        self.future = _executor.submit(_hash_file, path, expected, self.cancelled)
        self.future.add_done_callback(lambda _future: self._schedule_flush())

    def _schedule_flush(self):
        with self._lock:
            if not self._pending or self.cancelled.is_set():
                return
        _executor.submit(self._flush)

    def defer(self, identity, callback):
        # Keep at most two visible-page scenes alive while the digest is pending.
        with self._lock:
            if self.cancelled.is_set():
                return
            self._pending[identity] = callback
            self._pending.move_to_end(identity)
            while len(self._pending) > 2:
                self._pending.popitem(last=False)
        if self.future.done():
            self._schedule_flush()

    def _flush(self):
        digest = self.value()
        with self._lock:
            callbacks = list(self._pending.values())
            self._pending.clear()
        if digest is not None:
            for callback in callbacks:
                if self.cancelled.is_set():
                    break
                callback(digest)

    def value(self):
        if self.cancelled.is_set() or not self.future.done():
            return None
        return self.future.result()

    def cancel(self):
        self.cancelled.set()
        with self._lock:
            self._pending.clear()
        self.future.cancel()
