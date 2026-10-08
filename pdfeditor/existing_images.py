"""Edit individual direct image placements without replacing shared image data."""

import re
import math
from collections import Counter

import pymupdf as fitz


def _tokens(data):
    """Yield PDF token spans, keeping strings and compound operands opaque."""
    i = 0
    while i < len(data):
        start = i
        char = data[i]
        if char in b"\x00\t\n\x0c\r ":
            i += 1
            continue
        if char == 37:
            while i < len(data) and data[i] not in b"\r\n":
                i += 1
            continue
        if char == 40:
            depth = 1
            i += 1
            while i < len(data) and depth:
                if data[i] == 92:
                    i += 2
                    continue
                if data[i] == 40:
                    depth += 1
                elif data[i] == 41:
                    depth -= 1
                i += 1
            if depth:
                raise ValueError("Unterminated PDF string")
        elif char == 60 and data[i:i + 2] != b"<<":
            end = data.find(b">", i + 1)
            if end < 0:
                raise ValueError("Unterminated PDF hex string")
            i = end + 1
        elif data[i:i + 2] in (b"<<", b">>"):
            i += 2
        elif char in b"[]{}":
            i += 1
        else:
            i += 1
            while i < len(data) and data[i] not in b"\x00\t\n\x0c\r ()<>[]{}/%":
                i += 1
        yield data[start:i], start, i


def placements(document, page_index, excluded):
    try:
        return _placements(document, page_index, excluded)
    except (ValueError, RuntimeError, TypeError, OverflowError, ZeroDivisionError):
        return []


def _placements(document, page_index, excluded):
    page = document._doc[page_index]
    page_matrix = page.transformation_matrix
    if page.rotation:
        # PyMuPDF's rotated-page matrix omits the CropBox offset. Object
        # coordinates stay unrotated, just like get_image_info() coordinates.
        bounds = page.rect * page.derotation_matrix
        crop = page.cropbox
        sx, sy = bounds.width / crop.width, bounds.height / crop.height
        page_matrix = fitz.Matrix(sx, 0, 0, -sy, -crop.x0 * sx,
                                  (page.mediabox.y1 - crop.y0) * sy)
    names = {entry[7]: entry[0] for entry in page.get_images(full=True)
             if entry[-1] == 0}
    if not names:
        return []
    matrix = fitz.Matrix(1, 1)
    clipped = False
    stack = []
    result = []
    contents = page.get_contents()
    occurrences = Counter(contents)
    total_bytes = total_tokens = 0
    for content in contents:
        data = document._doc.xref_stream(content)
        total_bytes += len(data)
        if total_bytes > 16 * 1024 * 1024:
            return []
        operands = []
        ordinal = 0
        compound = 0
        try:
            for token, start, end in _tokens(data):
                total_tokens += 1
                if total_tokens > 500000 or token == b"BI":
                    return []  # Inline image bytes must never be interpreted as operators.
                if token in (b"[", b"<<"):
                    compound += 1
                elif token in (b"]", b">>"):
                    compound -= 1
                    if compound < 0:
                        return []
                if compound or token in (b"]", b">>"):
                    operands.clear()
                    continue
                if token.startswith((b"/", b"(", b"<")) or re.fullmatch(rb"[+-]?(?:\d+\.?\d*|\.\d+)", token):
                    operands.append((token, start, end))
                    operands = operands[-6:]
                    continue
                if token == b"q":
                    stack.append((fitz.Matrix(matrix), clipped))
                elif token == b"Q":
                    if not stack:
                        return []
                    matrix, clipped = stack.pop()
                elif token == b"cm":
                    if len(operands) != 6:
                        return []
                    matrix = fitz.Matrix(*(float(t[0]) for t in operands)) * matrix
                elif token in (b"W", b"W*"):
                    clipped = True
                elif token == b"gs":
                    # ExtGState can attach a page-space soft mask. Its scope
                    # must be editable as a group before placements can move.
                    clipped = True
                elif token == b"Tr" and operands and float(operands[-1][0]) >= 4:
                    clipped = True
                elif token == b"Do":
                    if len(operands) != 1 or not operands[0][0].startswith(b"/"):
                        return []
                    name = operands[0][0][1:]
                    name = re.sub(rb"#([0-9a-fA-F]{2})", lambda m: bytes([int(m[1], 16)]), name).decode("latin1")
                    if (content not in excluded and occurrences[content] == 1
                            and name in names and not clipped):
                        rect = fitz.Rect(0, 0, 1, 1) * matrix * page_matrix
                        if (all(math.isfinite(v) and abs(v) < 1e6 for v in rect)
                                and rect.width > .1 and rect.height > .1
                                and abs(matrix.a * matrix.d - matrix.b * matrix.c) > 1e-10):
                            result.append(dict(id=f"existing-image:{content}:{ordinal}", kind="image",
                                               rect=list(rect), content=content, ordinal=ordinal,
                                               start=operands[0][1], end=end, matrix=list(matrix),
                                               existing=True))
                    ordinal += 1
                operands.clear()
        except (ValueError, RuntimeError, OverflowError):
            return []
        if compound:
            return []
    return result if not stack else []


def edit(document, page_index, item, rect=None):
    pdf = document._doc
    page = pdf[page_index]
    data = pdf.xref_stream(item["content"])
    replacement = b"\n"
    if rect is not None:
        inverse = ~page.transformation_matrix
        source = fitz.Rect(item["rect"]) * inverse
        target = fitz.Rect(rect) * inverse
        sx, sy = target.width / source.width, target.height / source.height
        delta = fitz.Matrix(sx, 0, 0, sy, target.x0 - sx * source.x0, target.y0 - sy * source.y0)
        current = fitz.Matrix(item["matrix"])
        local = current * delta * ~current
        values = " ".join(f"{value:.10f}" for value in local).encode("ascii")
        replacement = b"\nq\n" + values + b" cm\n" + data[item["start"]:item["end"]] + b"\nQ\n"
    # A content stream may be shared by other pages. Always copy before editing.
    content = pdf.get_new_xref()
    pdf.update_object(content, "<<>>")
    pdf.update_stream(content, data[:item["start"]] + replacement + data[item["end"]:])
    refs = [content if x == item["content"] else x for x in page.get_contents()]
    pdf.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in refs) + "]")
    document.invalidate_render()
    return f"existing-image:{content}:{item['ordinal']}"
