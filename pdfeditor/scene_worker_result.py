"""Read a bounded standalone-worker result; legacy private IPC stays readable."""
from dataclasses import replace
import math
import pickle
import struct
from .scene_cache_packet import decode, MAX_BLOB

MAGIC = b'LFSW\x01\0\0\0'
HEADER = struct.Struct('<IdI4dQ')


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
