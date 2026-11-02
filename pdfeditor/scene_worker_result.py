"""Read a bounded standalone-worker result; legacy private IPC stays readable."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import math
import os
import pickle
import shutil
import struct
import threading
from .scene_cache_packet import decode, MAX_BLOB

MAGIC = b'LFSW\x01\0\0\0'
HEADER = struct.Struct('<IdI4dQ')
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='leaflet-scene-result')


class SceneResultRead:
    """Read private IPC off the GUI thread, with one bounded decoder at a time.

    This task owns only file paths and immutable scene data. Cancellation never
    waits or accesses a document, Qt object, or MuPDF SDK from this thread.
    The task owns its directory until reading and cleanup have both completed.
    """
    def __init__(self, path, directory, failure_reason=None):
        self.path, self.directory = path, directory
        self._lock = threading.Lock()
        self._cancelled = False
        self._ready = threading.Event()
        self._result = (None, None)
        _executor.submit(self._read, failure_reason)

    def _read(self, failure_reason):
        scene = None
        try:
            with self._lock:
                cancelled = self._cancelled
            if not cancelled and failure_reason is None:
                if os.path.isfile(self.path):
                    with open(self.path, 'rb') as stream:
                        scene = load(stream)
                else:
                    failure_reason = 'GPU scene worker returned no result'
        except Exception as error:
            failure_reason = 'GPU scene result could not be read: ' + str(error)
        finally:
            shutil.rmtree(self.directory, ignore_errors=True)
        with self._lock:
            if not self._cancelled:
                self._result = scene, failure_reason
            self._ready.set()

    def done(self):
        return self._ready.is_set()

    def take(self):
        if not self.done():
            raise RuntimeError('GPU scene result is not ready')
        with self._lock:
            result, self._result = self._result, (None, None)
            return result

    def cancel(self):
        with self._lock:
            self._cancelled = True
            self._result = (None, None)


def load(stream):
    prefix = stream.read(len(MAGIC))
    if prefix != MAGIC:
        stream.seek(0)
        return pickle.load(stream)  # Only the existing private Python worker protocol.
    header = stream.read(HEADER.size)
    if len(header) != HEADER.size:
        raise ValueError('truncated native worker header')
    status, scale, has_view, x0, y0, x1, y1, length = HEADER.unpack(header)
    if (status not in (0, 1) or has_view not in (0, 1)
            or not math.isfinite(scale) or not 1 <= scale <= 64
            or length > (4096 if status else MAX_BLOB)):
        raise ValueError('invalid native worker result')
    viewport = (x0, y0, x1, y1) if has_view else None
    if viewport is not None and (not all(map(math.isfinite, viewport)) or x1 <= x0 or y1 <= y0):
        raise ValueError('invalid native worker viewport')
    payload = stream.read(length)
    if len(payload) != length or stream.read(1):
        raise ValueError('truncated or trailing native worker result')
    if status:
        from .gpu_raster import VectorPage
        return VectorPage(False, reason=payload.decode('utf-8'), raster_scale=scale, viewport=viewport)
    scene = decode(payload)
    if scene.raster_scale != scale:
        raise ValueError('native worker scale mismatch')
    return replace(scene, viewport=viewport)
