"""Compare fresh Python/Rust path packing and native scene preparation on PDFs.

Run as a module with PDF paths and --output. Extraction is outside the timer.
Every preparation creates new native resources; no rendered output is reused.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import statistics
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 3:
        parser.error("use at least three repetitions")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import pymupdf
    from PyQt5.QtWidgets import QApplication
    from pdfeditor import d2d_backend as backend
    from pdfeditor.gpu_raster import vector_page_from_pymupdf
    from pdfeditor.reader_view import ReaderPageView
    from tests.benchmark_gpu_pipeline import render_sample
    app = QApplication.instance() or QApplication([])
    rust = backend._rust_pack_path
    if rust is None:
        raise RuntimeError("Build the Rust extension first")
    user32 = ctypes.WinDLL("user32")
    user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    records = []
    for filename in args.pdf:
        with pymupdf.open(filename) as pdf:
            page = pdf[0]
            size = page.rect.width, page.rect.height
            scene = vector_page_from_pymupdf(page)
        if not scene.supported:
            raise RuntimeError(scene.reason)
        commands = set(item.commands for item in scene.drawables if hasattr(item, "commands"))
        for path in commands:
            if bytes(backend._python_path_array(path)) != bytes(rust(path)):
                raise AssertionError("packed path bytes differ")
        result = {"file": filename.name, "paths": len(commands),
                  "segments": sum(map(len, commands)), "packed_bytes_equal": True,
                  "packing_ms": {"python": [], "rust": []},
                  "preparation_ms": {"python": [], "rust": []}, "pixel_sha256": {}}
        hwnd = user32.CreateWindowExW(0, "STATIC", "Path packing benchmark", 0,
            0, 0, 1200, 900, None, None, None, None)
        if not hwnd:
            raise ctypes.WinError()
        surface = backend.D2DSurface(hwnd, 1200, 900)
        view = ReaderPageView(use_opengl=False)
        view._d2d_surface = surface
        view._page_sizes = {0: size}
        try:
            for repetition in range(args.repeats + 1):
                order = ("python", "rust") if repetition % 2 == 0 else ("rust", "python")
                for mode in order:
                    backend._rust_pack_path = rust if mode == "rust" else None
                    start = time.perf_counter()
                    for path in commands:
                        packed = backend._path_array(path)
                        del packed
                    packing_ms = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()
                    view._native_vector_draws(0, scene)
                    preparation_ms = (time.perf_counter() - start) * 1000
                    if repetition:
                        result["packing_ms"][mode].append(packing_ms)
                        result["preparation_ms"][mode].append(preparation_ms)
                    if repetition == 0:
                        retained = view._d2d_vector_paths[0][3]
                        for scale in (min(1200 / size[0], 900 / size[1]), 1.0, 8.0):
                            transform = (scale, 0, 0, scale,
                                         (1200-size[0]*scale)/2, (900-size[1]*scale)/2)
                            pixels = render_sample(surface, retained, transform,
                                                   1200, 900, "completed", .001)[3]
                            digest = hashlib.sha256(pixels).hexdigest()
                            key = str(scale)
                            if mode == "python":
                                result["pixel_sha256"][key] = digest
                            elif result["pixel_sha256"][key] != digest:
                                raise AssertionError("rendered pixels differ")
                    view._discard_native_vector_page(0)
            result["median_ms"] = {metric: {mode: statistics.median(samples)
                for mode, samples in result[metric].items()}
                for metric in ("packing_ms", "preparation_ms")}
            records.append(result)
            print(json.dumps(result), flush=True)
        finally:
            backend._rust_pack_path = rust
            view._discard_native_vector_page(0)
            view._d2d_surface = None
            surface.close()
            view.close()
            user32.DestroyWindow(hwnd)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
    # Native Qt/D2D teardown is otherwise unstable in this manual harness.
    os._exit(0)
