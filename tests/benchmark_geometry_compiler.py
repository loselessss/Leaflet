"""Compare extraction with step 1 retained and only Rust geometry toggled.

Input PDFs and JSON results are private. No scene/result cache is used.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
import pymupdf
from pdfeditor import gpu_raster as raster


def render_signatures(scene, size):
    from pdfeditor.d2d_backend import D2DSurface
    from pdfeditor.reader_view import ReaderPageView
    from tests.benchmark_gpu_pipeline import render_sample
    user32 = ctypes.WinDLL('user32')
    user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    hwnd = user32.CreateWindowExW(0, 'STATIC', 'Geometry benchmark', 0,
                                 0, 0, 1200, 900, None, None, None, None)
    if not hwnd:
        raise ctypes.WinError()
    view = ReaderPageView(use_opengl=False)
    surface = D2DSurface(hwnd, 1200, 900)
    view._d2d_surface = surface
    view._page_sizes = {0: size}
    try:
        view._native_vector_draws(0, scene)
        retained = view._d2d_vector_paths[0][3]
        hashes = {}
        for scale in (min(1200 / size[0], 900 / size[1]), 1., 8.):
            transform = (scale, 0., 0., scale, (1200-size[0]*scale)/2, (900-size[1]*scale)/2)
            pixels = render_sample(surface, retained, transform, 1200, 900, 'completed', .001)[3]
            hashes[str(scale)] = hashlib.sha256(pixels).hexdigest()
        return hashes
    finally:
        view._discard_native_vector_page(0)
        view._d2d_surface = None
        surface.close()
        view.close()
        user32.DestroyWindow(hwnd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=7)
    parser.add_argument('--verify-render', action='store_true')
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error('use at least three repetitions')
    rust = raster._rust_geometry
    if rust is None:
        raise RuntimeError('Build Rust geometry helpers first')
    if args.verify_render:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
    records = []
    try:
        for filename in args.pdf:
            record = {'file': filename.name, 'extraction_ms': {'python': [], 'rust': []}}
            baseline = None
            for iteration in range(args.repeats + 1):
                modes = ('python', 'rust') if iteration % 2 == 0 else ('rust', 'python')
                for mode in modes:
                    raster._rust_geometry = rust if mode == 'rust' else None
                    with pymupdf.open(filename) as document:
                        page = document[0]
                        size = (page.rect.width, page.rect.height)
                        start = time.perf_counter()
                        scene = raster.vector_page_from_pymupdf(page)
                        elapsed = (time.perf_counter() - start) * 1000
                    if not scene.supported:
                        raise RuntimeError(scene.reason)
                    if baseline is None:
                        baseline = scene
                    if scene != baseline:
                        raise AssertionError('extracted scene differs')
                    if iteration == 0 and args.verify_render:
                        hashes = render_signatures(scene, size)
                        if mode == 'python':
                            record['pixel_sha256'] = hashes
                        elif hashes != record['pixel_sha256']:
                            raise AssertionError('rendered pixels differ')
                    if iteration:
                        record['extraction_ms'][mode].append(elapsed)
            record['scene_equal'] = True
            record['commands'] = len(baseline.drawables)
            record['median_ms'] = {mode: statistics.median(samples)
                                   for mode, samples in record['extraction_ms'].items()}
            records.append(record)
            print(json.dumps(record), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(records, indent=2), encoding='utf-8')
    finally:
        raster._rust_geometry = rust


if __name__ == '__main__':
    main()
    os._exit(0)  # Avoid unstable Qt/D2D teardown after optional render checks.
