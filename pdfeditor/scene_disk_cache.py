"""Disposable, bounded GPU scene storage. Never deserialize executable objects."""

import base64
from dataclasses import fields, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import zlib

MAX_DECODED = 256 * 1024 * 1024
# Bump when extraction semantics or persisted fields change, not for UI releases.
SCENE_FORMAT_VERSION = 4


def _limit():
    from .settings import disk_cache_mb
    return disk_cache_mb() * 1024 * 1024


def _types():
    from . import gpu_raster as g
    return {name: getattr(g, name) for name in (
        "VectorPage", "VectorPath", "VectorImage", "VectorLinearGradient",
        "VectorRadialGradient", "ClipPush", "ClipStrokePush", "ClipPop",
        "GroupPush", "GroupPop", "MaskBegin", "MaskEnd")}


def _encode(value):
    if is_dataclass(value):
        referenced = type(value).__name__ == "VectorImage" and value.source_index is not None
        encoded = {"type": type(value).__name__, "fields": {
            f.name: _encode(getattr(value, f.name)) for f in fields(value)
            if not (referenced and f.name == "pixels")}}
        if referenced:
            encoded["fields"]["pixels"] = {
                "image_ref": value.source_index,
                "sha256": hashlib.sha256(value.pixels).hexdigest()}
        return encoded
    if isinstance(value, bytes):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (tuple, list)):
        return [_encode(v) for v in value]
    return value


def _decode(value, types, images=None):
    if isinstance(value, list):
        return tuple(_decode(v, types, images) for v in value)
    if isinstance(value, dict):
        if "image_ref" in value:
            pixels = images[value["image_ref"]]
            if hashlib.sha256(pixels).hexdigest() != value["sha256"]:
                raise ValueError("source image changed")
            return pixels
        if set(value) == {"bytes"}:
            return base64.b64decode(value["bytes"], validate=True)
        cls = types[value["type"]]
        return cls(**{k: _decode(v, types, images) for k, v in value["fields"].items()})
    return value


def _connect():
    from .paths import user_data_dir
    root = Path(user_data_dir()) / "cache"
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(root / "gpu-scenes.sqlite3"), timeout=0.1)
    try:
        db.execute("PRAGMA auto_vacuum=FULL")
        db.execute("PRAGMA max_page_count=%d" % max(4, _limit() // 4096))
        db.execute("CREATE TABLE IF NOT EXISTS scenes (key TEXT PRIMARY KEY, data BLOB, used REAL)")
    except sqlite3.Error:
        db.close()
        raise
    return db


def key(document, page, scale, aggressive):
    # In-memory edits, protected documents and annotation overlays must not
    # share the original file's cache or persist decrypted content.
    try:
        if not _limit():
            return None
        if (document.render_generation or document._doc.is_dirty or
                document.password_protected or document._annotation_store or
                not getattr(document, "_disk_cache_source", None)):
            return None
        path, original = document._disk_cache_source
        current = os.stat(path)
        revision = (current.st_size, current.st_mtime_ns, current.st_ctime_ns)
        if revision != original:
            return None
        digest = getattr(document, "_disk_cache_digest", None)
        if digest is None:
            h = hashlib.sha256()
            with open(path, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            after = os.stat(path)
            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != revision:
                return None
            digest = document._disk_cache_digest = h.hexdigest()
        from .d2d_backend import ABI_VERSION
        import pymupdf
        identity = (SCENE_FORMAT_VERSION, ABI_VERSION, pymupdf.VersionBind,
                    digest, page, float(scale), bool(aggressive))
        return hashlib.sha256(repr(identity).encode()).hexdigest()
    except (OSError, AttributeError, ValueError):
        return None


def _source_pixels(page, payload):
    """Replay image callbacks only; cached paths/glyphs/effects stay untouched."""
    refs = set()
    def collect(node):
        if isinstance(node, dict):
            if "image_ref" in node:
                refs.add(node["image_ref"])
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)
    collect(payload)
    if not refs:
        return {}
    if page is None:
        raise ValueError("source page required")
    from .gpu_raster import _DisplayListDevice, _mupdf
    scale = payload["fields"]["raster_scale"]
    recorder = _DisplayListDevice(tuple(page.rect), scale)
    pixels = {}
    class ImagesOnly(_mupdf.FzDevice2):
        def __init__(self):
            super().__init__()
            self.index = 0
            self.use_virtual_fill_image()
            self.use_virtual_begin_tile()

        def begin_tile(self, *_args):
            return 0

        def fill_image(self, *args):
            index = self.index
            self.index += 1
            if index not in refs:
                return
            recorder.fill_image(*args)
            if not recorder.failure and recorder.items:
                pixels[index] = recorder.items.pop().pixels
    device = ImagesOnly()
    _mupdf.fz_run_page(page.this, device, _mupdf.FzMatrix(), _mupdf.FzCookie())
    if recorder.failure or refs != set(pixels):
        raise ValueError("source image replay failed")
    return pixels


def load(cache_key, page=None):
    if cache_key is None or not _limit():
        return None
    db = None
    try:
        db = _connect()
        row = db.execute("SELECT data FROM scenes WHERE key=?", (cache_key,)).fetchone()
        if row is None:
            return None
        decoder = zlib.decompressobj()
        raw = decoder.decompress(row[0], MAX_DECODED + 1)
        if len(raw) > MAX_DECODED or not decoder.eof:
            return None
        payload = json.loads(raw)
        scene = _decode(payload, _types(), _source_pixels(page, payload))
        if type(scene).__name__ != "VectorPage" or not scene.supported:
            return None
        db.execute("UPDATE scenes SET used=julianday('now') WHERE key=?", (cache_key,))
        db.commit()
        return scene
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RuntimeError,
            zlib.error, RecursionError):
        return None
    finally:
        if db is not None:
            db.close()


def save(cache_key, scene):
    if cache_key is None or not scene.supported or not _limit():
        return
    db = None
    try:
        raw = json.dumps(_encode(scene), separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > MAX_DECODED:
            return
        data = zlib.compress(raw, 1)
        # Reserve space for SQLite's index and page overhead within 100 MiB.
        budget = _limit() * 9 // 10
        if len(data) > budget:
            return
        db = _connect()
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM scenes WHERE key=?", (cache_key,))
        total = db.execute("SELECT coalesce(sum(length(data)),0) FROM scenes").fetchone()[0]
        while total + len(data) > budget:
            oldest = db.execute("SELECT key,length(data) FROM scenes ORDER BY used LIMIT 1").fetchone()
            db.execute("DELETE FROM scenes WHERE key=?", (oldest[0],))
            total -= oldest[1]
        db.execute("INSERT INTO scenes VALUES(?,?,julianday('now'))", (cache_key, data))
        db.commit()
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError):
        pass
    finally:
        if db is not None:
            db.close()


def trim():
    """Apply a reduced budget immediately; disabling discards stored scenes."""
    db = None
    try:
        db = _connect()
        db.execute("BEGIN IMMEDIATE")
        budget = _limit() * 9 // 10
        rows = db.execute("SELECT key,length(data) FROM scenes ORDER BY used").fetchall()
        total = sum(size for _, size in rows)
        for cache_key, size in rows:
            if total <= budget:
                break
            db.execute("DELETE FROM scenes WHERE key=?", (cache_key,))
            total -= size
        db.commit()
    except (OSError, sqlite3.Error):
        pass
    finally:
        if db is not None:
            db.close()
