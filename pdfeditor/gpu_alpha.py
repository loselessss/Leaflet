"""Fold a single raster alpha mask into its image before GPU composition.

Filtering premultiplied color differs slightly from filtering color and alpha
separately. Only matching sampling policies are eligible; sharp masks retain
their original composition. No vector mask or live text is rasterized here.
"""
from collections import Counter
from dataclasses import replace
import math

import pymupdf

from .gpu_raster import (ClipPop, ClipPush, MaskBegin, MaskEnd, VectorImage,
                         MAX_GPU_IMAGE_BYTES, _rect_commands, _valid_refresh_key)


def _packed(image):
    return (image.width > 0 and image.height > 0
            and image.stride == image.width * 4
            and len(image.pixels) == image.stride * image.height
            and len(image.pixels) <= MAX_GPU_IMAGE_BYTES)


def _eligible(begin, mask, end, source, pop):
    return (isinstance(begin, MaskBegin) and not begin.luminosity
            and begin.background_argb == 0
            and isinstance(mask, VectorImage) and mask.opacity == 1.0
            and isinstance(end, MaskEnd) and not end.transfer
            and isinstance(source, VectorImage) and isinstance(pop, ClipPop)
            and (mask.width, mask.height, mask.transform, mask.interpolate)
            == (source.width, source.height, source.transform, source.interpolate)
            and _packed(mask) and _packed(source)
            and isinstance(source.transform, (tuple, list)) and len(source.transform) == 6
            and all(math.isfinite(x) for x in source.transform)
            and len(begin.area) == 4 and all(math.isfinite(x) for x in begin.area)
            and begin.area[0] < begin.area[2] and begin.area[1] < begin.area[3])


def _combine(mask, source):
    alpha = mask.pixels[3::4]
    original_alpha = source.pixels[3::4]
    # set_alpha multiplies channels independently without interpreting color.
    # Keep BGRA order in the RGB-labelled container to avoid two swizzle copies.
    pix = pymupdf.Pixmap(pymupdf.csRGB, source.width, source.height,
                         source.pixels, True)
    pix.set_alpha(alpha, premultiply=1)
    pixels = pix.samples
    # set_alpha replaces A; existing premultiplied source alpha must multiply too.
    if original_alpha.count(255) != len(original_alpha):
        out = bytearray(pixels)
        out[3::4] = bytes((a * m + 127) // 255
                         for a, m in zip(original_alpha, alpha))
        pixels = bytes(out)
    key = None
    if (_valid_refresh_key(mask.refresh_key) and mask.refresh_key[0] == "mask"
            and _valid_refresh_key(source.refresh_key) and source.refresh_key[0] == "image"):
        key = ("alpha", (mask.refresh_key, source.refresh_key))
    return replace(source, pixels=pixels, source_index=None, refresh_key=key)


def refine_alpha_image(item, replacements):
    """Rebuild from both original callbacks at the requested source density."""
    mask_key, source_key = item.refresh_key[1]
    mask, source = replacements.get(mask_key), replacements.get(source_key)
    if not isinstance(mask, VectorImage) or not isinstance(source, VectorImage):
        return None
    if (not _packed(mask) or not _packed(source)
            or (mask.width, mask.height, mask.transform, mask.interpolate)
            != (source.width, source.height, source.transform, source.interpolate)
            or source.transform != item.transform or source.interpolate != item.interpolate
            or mask.opacity != 1):
        return None
    return _combine(mask, replace(source, opacity=item.opacity))


def fuse_alpha_images(items, *, abort=None, byte_limit=MAX_GPU_IMAGE_BYTES):
    """Return (items, fused count, unique image bytes), bounded by scene budget.

    Derived bytes belong to this extraction only. A refresh recipe records both
    original callbacks, so zoom refinement cannot substitute an unmasked image.
    Sources without a valid recipe fall back to full extraction when zoomed.
    """
    references = Counter(id(x.pixels) for x in items if isinstance(x, VectorImage))
    sizes = {id(x.pixels): len(x.pixels) for x in items if isinstance(x, VectorImage)}
    image_bytes = sum(sizes.values())
    generated = 0
    out, count, index = [], 0, 0
    while index < len(items):
        if (index % 256 == 0 or isinstance(items[index], MaskBegin)) and abort and abort():
            raise TimeoutError("GPU scene time budget exceeded")
        window = items[index:index + 5]
        if len(window) == 5 and _eligible(*window):
            begin, mask, end, source, pop = window
            removed = Counter((id(mask.pixels), id(source.pixels)))
            saved = sum(sizes[key] for key, n in removed.items() if references[key] == n)
            cost = len(source.pixels)
            # Limit cumulative temporary creation as well as final unique bytes,
            # including repeated uses of shared original images.
            if generated + cost <= byte_limit and image_bytes - saved + cost <= byte_limit:
                try:
                    combined = _combine(mask, source)
                except (ValueError, RuntimeError):
                    combined = None
                if abort and abort():
                    raise TimeoutError("GPU scene time budget exceeded")
                if combined is not None:
                    out.extend((ClipPush(_rect_commands(*begin.area)), combined, pop))
                    references.subtract(removed)
                    image_bytes += cost - saved
                    generated += cost
                    count += 1
                    index += 5
                    continue
        out.append(items[index])
        index += 1
    return tuple(out), count, image_bytes
