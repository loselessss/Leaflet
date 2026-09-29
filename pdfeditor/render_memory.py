"""Lightweight, periodically refreshed RAM limits for speculative rendering."""

import ctypes
import os
import time
from dataclasses import dataclass

MIB = 1024 * 1024


@dataclass(frozen=True)
class RenderMemory:
    scene_bytes: int
    prefetch_pages: int


def policy(total, available):
    available = max(0, min(total, available))
    budget = max(16 * MIB, min(1024 * MIB, total // 32, available // 8))
    # Leave ample room for the worker's temporary image/geometry buffers.
    count = 0 if available < 1024 * MIB else min(4, max(1, budget // (128 * MIB)))
    return RenderMemory(budget, count)


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            "total", "available", "page_total", "page_available",
            "virtual_total", "virtual_available", "extended")]


_last_sample = 0.0
_cached = RenderMemory(128 * MIB, 1)


def render_memory():
    global _last_sample, _cached
    now = time.monotonic()
    if now - _last_sample < 2:
        return _cached
    _last_sample = now
    if os.name == "nt":
        status = _MemoryStatus()
        status.length = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                _cached = policy(status.total, status.available)
        except (OSError, AttributeError):
            pass
    return _cached
