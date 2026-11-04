"""Page-at-a-time raster transport for the isolated OCR process."""
import json
import os
from pathlib import Path
import subprocess
import sys

MAX_PAGE_BYTES = 256 * 1024 * 1024


def renderer_command():
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent.parent
        for exe in (parent / "Leaflet.exe", parent / "Leaflet" / "Leaflet.exe"):
            if exe.is_file():
                return [str(exe), "--ocr-render-worker"]
        raise FileNotFoundError("Leaflet PDF raster worker is missing")
    return [sys.executable, "-m", "pdfeditor.ocr_render_worker"]


class PageSource:
    def __init__(self, job, target):
        self.process = subprocess.Popen(renderer_command(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1"),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.process.stdin.write(json.dumps(dict(path=job["path"],
                password=job.get("password"), zoom=job.get("zoom"), target=target)).encode() + b"\n")
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise

    def read(self, page):
        self.process.stdin.write(json.dumps(dict(page=page)).encode() + b"\n")
        self.process.stdin.flush()
        header = self.process.stdout.readline(4096)
        if not header:
            raise RuntimeError("PDF raster worker exited before returning a page")
        info = json.loads(header)
        if "error" in info:
            raise RuntimeError(info["error"])
        width, height, size = info["width"], info["height"], info["size"]
        if not (isinstance(width, int) and isinstance(height, int) and
                width > 0 and height > 0 and size == width * height * 3 and
                size <= MAX_PAGE_BYTES and 0 < info["zoom"] <= 64):
            raise ValueError("Invalid OCR raster response")
        data = bytearray(size)
        view = memoryview(data)
        offset = 0
        while offset < size:
            count = self.process.stdout.readinto(view[offset:])
            if not count:
                raise RuntimeError("Incomplete OCR raster response")
            offset += count
        import numpy as np
        return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3), info["zoom"]

    def close(self):
        if self.process.stdin:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        # EOF ends the helper, including when OCR is cancelled or crashes.
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
