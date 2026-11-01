"""Compare reader preview/thumbnail handoff without changing PDF rasterization."""
import argparse
from contextlib import nullcontext
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import tracemalloc
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pymupdf
from PyQt5.QtGui import QPixmap, QTransform
from PyQt5.QtWidgets import QApplication
from pdfeditor.core import Document
from pdfeditor.raster_buffer import RasterBuffer
from pdfeditor import widgets
from tests.benchmark_gpu_pipeline import process_memory
from tests.test_raster_handoff import rgb


def child(args):
    app = QApplication.instance() or QApplication([])
    doc = Document(str(args.pdf[0]), read_only=True)
    try:
        width, height = doc.page_size(0)
        scale = (min(.75, math.sqrt(1_000_000 / (width * height)))
                 if args.kind == 'preview' else 240 / width)
        # Include display-list creation, rasterization, Qt handoff and pixmap.
        gc.collect()
        started = time.perf_counter()
        with patch.object(widgets, '_copy_rgb_rows', None) if args.mode == 'qt-view' else nullcontext():
            image = widgets.qimage_from_render(*doc.render(0, scale, copy_pixels=args.mode == 'legacy'))
        pixmap = QPixmap.fromImage(image)
        total_ms = (time.perf_counter() - started) * 1000
        memory = process_memory()
        expected = rgb(image)
    finally:
        doc.close()
    # Keep a single identical SDK pixmap for transfer-only comparisons. Its
    # creation and conversion to the expected RGB bytes are outside all timings.
    with pymupdf.open(args.pdf[0]) as pdf:
        sdk = pdf[0].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    timings = []
    context = patch.object(widgets, '_copy_rgb_rows', None) if args.mode == 'qt-view' else nullcontext()
    with context:
        for _ in range(3):
            samples = sdk.samples if args.mode == 'legacy' else RasterBuffer(sdk)
            image = widgets.qimage_from_render(sdk.width, sdk.height, sdk.stride, samples)
        del image, samples
        for _ in range(40):
            started = time.perf_counter()
            samples = sdk.samples if args.mode == 'legacy' else RasterBuffer(sdk)
            image = widgets.qimage_from_render(sdk.width, sdk.height, sdk.stride, samples)
            timings.append((time.perf_counter() - started) * 1000)
            del image, samples
        gc.collect()
        tracemalloc.start()
        samples = sdk.samples if args.mode == 'legacy' else RasterBuffer(sdk)
        image = widgets.qimage_from_render(sdk.width, sdk.height, sdk.stride, samples)
        _, python_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    assert rgb(image) == expected
    assert rgb(pixmap.toImage()) == expected
    print(json.dumps(dict(document=args.pdf[0].name, kind=args.kind, mode=args.mode,
        width=sdk.width, height=sdk.height, rgb_bytes=sdk.stride * sdk.height,
        total_ms=total_ms, transfer_ms=statistics.median(timings),
        python_transfer_peak_bytes=python_peak, peak_rss_mib=memory['peak_rss_mib'], exact=True)), flush=True)


def audit(args):
    app = QApplication.instance() or QApplication([])
    rows = []
    for path in args.pdf:
        doc = Document(str(path), read_only=True)
        try:
            width, height = doc.page_size(0)
            for kind, scale in (('preview', min(.75, math.sqrt(1_000_000 / (width * height)))),
                                ('thumbnail', 240 / width)):
                legacy = widgets.qimage_from_render(*doc.render(0, scale))
                native = widgets.qimage_from_render(*doc.render(0, scale, copy_pixels=False))
                for image in (legacy, native):
                    image.setDevicePixelRatio(2.)
                expected = rgb(legacy)
                assert rgb(native) == expected
                assert rgb(QPixmap.fromImage(native).toImage()) == expected
                assert rgb(native.transformed(QTransform().rotate(90))) == rgb(legacy.transformed(QTransform().rotate(90)))
                row = dict(document=path.name, kind=kind, width=native.width(), height=native.height(),
                    changed_channels=0, maximum_difference=0, sha256=hashlib.sha256(expected).hexdigest())
                rows.append(row); print(json.dumps(row), flush=True)
        finally:
            doc.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path, nargs='+')
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--audit', action='store_true')
    parser.add_argument('--kind', choices=('preview', 'thumbnail'), default='preview')
    parser.add_argument('--mode', choices=('legacy', 'rust', 'qt-view'), default='rust')
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args)
        return
    if args.output is None:
        parser.error('--output is required outside child mode')
    if args.audit:
        audit(args)
        return
    rows = []
    for pdf in args.pdf:
        for kind in ('preview', 'thumbnail'):
            for run in range(args.runs):
                for mode in (('legacy', 'rust', 'qt-view') if run % 2 == 0 else ('qt-view', 'rust', 'legacy')):
                    output = subprocess.check_output([sys.executable, '-m', 'tests.benchmark_raster_handoff', '--child',
                        '--kind', kind, '--mode', mode, str(pdf)], text=True, timeout=60,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    row = json.loads(output); row['run'] = run; rows.append(row)
                    print(json.dumps(row), flush=True)
    medians = []
    for pdf in args.pdf:
        for kind in ('preview', 'thumbnail'):
            for mode in ('legacy', 'rust', 'qt-view'):
                samples = [r for r in rows if r['document'] == pdf.name and r['kind'] == kind and r['mode'] == mode]
                medians.append(dict(document=pdf.name, kind=kind, mode=mode, **{
                    key: statistics.median(r[key] for r in samples)
                    for key in ('total_ms', 'transfer_ms', 'python_transfer_peak_bytes', 'peak_rss_mib', 'rgb_bytes')}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(samples=rows, medians=medians), indent=2), encoding='utf-8')
    print(json.dumps(dict(medians=medians)), flush=True)


if __name__ == '__main__':
    main()
