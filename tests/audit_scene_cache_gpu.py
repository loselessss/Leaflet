"""Verify cache restoration changes no completed GPU pixels at fit and 800%."""
import argparse
import ctypes
import json
import os
import subprocess
import tempfile
from pathlib import Path
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import pymupdf
from PyQt5.QtWidgets import QApplication
from pdfeditor.rust_scene_compiler import compile_vector_page
from pdfeditor.scene_cache_packet import encode, decode
from pdfeditor.d2d_backend import D2DSurface
from tests.benchmark_gpu_pipeline import render_sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-worker', action='store_true', help='Compare the standalone worker instead of cache restoration')
    args = parser.parse_args()
    app = QApplication([])
    user32 = ctypes.WinDLL('user32')
    user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_uint32, *([ctypes.c_int] * 4), *([ctypes.c_void_p] * 4)]
    user32.CreateWindowExW.restype = ctypes.c_void_p
    user32.DestroyWindow.argtypes = [ctypes.c_void_p]
    rows = []
    for path in args.pdf:
        with pymupdf.open(path) as doc:
            page = doc[0]
            size = (page.rect.width, page.rect.height)
            handle = user32.CreateWindowExW(0, 'STATIC', 'Scene storage audit', 0,
                0, 0, 1200, 900, None, None, None, None)
            surface = D2DSurface(handle, 1200, 900)
            for scale in (min(1200 / size[0], 900 / size[1]), 8.):
                original = compile_vector_page(page, max(1., scale))
                assert original.supported, original.reason
                if args.native_worker:
                    from tests.test_native_scene_worker import native_command
                    from pdfeditor.scene_worker_result import load
                    with tempfile.TemporaryDirectory() as directory:
                        result = Path(directory) / 'scene.bin'
                        subprocess.run([*native_command(), str(path), str(result),
                            '--scale', str(max(1., scale)), '--timeout', '30'], check=True,
                            timeout=40, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        with result.open('rb') as stream:
                            restored = load(stream)
                else:
                    restored = decode(encode(original))
                assert restored == original
                frames = []
                for scene in (original, restored):
                    retained = surface.create_rust_scene(scene, *size)
                    transform = (scale, 0., 0., scale,
                        (1200 - size[0] * scale) / 2, (900 - size[1] * scale) / 2)
                    frames.append(render_sample(surface, retained, transform,
                        1200, 900, 'completed', .001)[3])
                    retained.close()
                differences = [abs(a - b) for a, b in zip(*frames)]
                row = dict(document=path.name, scale=scale,
                    changed_channels=sum(d != 0 for d in differences),
                    maximum_difference=max(differences),
                    packet_bytes=len(original.compiled_packet))
                assert frames[0] == frames[1], row
                rows.append(row)
                print(json.dumps(row), flush=True)
            surface.close()
            user32.DestroyWindow(handle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    os._exit(0)


if __name__ == '__main__':
    main()
