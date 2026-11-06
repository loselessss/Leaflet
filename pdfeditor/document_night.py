"""Adaptive, display-only document colors; analysis uses existing small previews."""
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import math
import os

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap

ANALYSIS_EDGE = 512
CPU_CACHE_BYTES = 16 * 1024 * 1024


def _rgba(image):
    import numpy as np
    image = image.convertToFormat(QImage.Format_RGBA8888)
    data = image.constBits().asstring(image.byteCount())
    return np.frombuffer(data, np.uint8).reshape(image.height(), image.bytesPerLine())[
        :, :image.width()*4].reshape(image.height(), image.width(), 4)


def _tone(rgb):
    """Night ink/paper reference, including color-text antialias compensation."""
    import numpy as np
    luminance = np.clip(np.sum(rgb * np.array([.2126, .7152, .0722], np.float32),
        axis=-1, keepdims=True), 0., 1.)
    chroma = np.max(rgb, axis=-1, keepdims=True)-np.min(rgb, axis=-1, keepdims=True)
    white = np.min(rgb, axis=-1, keepdims=True)
    ink = np.maximum(1.-white, 1e-6)
    colored = np.clip((chroma/ink-.06)/.19, 0., 1.)
    colored = colored*colored*(3.-2.*colored)
    target = .12 + .76*np.power(1.-luminance, .8)
    brighter = rgb+(1.-rgb)*(target-luminance)/np.maximum(1.-luminance, 1e-6)
    darker = rgb*target/np.maximum(luminance, 1e-6)
    mapped = np.where(target >= luminance, brighter, darker)
    color = np.minimum(1., (rgb-white)/ink*1.3)*ink+white*.12
    return np.clip(mapped+(color-mapped)*colored, 0., 1.)


@lru_cache(maxsize=1)
def _native_library():
    if os.name != 'nt':
        return None
    from .d2d_backend import _load_library, _library_path
    try:
        return _load_library(_library_path())
    except (OSError, RuntimeError):
        return None


@lru_cache(maxsize=1)
def _native_pixels():
    import ctypes
    function = getattr(_native_library(), 'spdf_document_night_pixels', None)
    if function is not None:
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        function.restype = ctypes.c_int32
    return function


@lru_cache(maxsize=1)
def _native_mask():
    import ctypes
    function = getattr(_native_library(), 'spdf_document_night_mask', None)
    if function is not None:
        function.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                             ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        function.restype = ctypes.c_int32
    return function


@dataclass(eq=False)
class NightPlan:
    mask: QPixmap
    alpha: bytes
    width: int
    height: int
    page_size: tuple


def build_plan(preview, page_size, image_regions=()):
    """Conservatively leave pictures, dark pages and dense non-paper areas alone."""
    from PIL import Image, ImageDraw, ImageFilter
    image = preview.toImage().scaled(ANALYSIS_EDGE, ANALYSIS_EDGE,
        Qt.KeepAspectRatio, Qt.SmoothTransformation)
    width, height = image.width(), image.height()
    native = _native_mask()
    if native is not None:
        import ctypes
        source = image.convertToFormat(QImage.Format_ARGB32)
        coverage = (ctypes.c_ubyte*(width*height))()
        flags = ctypes.c_uint32()
        status = native(int(source.constBits()), width, height, source.bytesPerLine(), coverage, ctypes.byref(flags))
        if status != 0:
            return None
        scan_like = bool(flags.value & 1)
        alpha = Image.frombytes('L', (width, height), bytes(coverage))
    else:
        import numpy as np
        rgb = _rgba(image)[..., :3].astype(np.float32)/255.
        luminance = rgb.mean(axis=-1)
        chroma = rgb.max(axis=-1)-rgb.min(axis=-1)
        paper = (luminance > .78) & (chroma < .18)
        border = np.concatenate((luminance[0], luminance[-1], luminance[:, 0], luminance[:, -1]))
        if paper.mean() < .03 or (paper.mean() < .25 and np.median(border) < .5):
            return None
        radius = max(2, round(min(width, height)*.012))
        local = np.asarray(Image.fromarray(paper.astype(np.uint8)*255).filter(ImageFilter.BoxBlur(radius)))
        # Remove narrow text-shaped holes from the conservative fallback mask.
        field = Image.fromarray((local < 140).astype(np.uint8)*255)
        field = field.filter(ImageFilter.MinFilter(17)).filter(ImageFilter.MaxFilter(17))
        alpha = Image.fromarray(255-np.asarray(field))
        scan_like = (paper.mean() > .55 and (chroma > .18).mean() < .02 and
                     ((luminance > .15) & (luminance < .78)).mean() < .15)
    painter = ImageDraw.Draw(alpha)
    page_width, page_height = page_size
    for left, top, right, bottom in image_regions:
        if not all(math.isfinite(v) for v in (left, top, right, bottom)):
            continue
        left, top = max(0., left), max(0., top)
        right, bottom = min(page_width, right), min(page_height, bottom)
        if right <= left or bottom <= top:
            continue
        if (right-left)*(bottom-top) > page_width*page_height*.85 and scan_like:
            continue
        bounds = (round(left/page_width*width), round(top/page_height*height),
                  round(right/page_width*width)-1, round(bottom/page_height*height)-1)
        if bounds[2] >= bounds[0] and bounds[3] >= bounds[1]:
            painter.rectangle(bounds, fill=0)
    alpha_bytes = alpha.tobytes()
    if not alpha.getbbox():
        return None
    # The GPU effect uses only coverage alpha; Qt converts it without a pixel loop.
    mask = QImage(alpha_bytes, width, height, width, QImage.Format_Alpha8).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    return NightPlan(QPixmap.fromImage(mask), alpha_bytes, width, height, tuple(page_size))


class NightDisplay:
    def __init__(self):
        self.plans = OrderedDict()
        self.pixmaps = OrderedDict()
        self.pixmap_bytes = 0

    def plan(self, document, page, preview, page_size):
        key = (document, document.render_generation, page, preview.cacheKey())
        if key not in self.plans:
            try:
                regions = document.display_image_regions(page)
                plan = build_plan(preview, page_size, regions)
            except (RuntimeError, ValueError, OverflowError):
                plan = None  # Uncertain classification keeps the reference appearance.
            self.plans[key] = plan
            while len(self.plans) > 8:
                self.plans.popitem(last=False)
        self.plans.move_to_end(key)
        return self.plans[key]

    def pixmap(self, source, region, plan):
        from PIL import Image
        if plan is None:
            return source
        key = source.cacheKey(), tuple(region), plan
        if key in self.pixmaps:
            self.pixmaps.move_to_end(key)
            return self.pixmaps[key]
        left, top, right, bottom = region
        width, height = source.width(), source.height()
        sx, sy = plan.width/plan.page_size[0], plan.height/plan.page_size[1]
        mask = Image.frombytes('L', (plan.width, plan.height), plan.alpha).transform(
            (width, height), Image.Transform.AFFINE,
            ((right-left)*sx/width, 0, left*sx, 0, (bottom-top)*sy/height, top*sy),
            resample=Image.Resampling.BILINEAR)
        native = _native_pixels()
        if native is not None:
            import ctypes
            image = source.toImage().convertToFormat(QImage.Format_ARGB32)
            output = QImage(width, height, QImage.Format_ARGB32)
            coverage = mask.tobytes()
            status = native(int(image.constBits()), width, height, image.bytesPerLine(),
                ctypes.c_char_p(coverage), int(output.bits()), output.bytesPerLine())
            if status < 0:
                raise RuntimeError('native document color transform failed')
            result = QPixmap.fromImage(output)
        else:
            import numpy as np
            weight = np.asarray(mask).astype(np.float32)[..., None]/255.
            rgba = _rgba(source.toImage()).copy()
            rgb = rgba[..., :3].astype(np.float32)/255.
            rgba[..., :3] = np.rint((rgb+(_tone(rgb)-rgb)*weight)*255).astype(np.uint8)
            image = QImage(rgba.tobytes(), width, height, width*4, QImage.Format_RGBA8888).copy()
            result = QPixmap.fromImage(image)
        cost = width*height*4
        if cost <= CPU_CACHE_BYTES:
            while self.pixmaps and self.pixmap_bytes+cost > CPU_CACHE_BYTES:
                _key, old_result = self.pixmaps.popitem(last=False)
                self.pixmap_bytes -= old_result.width()*old_result.height()*4
            self.pixmaps[key] = result
            self.pixmap_bytes += cost
        return result
