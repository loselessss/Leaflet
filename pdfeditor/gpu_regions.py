"""Compile small, expensive isolated illustrations before expanding geometry.

Only a bounded candidate subtree is recorded. Its own transparent source is
rasterized in place, so enclosing clips, backdrop and later text remain GPU
operations. No page crops or cross-job output cache are created here.
"""

import math

import pymupdf
from pymupdf import mupdf as _mupdf


MIN_REGION_OPERATIONS = 128
MAX_REGION_OPERATIONS = 65536
MAX_REGION_COUNT = 64
MAX_REGION_BYTES = 8 * 1024 * 1024
MAX_REGION_PAGE_FRACTION = .005
REGION_OVERSAMPLE = 2.0

_OPERATIONS = (
    "fill_path", "stroke_path", "clip_path", "pop_clip", "fill_text",
    "stroke_text", "clip_text", "clip_stroke_text", "clip_stroke_path",
    "fill_image", "fill_image_mask", "clip_image_mask", "fill_shade",
    "begin_mask", "end_mask", "begin_group", "end_group", "begin_tile",
    "end_tile",
)


class RegionDevice(_mupdf.FzDevice2):
    def __init__(self, recorder):
        super().__init__()
        for name in _OPERATIONS:
            getattr(self, "use_virtual_" + name)()
        self.recorder = recorder
        self.capture = None
        self.region_count = 0
        self.region_bytes = 0
        self.calls = 0

    def _eligible(self, area, isolated, knockout, mode, alpha):
        box = (float(area.x0), float(area.y0), float(area.x1), float(area.y1))
        page = self.recorder._page_rect
        page_area = (page[2] - page[0]) * (page[3] - page[1])
        if (not isolated or not knockout or mode != 0 or alpha != 1
                or self.recorder._mask_depth or self.recorder._tile_stack
                or self.region_count >= MAX_REGION_COUNT
                or not all(math.isfinite(v) for v in box) or page_area <= 0):
            return False
        area = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
        scale = self.recorder._raster_scale * REGION_OVERSAMPLE
        cost = (math.ceil((box[2] - box[0]) * scale) + 4) * (
            math.ceil((box[3] - box[1]) * scale) + 4) * 4
        from .gpu_raster import MAX_GPU_IMAGE_BYTES
        return (0 < area <= page_area * MAX_REGION_PAGE_FRACTION
                and cost <= MAX_REGION_BYTES - self.region_bytes
                and cost <= MAX_GPU_IMAGE_BYTES - self.recorder._image_bytes)

    def _record(self, name, args):
        capture = self.capture
        capture["operations"] += 1
        if capture["operations"] > MAX_REGION_OPERATIONS:
            self.recorder._set_failure("complex illustration operation limit exceeded")
            if self.recorder._cookie is not None:
                self.recorder._cookie.set_abort()
            return 0
        if name in ("fill_text", "stroke_text", "clip_text", "clip_stroke_text",
                    "begin_tile"):
            # Preserve live text outlines and the existing tile semantics.
            capture["keep_vector"] = True
        if name in ("fill_image", "fill_image_mask", "clip_image_mask"):
            capture["images"][name] += 1
        if name == "begin_tile":
            return _mupdf.ll_fz_begin_tile_id(capture["device"].m_internal, *args[:-1])
        if name == "fill_text":
            # PyMuPDF replaces its public ll_fz_fill_text helper with a
            # sequence-taking overload; callbacks lend a native float pointer.
            return _mupdf._mupdf.ll_fz_fill_text(capture["device"].m_internal, *args)
        function = "end_mask_tr" if name == "end_mask" else name
        return getattr(_mupdf, "ll_fz_" + function)(capture["device"].m_internal, *args)

    def _call(self, name, context, args):
        self.calls += 1
        if self.recorder.failure:
            return 0
        if (self.calls & 63) == 0 and self.recorder._abort_if_expired():
            return 0
        try:
            if name == "begin_group":
                if self.capture is not None:
                    self.capture["depth"] += 1
                elif self._eligible(args[0], args[2], args[3], args[4], args[5]):
                    area = args[0]
                    listing = _mupdf.fz_new_display_list(_mupdf.FzRect(area))
                    self.capture = {
                        "list": listing, "device": _mupdf.fz_new_list_device(listing),
                        "bbox": (area.x0, area.y0, area.x1, area.y1),
                        "depth": 1, "operations": 0, "keep_vector": False,
                        "images": dict.fromkeys(("fill_image", "fill_image_mask", "clip_image_mask"), 0),
                    }
            if self.capture is not None:
                result = self._record(name, args)
                if name == "end_group":
                    self.capture["depth"] -= 1
                    if not self.capture["depth"]:
                        self._finish()
                return result or 0
            return getattr(self.recorder, name)(context, *args) or 0
        except Exception as error:
            self.recorder._set_failure("complex illustration: " + str(error))
            if self.recorder._cookie is not None:
                self.recorder._cookie.set_abort()
            return 0

    def _finish(self):
        capture, self.capture = self.capture, None
        _mupdf.fz_close_device(capture["device"])
        if self.recorder.failure:
            return
        if not capture["keep_vector"] and capture["operations"] >= MIN_REGION_OPERATIONS:
            image = self._rasterize(capture)
            if image is not None:
                if not self.recorder._append_item(image):
                    return
                self.region_count += 1
                self.region_bytes += len(image.pixels)
                self.recorder._image_bytes += len(image.pixels)
                self.recorder._source_image_index += capture["images"]["fill_image"]
                self.recorder._stencil_source_index += capture["images"]["fill_image_mask"]
                self.recorder._mask_source_index += capture["images"]["clip_image_mask"]
                self.recorder._features.update(("complex-illustration", "image", "image-downsample"))
                return
        # Cheap/sensitive candidates keep the original operations and state.
        _mupdf.fz_run_display_list(
            capture["list"], self.recorder, _mupdf.FzMatrix(),
            _mupdf.FzRect(_mupdf.FzRect.Fixed_INFINITE), self.recorder._cookie or _mupdf.FzCookie())

    def _rasterize(self, capture):
        from .gpu_raster import MAX_GPU_IMAGE_BYTES, VectorImage
        if self.recorder._abort_if_expired():
            return None
        scale = self.recorder._raster_scale * REGION_OVERSAMPLE
        x0, y0, x1, y1 = capture["bbox"]
        left, top = math.floor(x0 * scale) - 1, math.floor(y0 * scale) - 1
        right, bottom = math.ceil(x1 * scale) + 1, math.ceil(y1 * scale) + 1
        width, height = right - left, bottom - top
        cost = width * height * 4
        if (width <= 0 or height <= 0 or cost > MAX_REGION_BYTES - self.region_bytes
                or cost > MAX_GPU_IMAGE_BYTES - self.recorder._image_bytes):
            return None
        pixmap = _mupdf.fz_new_pixmap_with_bbox(
            _mupdf.fz_device_rgb(), _mupdf.FzIrect(left, top, right, bottom),
            _mupdf.FzSeparations(), 1)
        _mupdf.fz_clear_pixmap(pixmap)
        device = _mupdf.fz_new_draw_device(_mupdf.FzMatrix(), pixmap)
        try:
            _mupdf.fz_run_display_list(
                capture["list"], device, _mupdf.FzMatrix(scale, 0, 0, scale, 0, 0),
                _mupdf.FzRect(left, top, right, bottom), self.recorder._cookie or _mupdf.FzCookie())
        finally:
            _mupdf.fz_close_device(device)
        if self.recorder._abort_if_expired():
            return None
        samples = pymupdf.Pixmap(pixmap).samples
        # Draw-device RGBA is already premultiplied. Swizzle without applying
        # alpha a second time; the existing image decoder accepts straight RGBA.
        bgra = bytearray(cost)
        for target, source in ((0, 2), (1, 1), (2, 0), (3, 3)):
            bgra[target::4] = samples[source::4]
        return VectorImage(bytes(bgra), width, height, width * 4,
                           (width / scale, 0, 0, height / scale, left / scale, top / scale))

    def dispose(self):
        if self.capture is not None:
            capture, self.capture = self.capture, None
            try:
                _mupdf.fz_close_device(capture["device"])
            except RuntimeError:
                pass


def _forward(name):
    def callback(self, context, *args):
        return self._call(name, context, args)
    return callback


for _name in _OPERATIONS:
    setattr(RegionDevice, _name, _forward(_name))
