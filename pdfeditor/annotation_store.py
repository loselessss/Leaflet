"""Versioned annotation-only sidecars; no Qt and no original PDF writes."""

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import uuid

import pymupdf as fitz


MAX_SIDECAR_BYTES = 16 * 1024 * 1024
OPERATIONS = {"add_note", "add_highlight", "set_note_text", "delete_annot"}


def _digest(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@contextmanager
def _write_lock(path):
    # The lock only covers comparison + atomic replacement, never the session.
    # A stale lock fails safely instead of guessing whether another writer lives.
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise OSError("The annotation file is locked by another save.") from error
    try:
        os.close(fd)
        yield
    finally:
        os.unlink(path)


class AnnotationStore:
    """An operation journal, bound to the exact source PDF by SHA-256.

    Only notes/highlights and annotation edits can be replayed. Added annotation
    IDs are independent of MuPDF xrefs, which can change after undo/reopen.
    """

    def __init__(self, source):
        self.source = Path(source).resolve()
        self.path = Path(str(self.source) + ".spdf-annotations.json")
        self.source_hash = _digest(self.source)
        self._source_stat = self.source.stat()
        self.operations = []
        self.cursor = 0
        self.ids = {}
        self.revision = self.saved_revision = 0
        self._disk_hash = None
        raw = self._read_disk()
        if raw is not None:
            payload = json.loads(raw)
            if (payload.get("format") != "spdf-annotations" or
                    payload.get("version") != 1 or
                    payload.get("source_sha256") != self.source_hash):
                raise ValueError("The annotation file does not match this PDF.")
            operations = payload.get("operations")
            if not isinstance(operations, list) or len(operations) > 100000:
                raise ValueError("Invalid annotation history.")
            self.operations = operations
            self.cursor = len(operations)
            self._disk_hash = hashlib.sha256(raw).hexdigest()

    def _read_disk(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_SIDECAR_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(raw) > MAX_SIDECAR_BYTES:
            raise ValueError("The annotation file is too large.")
        return raw

    @property
    def dirty(self):
        return self.revision != self.saved_revision

    def check_source(self):
        stat = self.source.stat()
        before = self._source_stat
        if (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) != (
                before.st_size, before.st_mtime_ns, before.st_ctime_ns):
            if _digest(self.source) != self.source_hash:
                raise ValueError("The original PDF changed. Reopen it before saving annotations.")
            self._source_stat = stat

    @staticmethod
    def _apply(pdf, operation, ids):
        name = operation["command"]
        if name not in OPERATIONS:
            raise ValueError("Unsupported annotation operation.")
        args = operation["args"]
        index = args["index"]
        if type(index) is not int or not 0 <= index < len(pdf):
            raise ValueError("Invalid annotation page.")
        page = pdf[index]
        if name in ("add_note", "set_note_text") and (
                not isinstance(args.get("text"), str) or len(args["text"]) > 1000000):
            raise ValueError("Invalid note text.")
        if name == "add_note":
            if not all(isinstance(args.get(key), (int, float)) and
                       math.isfinite(args[key]) and abs(args[key]) <= 10000000
                       for key in ("x", "y")):
                raise ValueError("Invalid note position.")
            annot = page.add_text_annot(fitz.Point(args["x"], args["y"]), args["text"])
        elif name == "add_highlight":
            rectangles = args["rects"]
            if not isinstance(rectangles, list) or not 1 <= len(rectangles) <= 10000:
                raise ValueError("Invalid highlight rectangles.")
            for rect in rectangles:
                if (len(rect) != 4 or not all(isinstance(v, (int, float)) and
                        math.isfinite(v) and abs(v) <= 10000000 for v in rect)
                        or rect[2] <= rect[0] or rect[3] <= rect[1]):
                    raise ValueError("Invalid highlight rectangle.")
            annot = page.add_highlight_annot([fitz.Rect(*r) for r in rectangles])
        else:
            target = operation["target"]
            xref = ids[target["id"]] if "id" in target else target["xref"]
            annot = next((a for a in page.annots() if a.xref == xref), None)
            if annot is None:
                raise ValueError("The target annotation no longer exists.")
            if name == "delete_annot":
                page.delete_annot(annot)
                return None
            if annot.type[0] != fitz.PDF_ANNOT_TEXT:
                raise ValueError("Only text notes can have their content edited.")
            annot.set_info(content=args["text"])
            annot.update()
            return None
        annot.update()
        ids[operation["id"]] = annot.xref
        return annot.xref

    def execute(self, pdf, name, args):
        # Normalize and detach coordinates/arguments before recording them.
        args = json.loads(json.dumps(args, allow_nan=False))
        operation = {"command": name, "args": args}
        if name in ("add_note", "add_highlight"):
            operation["id"] = uuid.uuid4().hex
        else:
            xref = args.pop("xref")
            key = next((key for key, value in self.ids.items() if value == xref), None)
            operation["target"] = {"id": key} if key else {"xref": xref}
        result = self._apply(pdf, operation, self.ids)
        self.operations[self.cursor:] = [operation]
        self.cursor += 1
        self.revision += 1
        return result

    def rebuild(self, opener, cursor=None):
        self.check_source()
        cursor = self.cursor if cursor is None else cursor
        if not 0 <= cursor <= len(self.operations):
            raise ValueError("Invalid annotation history position.")
        pdf = opener()
        ids = {}
        try:
            for operation in self.operations[:cursor]:
                self._apply(pdf, operation, ids)
        except Exception:
            pdf.close()
            raise
        self.ids = ids
        if cursor != self.cursor:
            self.cursor = cursor
            self.revision += 1
        return pdf

    def save(self):
        self.check_source()
        payload = {"format": "spdf-annotations", "version": 1,
                   "source_sha256": self.source_hash,
                   "operations": self.operations[:self.cursor]}
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > MAX_SIDECAR_BYTES:
            raise ValueError("The annotation file is too large. Export an annotated PDF.")
        with _write_lock(str(self.path) + ".lock"):
            current = self._read_disk()
            current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
            if current_hash != self._disk_hash:
                raise ValueError("Another window changed the annotations. Export your PDF to keep both versions.")
            self.check_source()
            fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp",
                                              dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self._disk_hash = hashlib.sha256(raw).hexdigest()
            self.saved_revision = self.revision
