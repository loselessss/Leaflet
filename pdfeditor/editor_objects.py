"""Editable sPDF-owned page content. Never infer objects from arbitrary PDF paths.

PDF references (not integer xrefs inside JSON) survive garbage collection on save.
Each object keeps an immutable original stream and a separately transformed stream.
"""

import hashlib
import json
import math
import re
import uuid
from contextlib import contextmanager

import fitz


def _refs(pdf, xref, key):
    kind, value = pdf.xref_get_key(xref, key)
    if kind not in ("array", "xref"):
        return []
    return [int(x) for x in re.findall(r"(\d+) 0 R", value)]


def _rect(value):
    values = tuple(float(x) for x in value)
    if len(values) != 4 or not all(math.isfinite(x) and abs(x) < 1e6 for x in values):
        raise ValueError("Invalid object coordinates.")
    rect = fitz.Rect(values)
    if rect.width < .1 or rect.height < .1:
        raise ValueError("Object width and height must be positive.")
    return rect


def objects(document, page_index):
    """Return validated objects for one page; foreign/stale metadata is ignored."""
    pdf = document._doc
    page = pdf[page_index]
    contents = set(page.get_contents())
    result = []
    for xref in _refs(pdf, page.xref, "SPDFObjects")[:10000]:
        try:
            kind, data = pdf.xref_get_key(xref, "Data")
            if kind != "string" or len(data) > 8192:
                continue
            item = json.loads(data)
            if item["version"] != 1 or item["kind"] not in ("rectangle", "image"):
                continue
            _rect(item["rect"])
            _rect(item["original_rect"])
            if item["cropbox"] != list(page.cropbox) or item["mediabox"] != list(page.mediabox):
                continue
            content, = _refs(pdf, xref, "Content")
            original, = _refs(pdf, xref, "Original")
            if content not in contents or not pdf.xref_is_stream(original):
                continue
            if hashlib.sha256(pdf.xref_stream(content)).hexdigest() != item["digest"]:
                continue
            if hashlib.sha256(pdf.xref_stream(original)).hexdigest() != item["original_digest"]:
                continue
            item.update(xref=xref, content=content, original=original)
            result.append(item)
        except (ValueError, TypeError, KeyError, RuntimeError):
            continue
    return result


def _write_data(pdf, item):
    data = {key: value for key, value in item.items()
            if key not in ("xref", "content", "original")}
    pdf.xref_set_key(item["xref"], "Data", fitz.get_pdf_str(json.dumps(data)))


@contextmanager
def _unrotated(document, page_index):
    document.ensure_editable()
    page = document._doc[page_index]
    rotation = page.rotation
    try:
        if rotation:
            page.set_rotation(0)
        yield
    finally:
        if rotation:
            page.set_rotation(rotation)


def create(document, page_index, kind, rect, *, image=None):
    with _unrotated(document, page_index):
        return _create(document, page_index, kind, rect, image=image)


def _create(document, page_index, kind, rect, *, image=None):
    document.ensure_editable()
    rect = _rect(rect)
    if kind not in ("rectangle", "image"):
        raise ValueError("Unsupported object type.")
    if kind == "image" and not image:
        raise ValueError("An image is required.")
    pdf = document._doc
    page = pdf[page_index]
    # Isolate unbalanced graphics state in pre-existing content.
    page.wrap_contents()
    previous = set(page.get_contents())
    if kind == "rectangle":
        page.draw_rect(rect, color=(.16, .32, .65), fill=(.84, .9, 1), width=1)
    else:
        page.insert_image(rect, stream=image, keep_proportion=False)
    content, = set(page.get_contents()) - previous
    stream = pdf.xref_stream(content)
    original = pdf.get_new_xref()
    pdf.update_object(original, "<<>>")
    pdf.update_stream(original, stream)
    xref = pdf.get_new_xref()
    pdf.update_object(xref, f"<< /Type /SPDFObject /Content {content} 0 R /Original {original} 0 R >>")
    item = dict(version=1, id=uuid.uuid4().hex, kind=kind,
                rect=list(rect), original_rect=list(rect),
                cropbox=list(page.cropbox), mediabox=list(page.mediabox),
                digest=hashlib.sha256(stream).hexdigest(),
                original_digest=hashlib.sha256(stream).hexdigest(),
                xref=xref, content=content, original=original)
    _write_data(pdf, item)
    refs = _refs(pdf, page.xref, "SPDFObjects") + [xref]
    pdf.xref_set_key(page.xref, "SPDFObjects", "[" + " ".join(f"{x} 0 R" for x in refs) + "]")
    document.invalidate_render()
    return item["id"]


def transform(document, page_index, object_id, rect):
    with _unrotated(document, page_index):
        _transform(document, page_index, object_id, rect)


def _transform(document, page_index, object_id, rect):
    document.ensure_editable()
    rect = _rect(rect)
    item = next((x for x in objects(document, page_index) if x["id"] == object_id), None)
    if item is None:
        raise ValueError("The object is no longer editable.")
    pdf = document._doc
    page = pdf[page_index]
    # Model coordinates are unrotated MuPDF page coordinates, including CropBox.
    inverse = ~page.transformation_matrix
    source = fitz.Rect(item["original_rect"]) * inverse
    target = rect * inverse
    sx, sy = target.width / source.width, target.height / source.height
    tx, ty = target.x0 - sx * source.x0, target.y0 - sy * source.y0
    prefix = f"q\n{sx:.10f} 0 0 {sy:.10f} {tx:.10f} {ty:.10f} cm\n".encode("ascii")
    stream = prefix + pdf.xref_stream(item["original"]) + b"\nQ\n"
    pdf.update_stream(item["content"], stream)
    item["rect"] = list(rect)
    item["digest"] = hashlib.sha256(stream).hexdigest()
    _write_data(pdf, item)
    document.invalidate_render()


def delete(document, page_index, object_id):
    document.ensure_editable()
    pdf = document._doc
    page = pdf[page_index]
    item = next((x for x in objects(document, page_index) if x["id"] == object_id), None)
    if item is None:
        raise ValueError("The object is no longer editable.")
    pdf.update_stream(item["content"], b"")
    refs = [x for x in _refs(pdf, page.xref, "SPDFObjects") if x != item["xref"]]
    pdf.xref_set_key(page.xref, "SPDFObjects", "[" + " ".join(f"{x} 0 R" for x in refs) + "]")
    document.invalidate_render()
