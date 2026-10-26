"""Bound image storage to a page-space viewport, preserving the source grid."""

from dataclasses import replace
import math

import pymupdf


def validate_viewport(viewport, page_rect):
    if len(viewport) != 4 or not all(math.isfinite(v) for v in viewport):
        raise ValueError("invalid GPU viewport")
    rect = pymupdf.Rect(viewport) & page_rect
    if rect.is_empty:
        raise ValueError("empty GPU viewport")
    return tuple(rect)


def image_crop(width, height, transform, viewport):
    matrix = pymupdf.Matrix(*transform)
    inverse = pymupdf.Matrix(matrix)
    if inverse.invert():
        return (0, 0, width, height)
    local = pymupdf.Rect(viewport) * inverse
    # Two source texels retain bilinear filtering at every viewport edge.
    x0 = max(0, min(width - 1, math.floor(local.x0 * width) - 2))
    y0 = max(0, min(height - 1, math.floor(local.y0 * height) - 2))
    x1 = max(x0 + 1, min(width, math.ceil(local.x1 * width) + 2))
    y1 = max(y0 + 1, min(height, math.ceil(local.y1 * height) + 2))
    return x0, y0, x1, y1


def crop_pixmap(pixmap, transform, viewport):
    width, height = pixmap.width, pixmap.height
    x0, y0, x1, y1 = image_crop(width, height, transform, viewport)
    if (x0, y0, x1, y1) == (0, 0, width, height):
        return pixmap, None
    box = pymupdf.IRect(x0 + pixmap.x, y0 + pixmap.y,
                       x1 + pixmap.x, y1 + pixmap.y)
    cropped = pymupdf.Pixmap(pixmap.colorspace or pymupdf.mupdf.FzColorspace(), box, pixmap.alpha)
    pymupdf.mupdf.fz_copy_pixmap_rect(
        cropped.this, pixmap.this, pymupdf.mupdf.FzIrect(*box),
        pymupdf.mupdf.FzDefaultColorspaces())
    return cropped, (x0 / width, y0 / height, (x1-x0) / width, (y1-y0) / height)


def cropped_image(item, crops):
    from .gpu_raster import VectorImage
    if not isinstance(item, VectorImage) or item.refresh_key is None:
        return item
    crop = crops.get(id(item.pixels))
    if crop is None:
        return item
    x, y, w, h = crop
    a, b, c, d, e, f = item.transform
    return replace(item, transform=(a*w, b*w, c*h, d*h,
                                   a*x+c*y+e, b*x+d*y+f),
                   source_index=None, refresh_key=None)
