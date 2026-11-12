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


def policy(total, available, limit_mb=0):
    available = max(0, min(total, available))
    budget = max(16 * MIB, min(2048 * MIB, total // 16, available // 4))
    if limit_mb:
        budget = min(budget, limit_mb * MIB)
    # Leave ample room for the worker's temporary image/geometry buffers.
    count = 0 if available < 1024 * MIB else max(2, budget // (32 * MIB))
    return RenderMemory(budget, count)


def vector_gpu_budget(ram_budget, video):
    """Retain drawing resources while reserving room for active composition."""
    limit = ram_budget // 2
    if video is not None:
        budget, usage = video
        limit = min(limit, budget // 4, max(0, budget - usage) // 2)
    return limit


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32)] + [
        (name, ctypes.c_uint64) for name in (
            "total", "available", "page_total", "page_available",
            "virtual_total", "virtual_available", "extended")]


_last_sample = 0.0
_cached = RenderMemory(128 * MIB, 1)


def invalidate_render_memory():
    global _last_sample
    _last_sample = 0.0


def process_memory_bytes(process):
    """Sample an owned Windows worker without opening another process handle."""
    if os.name != "nt":
        return 0
    try:
        handle = int(process._handle)
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak", "resident", "peak_paged", "paged", "peak_nonpaged",
                    "nonpaged", "commit", "peak_commit", "private")]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        read = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        read.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32]
        if read(handle, ctypes.byref(counters), counters.cb):
            return max(counters.resident, counters.private)
    except (OSError, AttributeError, TypeError, ValueError):
        pass
    return 0


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
                from .settings import render_cache_mb
                _cached = policy(status.total, status.available, render_cache_mb())
        except (OSError, AttributeError):
            pass
    return _cached
