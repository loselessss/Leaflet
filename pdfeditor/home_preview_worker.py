"""First-page previews in an isolated, headless MuPDF process."""
import base64
import json
import math
import os
import sys

MAX_EDGE = 340
MAX_HEIGHT = 220
MAX_REPLY = 1024 * 1024


def preview(path, *, work_dir=None):
    import pymupdf
    from . import scene_disk_cache as cache
    from .document_snapshot import DocumentSnapshot

    before = os.stat(path)
    revision = (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    cache_key = cache.thumbnail_key(path, revision, (pymupdf.VersionBind, MAX_EDGE, MAX_HEIGHT))
    png = cache.load_thumbnail(cache_key)
    if png is not None:
        try:
            decoded = pymupdf.Pixmap(png)
            if decoded.width <= MAX_EDGE + 1 and decoded.height <= MAX_HEIGHT + 1:
                return {"status": "ready", "png": base64.b64encode(png).decode("ascii")}
        except Exception:
            pass
    # MuPDF reads only a private, disk-backed copy. A slow poster preview must
    # not keep the original PDF locked while another window saves/replaces it.
    snapshot = DocumentSnapshot(path, root=work_dir)
    try:
        with pymupdf.open(snapshot.path) as document:
            return _render(document, path, revision, cache_key)
    finally:
        snapshot.close()


def _render(document, path, revision, cache_key):
    import pymupdf
    from . import scene_disk_cache as cache

    if document.needs_pass or not document.page_count:
        return {"status": "locked" if document.needs_pass else "unavailable"}
    if document.metadata.get("encryption"):
        cache_key = None
    page = document[0]
    width, height = page.rect.width, page.rect.height
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        return {"status": "unavailable"}
    scale = min(MAX_EDGE / width, MAX_HEIGHT / height)
    pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale),
                             colorspace=pymupdf.csRGB, alpha=False)
    if pixels.width > MAX_EDGE + 1 or pixels.height > MAX_HEIGHT + 1:
        return {"status": "unavailable"}
    png = pixels.tobytes("png")
    if len(png) > MAX_REPLY // 2:
        return {"status": "unavailable"}
    if cache_key:
        after = os.stat(path)
        if revision == (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            cache.save_thumbnail(cache_key, png)
    return {"status": "ready", "png": base64.b64encode(png).decode("ascii")}


def main(args=None):
    import pymupdf

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    work_dir = args[0] if args else None
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line)
            result = preview(request["path"], work_dir=work_dir)
        except Exception:
            result = {"status": "unavailable"}
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
        # Do not retain decoded PDF resources between unrelated documents.
        pymupdf.TOOLS.store_shrink(100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
