"""Optional exact-version bridge; path pointers are borrowed for one call only."""
import ctypes
from functools import lru_cache
from pathlib import Path
import sys
import pymupdf
import struct
from .scene_transfer import PackedCommands


@lru_cache(maxsize=1)
def _library():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    path = base / 'native' / ('leaflet_mupdf_path.dll' if getattr(sys, 'frozen', False)
                              else 'bin/leaflet_mupdf_path.dll')
    try:
        library = ctypes.PyDLL(str(path))  # Retain GIL through MuPDF's thread-local context.
        library.leaflet_path_version.restype = ctypes.c_char_p
        if library.leaflet_path_version().decode('ascii') != pymupdf.VersionFitz:
            return None
        library.leaflet_path_walk.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
        library.leaflet_path_walk.restype = ctypes.c_void_p
        library.leaflet_path_drop.argtypes = [ctypes.c_void_p]
        library.leaflet_path_drop.restype = None
        # Older development bridges can still supply path walking alone.
        if hasattr(library, 'leaflet_text_scan'):
            output_types = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t),
                            ctypes.POINTER(ctypes.c_size_t)]
            library.leaflet_text_scan.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), *output_types]
            library.leaflet_text_scan.restype = ctypes.c_void_p
            library.leaflet_glyph_walk.argtypes = [ctypes.c_void_p, ctypes.c_int32, *output_types]
            library.leaflet_glyph_walk.restype = ctypes.c_void_p
        if hasattr(library, 'leaflet_scene_collect'):
            library.leaflet_scene_abi.restype = ctypes.c_uint32
            if library.leaflet_scene_abi()!=4:
                return None
            outputs = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_size_t)]
            library.leaflet_scene_collect.argtypes = [ctypes.c_void_p, ctypes.c_double, *outputs]
            library.leaflet_scene_collect.restype = ctypes.c_void_p
            library.leaflet_scene_drop.argtypes = [ctypes.c_void_p]
            library.leaflet_scene_drop.restype = None
            library.leaflet_scene_materialize.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                        ctypes.c_size_t, *outputs]
            library.leaflet_scene_materialize.restype = ctypes.c_void_p
            library.leaflet_scene_error.restype = ctypes.c_char_p
            library.leaflet_scene_probe.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
            library.leaflet_scene_probe.restype = ctypes.c_int
        return library
    except (OSError, AttributeError):
        return None


def walk_path(path):
    library = _library()
    if library is None:
        return None
    data, size, count = ctypes.c_void_p(), ctypes.c_size_t(), ctypes.c_size_t()
    handle = library.leaflet_path_walk(path.m_internal_value(), ctypes.byref(data),
                                       ctypes.byref(size), ctypes.byref(count))
    if not handle:
        raise ValueError('native MuPDF path extraction failed')
    try:
        return PackedCommands(ctypes.string_at(data, size.value), count.value)
    finally:
        library.leaflet_path_drop(handle)


def scan_text(text, matrix):
    library = _library()
    if library is None or not hasattr(library, 'leaflet_text_scan'):
        return None
    from pymupdf import mupdf as m
    resource = text if isinstance(text, m.FzText) else m.FzText(text)
    if resource is not text:
        resource.thisown = False
    data, size, count = ctypes.c_void_p(), ctypes.c_size_t(), ctypes.c_size_t()
    handle = library.leaflet_text_scan(resource.m_internal_value(), (ctypes.c_float*6)(*matrix),
                                       ctypes.byref(data), ctypes.byref(size), ctypes.byref(count))
    if not handle:
        return None
    try:
        blob = ctypes.string_at(data, size.value)
        if len(blob) != count.value*40:
            raise ValueError('native text record mismatch')
        return struct.iter_unpack('<Qii6f', blob)
    finally:
        library.leaflet_path_drop(handle)


def walk_glyph(font, gid):
    library = _library()
    data, size, count = ctypes.c_void_p(), ctypes.c_size_t(), ctypes.c_size_t()
    handle = library.leaflet_glyph_walk(font, gid, ctypes.byref(data), ctypes.byref(size), ctypes.byref(count))
    if not handle:
        return None
    try:
        return PackedCommands(ctypes.string_at(data, size.value), count.value)
    finally:
        library.leaflet_path_drop(handle)


def compile_page(page, scale=1., viewport=None, timeout_seconds=None):
    """Three batch calls; PDF objects never cross into the Rust worker threads."""
    from ._path_packer import plan_native_scene, compile_native_scene
    library = _library()
    if library is None or not hasattr(library, 'leaflet_scene_collect'):
        raise RuntimeError('native MuPDF scene adapter is unavailable or has a different version')
    data, size = ctypes.c_void_p(), ctypes.c_size_t()
    job = library.leaflet_scene_collect(page.this.m_internal_value(),
        -1. if timeout_seconds is None else timeout_seconds, ctypes.byref(data), ctypes.byref(size))
    if not job:
        raise ValueError('native PDF collection failed: '+library.leaflet_scene_error().decode('utf-8','replace'))
    try:
        requests = plan_native_scene(ctypes.string_at(data, size.value), tuple(page.rect), scale, viewport)
        handle = library.leaflet_scene_materialize(job, ctypes.c_char_p(requests), len(requests),
                                                 ctypes.byref(data), ctypes.byref(size))
        if not handle:
            raise ValueError('native PDF materialization failed: '+library.leaflet_scene_error().decode('utf-8','replace'))
        try:
            return compile_native_scene(ctypes.string_at(data, size.value))
        finally:
            library.leaflet_path_drop(handle)
    finally:
        library.leaflet_scene_drop(job)


def probe_page(page):
    library = _library()
    if library is None or not hasattr(library,'leaflet_scene_probe'):
        return 1000000,1000000  # Defer to the bounded worker when native input is unavailable.
    score, operations = ctypes.c_uint64(),ctypes.c_uint64()
    if not library.leaflet_scene_probe(page.this.m_internal_value(),ctypes.byref(score),ctypes.byref(operations)):
        return 1000000,1000000
    return score.value,operations.value
