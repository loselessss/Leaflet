"""Manual Windows GPU benchmark; exact replay, no raster/group snapshot reuse.

Run with ``python -m tests.benchmark_gpu_pipeline --help``. Input PDFs and
generated measurements stay outside source control. Sharp timings include the
reader's 30 ms polling cadence; direct timings include synchronized readback.
Neither mode includes vsync/present or immutable geometry upload.
"""
import argparse
from collections import Counter
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time

import pymupdf
from PyQt5.QtWidgets import QApplication

from pdfeditor.d2d_backend import D2DSurface
from pdfeditor.gpu_raster import vector_page_from_pymupdf
from pdfeditor.reader_view import ReaderPageView


def process_memory():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("faults", ctypes.c_uint32)] + [
            (name, ctypes.c_size_t) for name in ("peak_rss", "rss", "peak_paged",
            "paged", "peak_nonpaged", "nonpaged", "commit", "peak_commit", "private")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    read = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    read.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_uint32]
    if not read(ctypes.c_void_p(-1), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {name + "_mib": getattr(counters, name) / 1024**2
            for name in ("peak_rss", "rss", "peak_commit", "private")}


def render_sample(surface, retained, transform, width, height, mode, poll_seconds):
    started = time.perf_counter()
    first_tile = None
    try:
        if mode == "sharp":
            if not surface.request_sharp_scene(retained, transform):
                raise RuntimeError("fresh sharp job was not queued")
            submitted = time.perf_counter()
            while True:
                status = surface.sharp_status()
                if first_tile is None and status in (2, 3):
                    first_tile = (time.perf_counter() - started) * 1000
                if status == 2:
                    break
                if time.perf_counter() - started > 30:
                    raise TimeoutError("sharp preparation exceeded 30 seconds")
                time.sleep(poll_seconds)
            finished = time.perf_counter()
            surface.begin_frame(0xffffffff)
            if not surface.draw_sharp_scene(retained, transform):
                raise RuntimeError("completed sharp frame missing")
        else:
            surface.begin_frame(0xffffffff)
            surface.draw_scene(retained, transform, reuse_groups=False)
            submitted = time.perf_counter()
        pixels = surface.read_pixels_bgra(width, height)
        if mode == "direct":
            finished = time.perf_counter()
        surface.end_frame()
        return ((finished - started) * 1000, (submitted - started) * 1000, first_tile, pixels)
    except Exception:
        try:
            surface.end_frame()
        except OSError:
            pass
        raise
    finally:
        surface.cancel_sharp()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--library", action="append", default=[], metavar="NAME=DLL",
                        help="Repeat to interleave builds in alternating order.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=15)
    parser.add_argument("--mode", choices=("direct", "sharp"), default="sharp")
    parser.add_argument("--poll-ms", type=float, default=30,
                        help="Sharp completion polling interval, matching the reader by default.")
    args = parser.parse_args()
    libraries = []
    for spec in args.library:
        name, separator, path = spec.partition("=")
        if not separator or not name or Path(name).name != name:
            parser.error("--library must be NAME=DLL, with a plain output folder name")
        libraries.append((name, Path(path)))
    if not libraries:
        libraries = [("current", None)]
    if len({name for name, _ in libraries}) != len(libraries):
        parser.error("library names must be unique")
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    if not 0 < args.poll_ms <= 1000:
        parser.error("--poll-ms must be greater than 0 and at most 1000")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
        ctypes.c_wchar_p, ctypes.c_uint32, *([ctypes.c_int] * 4),
        *([ctypes.c_void_p] * 4)]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    width, height = 1200, 900
    results = {"viewport": [width, height], "dpi": 96, "repeats": args.repeats,
               "poll_ms": args.poll_ms, "raster_scale": 1,
               "mode": args.mode,
               "metric": ("fresh scene request to complete sharp atlas (ms)" if args.mode == "sharp"
                          else "begin + fresh exact replay + synchronized BGRA readback (ms)"),
               "snapshot_reuse": False, "documents": []}
    for filename in args.pdf:
        started = time.perf_counter()
        with pymupdf.open(filename) as pdf:
            page = pdf[0]
            page_width, page_height = page.rect.width, page.rect.height
            scene = vector_page_from_pymupdf(page, raster_scale=1)
        extraction_ms = (time.perf_counter() - started) * 1000
        if not scene.supported:
            raise RuntimeError(f"{filename}: {scene.reason}")
        record = {"file": filename.name, "sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
                  "page_size": [page_width, page_height], "extraction_ms": extraction_ms,
                  "commands": dict(Counter(type(item).__name__ for item in scene.drawables)),
                  "features": scene.features, "runs": []}
        lanes = []
        try:
            for name, library in libraries:
                hwnd = user32.CreateWindowExW(0, "STATIC", "GPU benchmark", 0,
                    0, 0, width, height, None, None, None, None)
                if not hwnd:
                    raise ctypes.WinError(ctypes.get_last_error())
                view = ReaderPageView(use_opengl=False)
                lane = {"name": name, "view": view, "hwnd": hwnd}
                lanes.append(lane)
                surface = D2DSurface(hwnd, width, height, path=library)
                lane["surface"] = surface
                view._d2d_surface = surface
                view._page_sizes = {0: (page_width, page_height)}
                started = time.perf_counter()
                view._native_vector_draws(0, scene)
                lane["draws"] = view._d2d_vector_paths[0][1]
                lane["result"] = {"name": name, "upload_ms": (time.perf_counter() - started) * 1000,
                    "adapter": surface.info.adapter_name, "driver": surface.info.driver, "cases": []}
                if library is not None:
                    lane["result"]["library_sha256"] = hashlib.sha256(library.read_bytes()).hexdigest()
                record["runs"].append(lane["result"])
                (args.output / name).mkdir(exist_ok=True)
            fit = min(width / page_width, height / page_height)
            for name, scale in (("fit", fit), ("100pct", 1.0), ("200pct", 2.0)):
                dx, dy = (width - page_width * scale) / 2, (height - page_height * scale) / 2
                for lane in lanes:
                    lane["case"] = {"name": name, "scale": scale, "samples_ms": [],
                                    "submission_ms": [], "first_tile_ms": []}
                    lane["result"]["cases"].append(lane["case"])
                for index in range(args.repeats + 3):
                    # Rotate/reverse order to reduce clock/thermal/order bias.
                    rotation = (index // 2) % len(lanes)
                    order = lanes[rotation:] + lanes[:rotation]
                    if index % 2:
                        order = list(reversed(order))
                    for lane in order:
                        case = lane["case"]
                        if "error" in case:
                            continue
                        surface = lane["surface"]
                        # A fresh identity prevents page, group and tile reuse.
                        retained = surface.create_scene(page_width, page_height, lane["draws"])
                        transform = (scale, 0, 0, scale, dx, dy)
                        time.sleep(.025)  # Drain Present outside the timer.
                        try:
                            elapsed, submitted, first_tile, pixels = render_sample(
                                surface, retained, transform, width, height, args.mode, args.poll_ms / 1000)
                            if index == 0:
                                image = args.output / lane["name"] / f"{filename.stem}-{name}.bgra"
                                image.write_bytes(pixels)
                            if index >= 3:
                                case["samples_ms"].append(elapsed)
                                case["submission_ms"].append(submitted)
                                if first_tile is not None:
                                    case["first_tile_ms"].append(first_tile)
                        except (OSError, RuntimeError, TimeoutError) as error:
                            case["error"] = str(error)
                        finally:
                            retained.close()
                for lane in lanes:
                    case = lane["case"]
                    if "error" not in case:
                        case["median_ms"] = statistics.median(case["samples_ms"])
                        case["p95_ms"] = sorted(case["samples_ms"])[math.ceil(.95 * args.repeats) - 1]
                        case["submission_median_ms"] = statistics.median(case["submission_ms"])
                        if case["first_tile_ms"]:
                            case["first_tile_median_ms"] = statistics.median(case["first_tile_ms"])
                    print(filename.name, name, lane["name"], case.get("error", round(case.get("median_ms", 0), 2)), flush=True)
        finally:
            record["process_memory"] = process_memory()
            for lane in lanes:
                lane["view"]._release_d2d_surface()
                lane["view"].close()
                lane["view"].deleteLater()
                user32.DestroyWindow(lane["hwnd"])
            app.processEvents()
        results["documents"].append(record)
        (args.output / "results.json").write_text(json.dumps(results, indent=2,
            ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
