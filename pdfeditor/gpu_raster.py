"""Conservative MuPDF display-list to Direct2D scene conversion.

MuPDF remains the PDF parser and supplies exact glyph outlines and decoded
images. Direct2D rasterizes supported drawing commands. Unsupported effects
fall back to the existing PyMuPDF tile path unless a self-contained effect can
be rasterized as a bounded image island.
"""

from dataclasses import dataclass, replace
import ctypes
import math
import struct
import time

import pymupdf
from pymupdf import mupdf as _mupdf


MAX_GPU_IMAGE_BYTES = 64 * 1024 * 1024
MAX_GPU_SCENE_ITEMS = 50000
SHADE_RASTER_SCALE = 2.0
LINEAR_SHADE_STEPS = 64
GPU_IMAGE_DOWNSAMPLE_OVERSAMPLE = 1.0
CPU_ISLAND_BBOX_PAD = 2.0
MAX_CPU_ISLAND_PAGE_COVERAGE = 0.85
MAX_APPROXIMATE_CPU_ISLAND_PAGE_COVERAGE = 0.15
MAX_MERGED_FILL_PATH_COMMANDS = 8192
AGGRESSIVE_BAND_COLOR_TOLERANCE = 12
UNIT_RECT_COMMANDS = (
    ("move", 0.0, 0.0),
    ("line", 1.0, 0.0),
    ("line", 1.0, 1.0),
    ("line", 0.0, 1.0),
    ("close",),
)
FZ_LINEAR_SHADE = 2
FZ_RADIAL_SHADE = 3
FZ_LINEAR_SHADE_UNION_OFFSET = 224
GLYPH_ENCODERS = ("fz_encode_character", "fz_encode_character_sc")
GPU_SCENE_PROBE_OPERATIONS = (
    "fill_path", "stroke_path", "clip_path", "pop_clip",
    "fill_text", "stroke_text", "clip_text", "clip_stroke_text",
    "clip_stroke_path", "fill_image", "fill_image_mask",
    "clip_image_mask", "fill_shade", "begin_mask", "end_mask",
    "begin_group", "end_group", "begin_tile", "end_tile",
)


@dataclass(frozen=True)
class VectorPath:
    commands: tuple
    even_odd: bool = False
    fill_argb: int = None
    stroke_argb: int = None
    stroke_width: float = 1.0
    stroke_style: tuple = None
    transform: tuple = None
    groupable: bool = False
    shading: bool = False


@dataclass(frozen=True)
class VectorImage:
    pixels: bytes
    width: int
    height: int
    stride: int
    transform: tuple
    opacity: float = 1.0
    interpolate: bool = True
    source_index: int = None


@dataclass(frozen=True)
class VectorLinearGradient:
    commands: tuple
    start: tuple
    end: tuple
    stops: tuple
    even_odd: bool = False
    transform: tuple = None


@dataclass(frozen=True)
class VectorRadialGradient:
    commands: tuple
    center: tuple
    origin: tuple
    radius: tuple
    stops: tuple
    even_odd: bool = False
    transform: tuple = None


@dataclass(frozen=True)
class ClipPush:
    commands: tuple
    even_odd: bool = False
    transform: tuple = None


@dataclass(frozen=True)
class ClipStrokePush:
    commands: tuple
    stroke_width: float
    stroke_style: tuple = None
    transform: tuple = None


@dataclass(frozen=True)
class ClipPop:
    pass


@dataclass(frozen=True)
class GroupPush:
    opacity: float
    blend_mode: int = 0
    isolated: bool = True
    knockout: bool = False


@dataclass(frozen=True)
class GroupPop:
    pass


@dataclass(frozen=True)
class MaskBegin:
    area: tuple
    luminosity: bool
    background_argb: int


@dataclass(frozen=True)
class MaskEnd:
    transfer: tuple = ()


@dataclass(frozen=True)
class VectorPage:
    supported: bool
    paths: tuple = ()
    reason: str = ""
    items: tuple = ()
    features: tuple = ()
    raster_scale: float = 1.0

    @property
    def drawables(self):
        return self.items or self.paths


@dataclass(frozen=True)
class _TileState:
    start: int
    area: tuple
    view: tuple
    xstep: float
    ystep: float
    ctm: tuple


class _PathWalker(_mupdf.FzPathWalker2):
    def __init__(self):
        super().__init__()
        self.use_virtual_moveto()
        self.use_virtual_lineto()
        self.use_virtual_curveto()
        self.use_virtual_closepath()
        self.commands = []

    def moveto(self, _context, x, y):
        self.commands.append(("move", float(x), float(y)))

    def lineto(self, _context, x, y):
        self.commands.append(("line", float(x), float(y)))

    def curveto(self, _context, x1, y1, x2, y2, x3, y3):
        self.commands.append((
            "cubic", float(x1), float(y1), float(x2), float(y2),
            float(x3), float(y3)))

    def closepath(self, _context):
        self.commands.append(("close",))


class _SceneProbeDevice(_mupdf.FzDevice2):
    """Count display-list complexity without decoding or walking resources."""

    def __init__(self):
        super().__init__()
        for name in GPU_SCENE_PROBE_OPERATIONS:
            getattr(self, "use_virtual_" + name)()
        self.score = 0
        self.operations = 0

    def _hit(self, weight=1):
        self.operations += 1
        self.score += weight

    def fill_path(self, *_args):
        self._hit()

    def stroke_path(self, *_args):
        self._hit()

    def clip_path(self, *_args):
        self._hit()

    def pop_clip(self, *_args):
        self._hit()

    def fill_text(self, *_args):
        self._hit(8)

    def stroke_text(self, *_args):
        self._hit(8)

    def clip_text(self, *_args):
        self._hit(8)

    def clip_stroke_text(self, *_args):
        self._hit(8)

    def clip_stroke_path(self, *_args):
        self._hit()

    def fill_image(self, *_args):
        self._hit(4)

    def fill_image_mask(self, *_args):
        self._hit(4)

    def clip_image_mask(self, *_args):
        self._hit(4)

    def fill_shade(self, *_args):
        self._hit(8)

    def begin_mask(self, *_args):
        self._hit(8)

    def end_mask(self, *_args):
        self._hit()

    def begin_group(self, *_args):
        self._hit(8)

    def end_group(self, *_args):
        self._hit()

    def begin_tile(self, *_args):
        self._hit(8)
        return 0

    def end_tile(self, *_args):
        self._hit()


def probe_gpu_scene_complexity(page):
    """Return ``(weighted score, operations)`` from a cheap full-page pass."""
    cookie = _mupdf.FzCookie()
    device = _SceneProbeDevice()
    try:
        _mupdf.fz_run_page(page.this, device, _mupdf.FzMatrix(), cookie)
        return device.score, device.operations
    finally:
        _mupdf.fz_close_device(device)


def _path_commands(path, *, allow_empty=False):
    walker = _PathWalker()
    if isinstance(path, _mupdf.FzPath):
        resource = path
    else:
        resource = _mupdf.FzPath(path)
        resource.thisown = False
    _mupdf.fz_walk_path(resource, walker, walker.m_internal)
    if not walker.commands and not allow_empty:
        raise ValueError("empty vector path")
    return tuple(walker.commands)


def _is_invisible_text_codepoint(ucs):
    try:
        char = chr(int(ucs))
    except (OverflowError, ValueError):
        return False
    if char.isspace():
        return True
    return int(ucs) in {
        0x00ad,  # soft hyphen
        0x200b,  # zero width space
        0x200c,  # zero width non-joiner
        0x200d,  # zero width joiner
        0xfeff,  # zero width no-break space / BOM
    }


def _encoded_glyph_id(font, ucs):
    try:
        codepoint = int(ucs)
    except (OverflowError, ValueError, TypeError):
        return -1
    for encoder_name in GLYPH_ENCODERS:
        encoder = getattr(font, encoder_name, None)
        if encoder is None:
            continue
        try:
            gid = int(encoder(codepoint))
        except (RuntimeError, TypeError, ValueError, OverflowError):
            continue
        if gid > 0:
            return gid
    return -1


def _matrix(value):
    matrix = value if isinstance(value, _mupdf.FzMatrix) else _mupdf.FzMatrix(value)
    return (float(matrix.a), float(matrix.b), float(matrix.c),
            float(matrix.d), float(matrix.e), float(matrix.f))


def _raw_matrix(value):
    try:
        return (float(value.a), float(value.b), float(value.c),
                float(value.d), float(value.e), float(value.f))
    except AttributeError:
        return _matrix(value)


def _concat_matrices(first, second):
    a, b, c, d, e, f = first
    g, h, i, j, k, l = second
    return (
        a * g + b * i,
        a * h + b * j,
        c * g + d * i,
        c * h + d * j,
        e * g + f * i + k,
        e * h + f * j + l)


def _invert_matrix(transform):
    a, b, c, d, e, f = transform
    determinant = a * d - b * c
    if abs(determinant) < 1e-12:
        raise ValueError("non-invertible pattern matrix")
    return (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant)


def _transform_point(transform, x, y):
    a, b, c, d, e, f = transform
    return (a * x + c * y + e, b * x + d * y + f)


def _rect_commands(x0, y0, x1, y1):
    return (
        ("move", float(x0), float(y0)),
        ("line", float(x1), float(y0)),
        ("line", float(x1), float(y1)),
        ("line", float(x0), float(y1)),
        ("close",))


def _rect_tuple(rect):
    return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))


def _translate_commands(commands, dx, dy):
    translated = []
    for command in commands:
        kind = command[0]
        if kind == "close":
            translated.append(command)
            continue
        values = list(command[1:])
        for index in range(0, len(values), 2):
            values[index] = float(values[index]) + dx
            values[index + 1] = float(values[index + 1]) + dy
        translated.append((kind, *values))
    return tuple(translated)


def _image_downsample_factor(width, height, transform, raster_scale=1.0):
    a, b, c, d, _e, _f = _matrix(transform)
    scale = max(1.0, float(raster_scale))
    target_width = max(
        1, math.ceil(math.hypot(a, b) * scale *
                     GPU_IMAGE_DOWNSAMPLE_OVERSAMPLE))
    target_height = max(
        1, math.ceil(math.hypot(c, d) * scale *
                     GPU_IMAGE_DOWNSAMPLE_OVERSAMPLE))
    factor = 0
    while width // (2 ** (factor + 1)) >= target_width and \
            height // (2 ** (factor + 1)) >= target_height:
        factor += 1
    return factor


def _downsampled_size(width, height, factor):
    divisor = 2 ** factor
    return (max(1, math.ceil(width / divisor)),
            max(1, math.ceil(height / divisor)))


def _transform_commands(commands, transform):
    a, b, c, d, e, f = transform

    def point(x, y):
        return (a * x + c * y + e, b * x + d * y + f)

    transformed = []
    for command in commands:
        kind = command[0]
        if kind == "close":
            transformed.append(command)
            continue
        if kind in ("move", "line"):
            transformed.append((kind, *point(command[1], command[2])))
            continue
        if kind == "cubic":
            transformed.append((
                kind,
                *point(command[1], command[2]),
                *point(command[3], command[4]),
                *point(command[5], command[6])))
            continue
        raise ValueError("unsupported vector path command")
    return tuple(transformed)


def _commands_bbox(commands, transform=None):
    points = []
    for command in commands:
        kind = command[0]
        if kind == "close":
            continue
        values = command[1:]
        points.extend(
            (float(values[index]), float(values[index + 1]))
            for index in range(0, len(values), 2))
    if not points:
        return None
    if transform is not None:
        points = [_transform_point(transform, x, y) for x, y in points]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _image_mask_area(transform, page_rect):
    bounds = _commands_bbox(UNIT_RECT_COMMANDS, transform)
    page_x0, page_y0, page_x1, page_y1 = page_rect
    area = (
        max(page_x0, bounds[0]), max(page_y0, bounds[1]),
        min(page_x1, bounds[2]), min(page_y1, bounds[3]))
    return area if area[2] > area[0] and area[3] > area[1] else None


def _rect_path_bbox(commands, transform=None):
    if tuple(command[0] for command in commands) != (
            "move", "line", "line", "line", "close"):
        return None
    points = [(float(command[1]), float(command[2]))
              for command in commands[:-1]]
    if transform is not None:
        points = [_transform_point(transform, *point) for point in points]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    box = (min(xs), min(ys), max(xs), max(ys))
    epsilon = 1e-5
    corners = {
        (0 if abs(x - box[0]) <= epsilon else 1,
         0 if abs(y - box[1]) <= epsilon else 1)
        for x, y in points
        if (abs(x - box[0]) <= epsilon or abs(x - box[2]) <= epsilon) and
        (abs(y - box[1]) <= epsilon or abs(y - box[3]) <= epsilon)
    }
    return box if corners == {(0, 0), (0, 1), (1, 0), (1, 1)} else None


def _convex_path_contains_bbox(commands, transform, box):
    polygon = []
    current = None
    for command in commands:
        kind = command[0]
        if kind == "move":
            if polygon:
                return False
            current = (float(command[1]), float(command[2]))
            polygon.append(current)
        elif kind == "line" and current is not None:
            current = (float(command[1]), float(command[2]))
            polygon.append(current)
        elif kind == "cubic" and current is not None:
            start = current
            control1 = (float(command[1]), float(command[2]))
            control2 = (float(command[3]), float(command[4]))
            end = (float(command[5]), float(command[6]))
            for step in range(1, 9):
                t = step / 8.0
                mt = 1.0 - t
                polygon.append((
                    mt ** 3 * start[0] +
                    3.0 * mt ** 2 * t * control1[0] +
                    3.0 * mt * t ** 2 * control2[0] + t ** 3 * end[0],
                    mt ** 3 * start[1] +
                    3.0 * mt ** 2 * t * control1[1] +
                    3.0 * mt * t ** 2 * control2[1] + t ** 3 * end[1]))
            current = end
        elif kind != "close":
            return False
    if len(polygon) < 3:
        return False
    if polygon[-1] == polygon[0]:
        polygon.pop()
    if transform is not None:
        polygon = [_transform_point(transform, *point) for point in polygon]
    corners = ((box[0], box[1]), (box[2], box[1]),
               (box[2], box[3]), (box[0], box[3]))
    epsilon = 1e-5
    for point in corners:
        crosses = []
        for index, first in enumerate(polygon):
            second = polygon[(index + 1) % len(polygon)]
            crosses.append(
                (second[0] - first[0]) * (point[1] - first[1]) -
                (second[1] - first[1]) * (point[0] - first[0]))
        if not (all(value >= -epsilon for value in crosses) or
                all(value <= epsilon for value in crosses)):
            return False
    return True


def _item_bbox(item):
    if isinstance(item, VectorPath):
        box = _commands_bbox(item.commands, item.transform)
        if box is not None and item.stroke_argb is not None:
            pad = max(0.0, float(item.stroke_width)) * 0.5
            return (box[0] - pad, box[1] - pad,
                    box[2] + pad, box[3] + pad)
        return box
    if isinstance(item, VectorImage):
        return _commands_bbox(UNIT_RECT_COMMANDS, item.transform)
    if isinstance(item, (VectorLinearGradient, VectorRadialGradient)):
        return _commands_bbox(item.commands, item.transform)
    return None


def _overlapping(first, second):
    epsilon = 1e-5
    return (
        first[0] < second[2] - epsilon and
        first[2] > second[0] + epsilon and
        first[1] < second[3] - epsilon and
        first[3] > second[1] + epsilon)


def _contains_bbox(outer, inner):
    epsilon = 1e-5
    return (
        outer[0] <= inner[0] + epsilon and
        outer[1] <= inner[1] + epsilon and
        outer[2] >= inner[2] - epsilon and
        outer[3] >= inner[3] - epsilon)


def _drawings_are_disjoint(children):
    boxes = []
    for child in children:
        if isinstance(child, (VectorPath, VectorImage)):
            box = _item_bbox(child)
            if box is None:
                return False
            if any(_overlapping(box, previous) for previous in boxes):
                return False
            boxes.append(box)
    return bool(boxes)


def _is_drawable_item(item):
    return isinstance(item, (VectorPath, VectorImage,
                             VectorLinearGradient, VectorRadialGradient))


def _union_bbox(items):
    box = None
    for item in items:
        item_box = _item_bbox(item)
        if item_box is None:
            continue
        if box is None:
            box = item_box
            continue
        box = (min(box[0], item_box[0]), min(box[1], item_box[1]),
               max(box[2], item_box[2]), max(box[3], item_box[3]))
    return box


def _padded_page_bbox(box, page_rect, scale):
    if box is None:
        return None
    pad = max(CPU_ISLAND_BBOX_PAD, 1.0 / max(1.0, float(scale)))
    x0 = max(float(page_rect.x0), float(box[0]) - pad)
    y0 = max(float(page_rect.y0), float(box[1]) - pad)
    x1 = min(float(page_rect.x1), float(box[2]) + pad)
    y1 = min(float(page_rect.y1), float(box[3]) + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _bbox_area(box):
    if box is None:
        return 0.0
    return max(0.0, float(box[2]) - float(box[0])) * \
        max(0.0, float(box[3]) - float(box[1]))


def _rgba_to_premul_bgra(samples, width, height):
    cost = int(width) * int(height) * 4
    if len(samples) < cost:
        raise ValueError("rasterized image data is incomplete")
    bgra = bytearray(cost)
    alpha = samples[3:cost:4]
    opaque = alpha.count(255) == len(alpha)
    for target, source in ((0, 2), (1, 1), (2, 0)):
        channel = samples[source:cost:4]
        bgra[target::4] = channel if opaque else bytes(
            (value * opacity + 127) // 255
            for value, opacity in zip(channel, alpha))
    bgra[3::4] = alpha
    return bytes(bgra)


def _linear_or_radial_shade_values(shade):
    if int(shade.type) not in (FZ_LINEAR_SHADE, FZ_RADIAL_SHADE):
        return None
    data = ctypes.string_at(
        int(shade.this), FZ_LINEAR_SHADE_UNION_OFFSET + 32)
    extend = struct.unpack_from("ii", data, FZ_LINEAR_SHADE_UNION_OFFSET)
    coords = struct.unpack_from(
        "ffffff", data, FZ_LINEAR_SHADE_UNION_OFFSET + 8)
    if not all(math.isfinite(value) for value in coords):
        raise ValueError("invalid linear shading coordinates")
    return extend, coords


def _ellipse_commands(transform, x, y, radius):
    if radius < 0:
        raise ValueError("invalid radial shading radius")
    kappa = 0.5522847498307936
    cx, cy = _transform_point(transform, x, y)
    rx = _transform_point(transform, x + radius, y)
    ry = _transform_point(transform, x, y + radius)
    vx = (rx[0] - cx, rx[1] - cy)
    vy = (ry[0] - cx, ry[1] - cy)
    return (
        ("move", cx + vx[0], cy + vx[1]),
        ("cubic",
         cx + vx[0] + vy[0] * kappa, cy + vx[1] + vy[1] * kappa,
         cx + vy[0] + vx[0] * kappa, cy + vy[1] + vx[1] * kappa,
         cx + vy[0], cy + vy[1]),
        ("cubic",
         cx + vy[0] - vx[0] * kappa, cy + vy[1] - vx[1] * kappa,
         cx - vx[0] + vy[0] * kappa, cy - vx[1] + vy[1] * kappa,
         cx - vx[0], cy - vx[1]),
        ("cubic",
         cx - vx[0] - vy[0] * kappa, cy - vx[1] - vy[1] * kappa,
         cx - vy[0] - vx[0] * kappa, cy - vy[1] - vx[1] * kappa,
         cx - vy[0], cy - vy[1]),
        ("cubic",
         cx - vy[0] + vx[0] * kappa, cy - vy[1] + vx[1] * kappa,
         cx + vx[0] - vy[0] * kappa, cy + vx[1] - vy[1] * kappa,
         cx + vx[0], cy + vx[1]),
        ("close",))


def _float_pointer_items(pointer, start, count):
    values = (ctypes.c_float * count).from_address(
        int(pointer) + start * ctypes.sizeof(ctypes.c_float))
    return tuple(float(values[index]) for index in range(count))


def _gradient_stops(shade, alpha, color_params):
    source = _mupdf.FzColorspace(shade.colorspace)
    source.thisown = False
    channels = source.fz_colorspace_n()
    if channels <= 0 or not shade.function:
        return None
    stride = int(shade.function_stride)
    if stride < channels:
        raise ValueError("invalid shading function")
    stops = []
    opacity = max(0.0, min(1.0, float(alpha)))
    for index in range(LINEAR_SHADE_STEPS + 1):
        position = index / LINEAR_SHADE_STEPS
        color_index = max(0, min(255, round(position * 255)))
        color = _float_pointer_items(shade.function, color_index * stride, channels)
        stops.append((position, _device_color_values(
            source, color, opacity, color_params)))
    return tuple(stops)


def _argb(color, opacity):
    values = tuple(color)
    if len(values) < 3:
        raise ValueError("Direct2D scene requires RGB colors")
    alpha = max(0, min(255, round(float(opacity) * 255)))
    channels = [max(0, min(255, round(float(value) * 255)))
                for value in values[:3]]
    return (alpha << 24) | (channels[0] << 16) | (channels[1] << 8) | channels[2]


def _device_color(colorspace, color, opacity, color_params):
    source = _mupdf.FzColorspace(colorspace)
    # The callback lends this pointer; the temporary C++ wrapper must not drop
    # the page/global colorspace when Python releases it.
    source.thisown = False
    source_values = [_mupdf.floats_getitem(color, index)
                     for index in range(source.fz_colorspace_n())]
    return _device_color_values(source, source_values, opacity, color_params)


def _device_color_values(colorspace, color, opacity, color_params):
    source = _mupdf.FzColorspace(colorspace)
    source.thisown = False
    target = _mupdf.fz_device_rgb()
    target.thisown = False
    intermediate = _mupdf.FzColorspace()
    params = _mupdf.FzColorParams(color_params)
    converted = _mupdf.fz_convert_color(
        source, list(color), target, intermediate, params)
    return _argb(converted, opacity)


def _stroke_parameters(stroke):
    width = float(stroke.linewidth)
    dash_count = int(stroke.dash_len)
    dashes = tuple(float(_mupdf.floats_getitem(
        stroke.dash_list, index)) for index in range(dash_count))
    if any(not math.isfinite(value) or value < 0 for value in dashes):
        raise ValueError("invalid stroke dash pattern")
    if dashes and width <= 0:
        raise ValueError("dashed hairline stroke is not supported")
    dash_scale = width if dashes else 1.0
    style = (
        int(stroke.start_cap), int(stroke.dash_cap),
        int(stroke.end_cap), int(stroke.linejoin),
        float(stroke.miterlimit), float(stroke.dash_phase) / dash_scale,
        tuple(value / dash_scale for value in dashes))
    if style == (0, 0, 0, 0, 10.0, 0.0, ()):
        style = None
    return width, style


def _uniform_scale(matrix):
    a, b, c, d, _e, _f = _matrix(matrix)
    first = math.hypot(a, b)
    second = math.hypot(c, d)
    tolerance = max(1.0, first, second) * 1e-5
    dot_tolerance = max(1.0, first * second) * 1e-5
    if first <= 0 or abs(first - second) > tolerance or \
            abs(a * c + b * d) > dot_tolerance:
        raise ValueError("non-uniform stroked text transform")
    return first


def _is_identity_transfer_function(function):
    if not function:
        return True
    fn = _mupdf.FzFunction(function)
    fn.thisown = False
    samples = (0.0, 0.25, 0.5, 0.75, 1.0)
    inputs = _mupdf.new_floats(1)
    try:
        for value in samples:
            _mupdf.floats_setitem(inputs, 0, value)
            output = float(fn.fz_eval_function(inputs, 1, 1))
            if not math.isfinite(output) or abs(output - value) > 1e-5:
                return False
    finally:
        _mupdf.delete_floats(inputs)
    return True


def _transfer_function_samples(function):
    if not function:
        return ()
    fn = _mupdf.FzFunction(function)
    fn.thisown = False
    inputs = _mupdf.new_floats(1)
    try:
        samples = []
        for index in range(256):
            value = index / 255.0
            _mupdf.floats_setitem(inputs, 0, value)
            output = float(fn.fz_eval_function(inputs, 1, 1))
            if not math.isfinite(output):
                raise ValueError("invalid soft-mask transfer function")
            samples.append(max(0.0, min(1.0, output)))
    finally:
        _mupdf.delete_floats(inputs)
    return tuple(samples)


def _multiply_argb_opacity(argb, opacity):
    alpha = (argb >> 24) & 0xff
    alpha = max(0, min(255, round(alpha * opacity)))
    return (argb & 0x00ffffff) | (alpha << 24)


def _with_group_opacity(item, opacity):
    if isinstance(item, VectorImage):
        return replace(item, opacity=item.opacity * opacity)
    if isinstance(item, (VectorLinearGradient, VectorRadialGradient)):
        return replace(item, stops=tuple(
            (position, _multiply_argb_opacity(argb, opacity))
            for position, argb in item.stops))
    if isinstance(item, VectorPath):
        if item.fill_argb is not None and item.stroke_argb is not None:
            raise ValueError("non-isolated group opacity has combined fill and stroke")
        fill = (_multiply_argb_opacity(item.fill_argb, opacity)
                if item.fill_argb is not None else None)
        stroke = (_multiply_argb_opacity(item.stroke_argb, opacity)
                  if item.stroke_argb is not None else None)
        return replace(item, fill_argb=fill, stroke_argb=stroke)
    raise ValueError("non-isolated group opacity contains unsupported drawing")


def _is_shading_only_group(children):
    drawings = [child for child in children
                if isinstance(child, (VectorPath, VectorImage,
                                      VectorLinearGradient,
                                      VectorRadialGradient))]
    return bool(drawings) and all(
        (isinstance(child, VectorPath) and child.shading) or
        isinstance(child, (VectorLinearGradient, VectorRadialGradient))
        for child in drawings)


def _is_opaque_vector_only_group(children):
    drawings = [child for child in children
                if isinstance(child, (VectorPath, VectorImage))]
    if not drawings or any(not isinstance(child, VectorPath)
                           for child in drawings):
        return False
    for child in drawings:
        for argb in (child.fill_argb, child.stroke_argb):
            if argb is not None and ((argb >> 24) & 0xff) != 255:
                return False
    return True


def _with_shading_group_opacity(children, opacity):
    flattened = []
    for child in children:
        if (isinstance(child, VectorPath) and child.shading) or \
                isinstance(child, (VectorLinearGradient, VectorRadialGradient)):
            flattened.append(_with_group_opacity(child, opacity))
        else:
            flattened.append(child)
    return flattened


def _with_drawing_group_opacity(children, opacity):
    flattened = []
    for child in children:
        if isinstance(child, (VectorPath, VectorImage)):
            flattened.append(_with_group_opacity(child, opacity))
        else:
            flattened.append(child)
    return flattened


def _argb_channels(argb):
    return (
        (int(argb) >> 24) & 0xff,
        (int(argb) >> 16) & 0xff,
        (int(argb) >> 8) & 0xff,
        int(argb) & 0xff)


def _argb_from_channels(alpha, red, green, blue):
    return (
        (max(0, min(255, int(round(alpha)))) << 24) |
        (max(0, min(255, int(round(red)))) << 16) |
        (max(0, min(255, int(round(green)))) << 8) |
        max(0, min(255, int(round(blue)))))


def _similar_argb(first, second, tolerance):
    return max(abs(a - b) for a, b in zip(
        _argb_channels(first), _argb_channels(second))) <= tolerance


def _average_fill_argb(chunk):
    if len(chunk) < 2:
        return chunk[0].fill_argb
    areas = [_bbox_area(_item_bbox(item)) for item in chunk]
    if sum(areas) <= 0.0:
        areas = [1.0] * len(chunk)
    totals = [0.0, 0.0, 0.0, 0.0]
    for item, weight in zip(chunk, areas):
        for index, value in enumerate(_argb_channels(item.fill_argb)):
            totals[index] += value * weight
    total = sum(areas)
    return _argb_from_channels(*(value / total for value in totals))


def _merged_fill_path(chunk, *, approximate_color=False):
    if len(chunk) < 2:
        return chunk
    commands = []
    first = chunk[0]
    shading = all(item.shading for item in chunk)
    for item in chunk:
        source = item.commands
        if item.transform is not None:
            source = _transform_commands(source, item.transform)
        commands.extend(source)
    return (VectorPath(
        tuple(commands), even_odd=first.even_odd,
        fill_argb=(_average_fill_argb(chunk) if approximate_color
                   else first.fill_argb),
        shading=shading),)


def _compact_consecutive_fill_paths(items, *, aggressive_band_merge=False):
    compacted = []
    chunk = []
    boxes = []
    command_count = 0
    fill_argb = None
    even_odd = False
    groupable = False
    fill_merged = False
    text_merged = False
    aggressive_merged = False

    def flush():
        nonlocal chunk, boxes, command_count, fill_argb, even_odd
        nonlocal groupable, fill_merged, text_merged, aggressive_merged
        if len(chunk) >= 2:
            approximate_color = (
                aggressive_band_merge and not groupable and
                any(item.fill_argb != chunk[0].fill_argb for item in chunk))
            compacted.extend(_merged_fill_path(
                chunk, approximate_color=approximate_color))
            aggressive_merged = aggressive_merged or approximate_color
            if groupable:
                text_merged = True
            else:
                fill_merged = True
        else:
            compacted.extend(chunk)
        chunk = []
        boxes = []
        command_count = 0
        fill_argb = None
        even_odd = False
        groupable = False

    for item in items:
        item_box = _item_bbox(item) if isinstance(item, VectorPath) else None
        mergeable = (
            isinstance(item, VectorPath) and
            item.fill_argb is not None and
            item.stroke_argb is None and
            (not item.groupable or item.transform is not None) and
            (item.groupable or not item.even_odd) and
            item_box is not None)
        next_count = command_count + len(item.commands) if mergeable else 0
        same_run = True
        if mergeable and fill_argb is not None:
            same_color = item.fill_argb == fill_argb or (
                aggressive_band_merge and not item.groupable and
                not groupable and
                _similar_argb(item.fill_argb, fill_argb,
                              AGGRESSIVE_BAND_COLOR_TOLERANCE))
            same_run = (
                same_color and item.even_odd == even_odd and
                item.groupable == groupable)
        overlaps = bool(
            mergeable and
            (not item.groupable or ((item.fill_argb >> 24) & 0xff) < 255) and
            any(_overlapping(item_box, previous) for previous in boxes))
        if not mergeable or \
                not same_run or \
                next_count > MAX_MERGED_FILL_PATH_COMMANDS or \
                overlaps:
            flush()
        if mergeable:
            chunk.append(item)
            boxes.append(item_box)
            command_count += len(item.commands)
            if fill_argb is None:
                fill_argb = item.fill_argb
            even_odd = item.even_odd
            groupable = item.groupable
        else:
            compacted.append(item)
    flush()
    return tuple(compacted), fill_merged, text_merged, aggressive_merged


def _compact_gradient_clip_triplets(items):
    compacted = []
    merged = False
    index = 0
    while index < len(items):
        if index + 2 < len(items) and \
                isinstance(items[index], ClipPush) and \
                isinstance(items[index + 1],
                           (VectorLinearGradient, VectorRadialGradient)) and \
                isinstance(items[index + 2], ClipPop):
            clip = items[index]
            gradient = items[index + 1]
            clip_box = _rect_path_bbox(clip.commands, clip.transform)
            gradient_box = _item_bbox(gradient)
            replacement = None
            if clip_box is not None and gradient_box is not None:
                if _convex_path_contains_bbox(
                        gradient.commands, gradient.transform, clip_box):
                    replacement = replace(
                        gradient, commands=clip.commands,
                        even_odd=clip.even_odd, transform=clip.transform)
                elif _contains_bbox(clip_box, gradient_box):
                    replacement = gradient
            if replacement is not None:
                compacted.append(replacement)
                merged = True
                index += 3
                continue
        compacted.append(items[index])
        index += 1
    return tuple(compacted), merged


def _tile_offset_transform(transform, state, xoffset, yoffset):
    page_dx = state.ctm[0] * xoffset + state.ctm[2] * yoffset
    page_dy = state.ctm[1] * xoffset + state.ctm[3] * yoffset
    if transform is None:
        return None, page_dx, page_dy
    offset = (1.0, 0.0, 0.0, 1.0, xoffset, yoffset)
    return _concat_matrices(offset, transform), page_dx, page_dy


def _offset_tile_item(item, state, xoffset, yoffset):
    if isinstance(item, (ClipPop, GroupPush, GroupPop)):
        return item
    if isinstance(item, (MaskBegin, MaskEnd)):
        raise ValueError("unsupported mask inside tile pattern")
    if isinstance(item, VectorPath):
        transform, dx, dy = _tile_offset_transform(
            item.transform, state, xoffset, yoffset)
        commands = item.commands if transform is not None else \
            _translate_commands(item.commands, dx, dy)
        return replace(item, commands=commands, transform=transform)
    if isinstance(item, VectorImage):
        transform, dx, dy = _tile_offset_transform(
            item.transform, state, xoffset, yoffset)
        if transform is None:
            transform = (1.0, 0.0, 0.0, 1.0, dx, dy)
        return replace(item, transform=transform)
    if isinstance(item, (VectorLinearGradient, VectorRadialGradient)):
        transform, dx, dy = _tile_offset_transform(
            item.transform, state, xoffset, yoffset)
        commands = item.commands if transform is not None else \
            _translate_commands(item.commands, dx, dy)
        return replace(item, commands=commands, transform=transform)
    if isinstance(item, ClipPush):
        transform, dx, dy = _tile_offset_transform(
            item.transform, state, xoffset, yoffset)
        commands = item.commands if transform is not None else \
            _translate_commands(item.commands, dx, dy)
        return replace(item, commands=commands, transform=transform)
    if isinstance(item, ClipStrokePush):
        transform, dx, dy = _tile_offset_transform(
            item.transform, state, xoffset, yoffset)
        commands = item.commands if transform is not None else \
            _translate_commands(item.commands, dx, dy)
        return replace(item, commands=commands, transform=transform)
    raise ValueError("unsupported tile pattern item")


def _tile_repeat_offsets(state):
    if not all(math.isfinite(value) for value in
               (*state.area, *state.view, state.xstep, state.ystep,
                *state.ctm)):
        raise ValueError("invalid tile pattern geometry")
    if abs(state.xstep) < 1e-6 or abs(state.ystep) < 1e-6:
        raise ValueError("invalid tile pattern step")
    inverse = _invert_matrix(state.ctm)
    ax0, ay0, ax1, ay1 = state.area
    corners = (
        _transform_point(inverse, ax0, ay0),
        _transform_point(inverse, ax1, ay0),
        _transform_point(inverse, ax1, ay1),
        _transform_point(inverse, ax0, ay1))
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    vx0, vy0, vx1, vy1 = state.view
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if state.xstep < 0:
        state = replace(state, xstep=-state.xstep)
    if state.ystep < 0:
        state = replace(state, ystep=-state.ystep)
    ix0 = math.floor((xmin - max(vx0, vx1)) / state.xstep) - 1
    ix1 = math.ceil((xmax - min(vx0, vx1)) / state.xstep) + 1
    iy0 = math.floor((ymin - max(vy0, vy1)) / state.ystep) - 1
    iy1 = math.ceil((ymax - min(vy0, vy1)) / state.ystep) + 1
    count = max(0, ix1 - ix0 + 1) * max(0, iy1 - iy0 + 1)
    if count > 4096:
        raise ValueError("tile pattern repeat count exceeds GPU scene limit")
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            yield ix * state.xstep, iy * state.ystep


def _flatten_nonisolated_groups(items):
    def parse(index, stop_at_group=False):
        flattened = []
        while index < len(items):
            item = items[index]
            if isinstance(item, GroupPop):
                if not stop_at_group:
                    raise ValueError("unbalanced transparency group stack")
                return flattened, index + 1
            if isinstance(item, GroupPush):
                children, index = parse(index + 1, True)
                drawing_indexes = [
                    position for position, child in enumerate(children)
                    if isinstance(child, (VectorPath, VectorImage,
                                          VectorLinearGradient,
                                          VectorRadialGradient))]
                shading_only = _is_shading_only_group(children)
                opaque_vector_only = _is_opaque_vector_only_group(children)
                disjoint = _drawings_are_disjoint(children)
                if item.knockout and len(drawing_indexes) > 1 and not (
                        shading_only or opaque_vector_only or disjoint):
                    if (not item.isolated or item.blend_mode != 0 or
                            item.opacity < 1.0 - 1e-6):
                        if not item.isolated and item.blend_mode == 0 and \
                                item.opacity >= 1.0 - 1e-6:
                            flattened.append(replace(item, isolated=True))
                            flattened.extend(children)
                            flattened.append(GroupPop())
                            continue
                        raise ValueError("unsupported knockout transparency group")
                if item.isolated:
                    if item.knockout and not drawing_indexes:
                        flattened.extend(children)
                        continue
                    flattened.append(item)
                    flattened.extend(children)
                    flattened.append(GroupPop())
                    continue
                if not drawing_indexes:
                    flattened.extend(children)
                    continue
                if item.blend_mode != 0:
                    if item.blend_mode <= 11 and (
                            len(drawing_indexes) == 1 or
                            shading_only or opaque_vector_only):
                        flattened.append(replace(
                            item, isolated=True))
                        flattened.extend(children)
                        flattened.append(GroupPop())
                        continue
                    raise ValueError(
                        "unsupported non-isolated transparency group blend mode")
                if len(drawing_indexes) != 1:
                    if shading_only:
                        flattened.extend(_with_shading_group_opacity(
                            children, item.opacity))
                        continue
                    if opaque_vector_only and item.opacity >= 1.0 - 1e-6:
                        flattened.extend(children)
                        continue
                    if item.knockout and opaque_vector_only:
                        flattened.append(replace(item, isolated=True))
                        flattened.extend(children)
                        flattened.append(GroupPop())
                        continue
                    if item.knockout and disjoint:
                        flattened.extend(_with_drawing_group_opacity(
                            children, item.opacity))
                        continue
                    raise ValueError(
                        "unsupported non-isolated transparency group contents")
                position = drawing_indexes[0]
                children[position] = _with_group_opacity(
                    children[position], item.opacity)
                flattened.extend(children)
                continue
            flattened.append(item)
            index += 1
        if stop_at_group:
            raise ValueError("unbalanced transparency group stack")
        return flattened, index

    return tuple(parse(0)[0])


def _group_spans(items):
    stack = []
    spans = []
    for index, item in enumerate(items):
        if isinstance(item, GroupPush):
            stack.append((index, item))
        elif isinstance(item, GroupPop):
            if not stack:
                raise ValueError("unbalanced transparency group stack")
            start, push = stack.pop()
            spans.append((start, index, push))
    if stack:
        raise ValueError("unbalanced transparency group stack")
    return spans


def _enclosing_scopes(items, group_start):
    scopes = []
    for item in items[:group_start]:
        if isinstance(item, (ClipPush, ClipStrokePush)):
            scopes.append("clip")
        elif isinstance(item, ClipPop):
            if scopes:
                scopes.pop()
        elif isinstance(item, MaskBegin):
            scopes.append("mask")
        elif isinstance(item, MaskEnd):
            if scopes and scopes[-1] == "mask":
                scopes[-1] = "clip"
        elif isinstance(item, GroupPush):
            scopes.append("group")
        elif isinstance(item, GroupPop):
            if scopes and scopes[-1] == "group":
                scopes.pop()
    return tuple(scopes)


def _cpu_island_from_page(page, box, scale, image_bytes):
    box = _padded_page_bbox(box, page.rect, scale)
    if box is None:
        raise ValueError("CPU island has empty bounds")
    page_box = (float(page.rect.x0), float(page.rect.y0),
                float(page.rect.x1), float(page.rect.y1))
    page_area = _bbox_area(page_box)
    if page_area <= 0.0 or \
            _bbox_area(box) / page_area > MAX_CPU_ISLAND_PAGE_COVERAGE:
        raise ValueError("CPU island covers too much of the page")
    clip = pymupdf.Rect(*box)
    pixmap = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=True)
    width = int(pixmap.width)
    height = int(pixmap.height)
    cost = width * height * 4
    if cost <= 0:
        raise ValueError("CPU island has empty pixels")
    if cost > MAX_GPU_IMAGE_BYTES or image_bytes + cost > MAX_GPU_IMAGE_BYTES:
        raise ValueError("CPU island image data exceeds GPU scene limit")
    if pixmap.n != 4 or not pixmap.alpha:
        raise ValueError("CPU island is not RGBA")
    pixels = _rgba_to_premul_bgra(pixmap.samples, width, height)
    return VectorImage(
        pixels, width, height, width * 4,
        (width / scale, 0.0, 0.0, height / scale,
         float(pixmap.x) / scale, float(pixmap.y) / scale)), cost


def _approximate_island_absorbed_indexes(items, start, end, box, page):
    page_area = _bbox_area((float(page.rect.x0), float(page.rect.y0),
                            float(page.rect.x1), float(page.rect.y1)))
    if page_area <= 0.0:
        return box, set()
    current = box
    absorbed = set()
    changed = True
    while changed:
        changed = False
        for index, item in enumerate(items):
            if start <= index <= end or index in absorbed or \
                    not _is_drawable_item(item):
                continue
            item_box = _item_bbox(item)
            if item_box is None or not _overlapping(current, item_box):
                continue
            expanded = (
                min(current[0], item_box[0]), min(current[1], item_box[1]),
                max(current[2], item_box[2]), max(current[3], item_box[3]))
            if _bbox_area(expanded) / page_area > \
                    MAX_APPROXIMATE_CPU_ISLAND_PAGE_COVERAGE:
                continue
            current = expanded
            absorbed.add(index)
            changed = True
    padded = _padded_page_bbox(current, page.rect, 1.0)
    if padded is None:
        padded = current
    absorbed = {
        index for index in absorbed
        if _contains_bbox(padded, _item_bbox(items[index]))
    }
    return current, absorbed


def _replace_one_group_with_cpu_island(
        items, page, scale, image_bytes, *, approximate=False):
    spans = sorted(_group_spans(items), key=lambda span: span[1] - span[0])
    for start, end, _push in spans:
        group_items = tuple(items[start:end + 1])
        try:
            _flatten_nonisolated_groups(group_items)
            continue
        except Exception:
            pass
        scopes = _enclosing_scopes(items, start)
        if "mask" in scopes or (not approximate and "group" in scopes):
            continue
        children = tuple(items[start + 1:end])
        box = _union_bbox(children)
        if box is None:
            continue
        page_area = _bbox_area((float(page.rect.x0), float(page.rect.y0),
                                float(page.rect.x1), float(page.rect.y1)))
        coverage = _bbox_area(box) / page_area if page_area > 0.0 else 1.0
        if approximate and coverage > MAX_APPROXIMATE_CPU_ISLAND_PAGE_COVERAGE:
            continue
        absorbed = set()
        if approximate:
            box, absorbed = _approximate_island_absorbed_indexes(
                items, start, end, box, page)
        external_boxes = [
            _item_bbox(item) for index, item in enumerate(items)
            if index not in absorbed and not start <= index <= end
        ]
        external_boxes = [item_box for item_box in external_boxes
                          if item_box is not None]
        overlaps = any(_overlapping(box, item_box)
                       for item_box in external_boxes)
        if overlaps and not approximate:
            continue
        try:
            island, cost = _cpu_island_from_page(page, box, scale, image_bytes)
        except Exception:
            continue
        merged = []
        for index, item in enumerate(items):
            if index == start:
                merged.append(island)
            if start <= index <= end or index in absorbed:
                continue
            merged.append(item)
        return (tuple(merged),
                image_bytes + cost, overlaps or bool(scopes))
    return None


def _flatten_or_cpu_island_groups(items, page, scale, image_bytes):
    current = tuple(items)
    islanded = False
    while True:
        try:
            return tuple(_flatten_nonisolated_groups(current)), image_bytes, islanded
        except Exception as error:
            replaced = _replace_one_group_with_cpu_island(
                current, page, scale, image_bytes)
            if replaced is None:
                replaced = _replace_one_group_with_cpu_island(
                    current, page, scale, image_bytes, approximate=True)
            if replaced is None:
                raise error
            current, image_bytes, approximate = replaced
            islanded = "approximate" if approximate else True


class _DisplayListDevice(_mupdf.FzDevice2):
    """Record only operations with an exact Direct2D representation."""

    def __init__(self, page_rect, raster_scale=1.0, cookie=None, deadline=None):
        super().__init__()
        for name in (
                "fill_path", "stroke_path", "clip_path", "pop_clip",
                "fill_text", "stroke_text", "clip_text", "clip_stroke_text",
                "clip_stroke_path", "fill_image", "fill_image_mask",
                "clip_image_mask", "fill_shade", "begin_mask", "end_mask",
                "begin_group", "end_group", "begin_tile", "end_tile"):
            getattr(self, "use_virtual_" + name)()
        self.items = []
        self.failure = ""
        self._glyphs = {}
        self._images = {}
        self._source_image_index = 0
        self._image_bytes = 0
        self._clip_depth = 0
        self._group_depth = 0
        self._group_passthrough = []
        self._mask_depth = 0
        self._tile_stack = []
        self._page_rect = tuple(float(value) for value in page_rect)
        self._features = set()
        self._raster_scale = max(1.0, float(raster_scale))
        self._cookie = cookie
        self._deadline = deadline

    def _fail(self, operation):
        self._set_failure("unsupported operation: " + operation)

    def _set_failure(self, reason):
        if not self.failure:
            self.failure = reason

    def _abort_if_expired(self):
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self._set_failure("GPU scene time budget exceeded")
            if self._cookie is not None:
                self._cookie.set_abort()
            return True
        return False

    def _append_item(self, item):
        if self._abort_if_expired():
            return False
        if len(self.items) >= MAX_GPU_SCENE_ITEMS:
            self._set_failure("GPU scene command limit exceeded")
            if self._cookie is not None:
                self._cookie.set_abort()
            return False
        self.items.append(item)
        return True

    def _extend_items(self, items):
        items = tuple(items)
        if self._abort_if_expired():
            return False
        if len(self.items) + len(items) > MAX_GPU_SCENE_ITEMS:
            self._set_failure("GPU scene command limit exceeded")
            if self._cookie is not None:
                self._cookie.set_abort()
            return False
        self.items.extend(items)
        return True

    def _image_cache_key(self, source, kind, extra=()):
        key = source.m_internal_value()
        if not key:
            return None
        return (kind, key, *extra)

    def _reserve_image_bytes(self, source, key, ctm):
        if key is not None and key in self._images:
            return
        width = int(source.w())
        height = int(source.h())
        factor = _image_downsample_factor(
            width, height, ctm, self._raster_scale)
        width, height = _downsampled_size(width, height, factor)
        estimated = width * height * 4
        if estimated > MAX_GPU_IMAGE_BYTES or \
                self._image_bytes + estimated > MAX_GPU_IMAGE_BYTES:
            raise ValueError("page image data exceeds GPU scene limit")

    def _store_image_bytes(self, key, pixels, width, height, stride):
        if key is not None and key in self._images:
            return self._images[key]
        cost = width * height * 4
        if cost > MAX_GPU_IMAGE_BYTES or \
                self._image_bytes + cost > MAX_GPU_IMAGE_BYTES:
            raise ValueError("page image data exceeds GPU scene limit")
        entry = (pixels, width, height, stride)
        if key is not None:
            self._images[key] = entry
        self._image_bytes += cost
        return entry

    def _downsample_pixmap(self, pixmap, ctm):
        factor = _image_downsample_factor(
            pixmap.width, pixmap.height, ctm, self._raster_scale)
        if factor:
            pixmap.shrink(factor)
            self._features.add("image-downsample")
        return pixmap

    def _linear_shade_paths(self, shade, ctm, alpha, color_params, bounds):
        if int(shade.type) != FZ_LINEAR_SHADE:
            return None
        values = _linear_or_radial_shade_values(shade)
        if values is None or not shade.function:
            return None
        source = _mupdf.FzColorspace(shade.colorspace)
        source.thisown = False
        channels = source.fz_colorspace_n()
        if channels <= 0:
            return None
        extend, coords = values
        transform = _concat_matrices(_raw_matrix(shade.matrix), _matrix(ctm))
        start = _transform_point(transform, coords[0], coords[1])
        end = _transform_point(transform, coords[3], coords[4])
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            raise ValueError("invalid linear shading vector")
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            return ()
        corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        projections = [
            ((x - start[0]) * ux + (y - start[1]) * uy) / length
            for x, y in corners]
        lower = min(projections)
        upper = max(projections)
        segments = []
        if extend[0] and lower < 0.0:
            segments.append((lower, 0.0, 0.0))
        inside_lower = max(0.0, lower)
        inside_upper = min(1.0, upper)
        if inside_upper > inside_lower:
            first = math.floor(inside_lower * LINEAR_SHADE_STEPS)
            last = math.ceil(inside_upper * LINEAR_SHADE_STEPS)
            for index in range(first, last):
                t0 = max(inside_lower, index / LINEAR_SHADE_STEPS)
                t1 = min(inside_upper, (index + 1) / LINEAR_SHADE_STEPS)
                if t1 > t0:
                    segments.append((t0, t1, (t0 + t1) * 0.5))
        if extend[1] and upper > 1.0:
            segments.append((1.0, upper, 1.0))
        if not segments:
            return ()
        stride = int(shade.function_stride)
        if stride < channels:
            raise ValueError("invalid linear shading function")
        opacity = max(0.0, min(1.0, float(alpha)))
        reach = math.hypot(x1 - x0, y1 - y0) + length + 4.0
        items = [ClipPush(_rect_commands(x0, y0, x1, y1))]
        for t0, t1, sample in segments:
            index = max(0, min(255, round(sample * 255)))
            offset = index * stride
            color = _float_pointer_items(shade.function, offset, channels)
            center0 = (
                start[0] + ux * length * t0,
                start[1] + uy * length * t0)
            center1 = (
                start[0] + ux * length * t1,
                start[1] + uy * length * t1)
            commands = (
                ("move", center0[0] + px * reach, center0[1] + py * reach),
                ("line", center1[0] + px * reach, center1[1] + py * reach),
                ("line", center1[0] - px * reach, center1[1] - py * reach),
                ("line", center0[0] - px * reach, center0[1] - py * reach),
                ("close",))
            items.append(VectorPath(
                commands, fill_argb=_device_color_values(
                    source, color, opacity, color_params), shading=True))
        items.append(ClipPop())
        return items

    def _linear_shade_gradient(self, shade, ctm, alpha, color_params, bounds):
        if int(shade.type) != FZ_LINEAR_SHADE:
            return None
        values = _linear_or_radial_shade_values(shade)
        if values is None:
            return None
        stops = _gradient_stops(shade, alpha, color_params)
        if stops is None:
            return None
        extend, coords = values
        transform = _concat_matrices(_raw_matrix(shade.matrix), _matrix(ctm))
        start = _transform_point(transform, coords[0], coords[1])
        end = _transform_point(transform, coords[3], coords[4])
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 1e-6:
            raise ValueError("invalid linear shading vector")
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            return ()
        corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        projections = [
            ((x - start[0]) * ux + (y - start[1]) * uy) / length
            for x, y in corners]
        lower = min(projections) if extend[0] else max(0.0, min(projections))
        upper = max(projections) if extend[1] else min(1.0, max(projections))
        if upper <= lower:
            return ()
        reach = math.hypot(x1 - x0, y1 - y0) + length + 4.0
        center0 = (start[0] + ux * length * lower,
                   start[1] + uy * length * lower)
        center1 = (start[0] + ux * length * upper,
                   start[1] + uy * length * upper)
        strip = (
            ("move", center0[0] + px * reach, center0[1] + py * reach),
            ("line", center1[0] + px * reach, center1[1] + py * reach),
            ("line", center1[0] - px * reach, center1[1] - py * reach),
            ("line", center0[0] - px * reach, center0[1] - py * reach),
            ("close",))
        return (
            ClipPush(_rect_commands(x0, y0, x1, y1)),
            VectorLinearGradient(strip, start, end, stops),
            ClipPop())

    def _radial_shade_paths(self, shade, ctm, alpha, color_params, bounds):
        if int(shade.type) != FZ_RADIAL_SHADE:
            return None
        values = _linear_or_radial_shade_values(shade)
        if values is None or not shade.function:
            return None
        source = _mupdf.FzColorspace(shade.colorspace)
        source.thisown = False
        channels = source.fz_colorspace_n()
        if channels <= 0:
            return None
        _extend, coords = values
        transform = _concat_matrices(_raw_matrix(shade.matrix), _matrix(ctm))
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            return ()
        stride = int(shade.function_stride)
        if stride < channels:
            raise ValueError("invalid radial shading function")
        opacity = max(0.0, min(1.0, float(alpha)))
        items = [ClipPush(_rect_commands(x0, y0, x1, y1))]
        for index in reversed(range(LINEAR_SHADE_STEPS)):
            t0 = index / LINEAR_SHADE_STEPS
            t1 = (index + 1) / LINEAR_SHADE_STEPS
            sample = (t0 + t1) * 0.5
            color_index = max(0, min(255, round(sample * 255)))
            offset = color_index * stride
            color = _float_pointer_items(shade.function, offset, channels)
            inner = (
                coords[0] + (coords[3] - coords[0]) * t0,
                coords[1] + (coords[4] - coords[1]) * t0,
                coords[2] + (coords[5] - coords[2]) * t0)
            outer = (
                coords[0] + (coords[3] - coords[0]) * t1,
                coords[1] + (coords[4] - coords[1]) * t1,
                coords[2] + (coords[5] - coords[2]) * t1)
            commands = _ellipse_commands(
                transform, outer[0], outer[1], outer[2])
            if inner[2] > 1e-6:
                commands += _ellipse_commands(
                    transform, inner[0], inner[1], inner[2])
                even_odd = True
            else:
                even_odd = False
            items.append(VectorPath(
                commands, even_odd=even_odd,
                fill_argb=_device_color_values(
                    source, color, opacity, color_params), shading=True))
        items.append(ClipPop())
        return items

    def _radial_shade_gradient(self, shade, ctm, alpha, color_params, bounds):
        if int(shade.type) != FZ_RADIAL_SHADE:
            return None
        values = _linear_or_radial_shade_values(shade)
        if values is None:
            return None
        _extend, coords = values
        # Direct2D's radial brush has one end radius. PDF radial shadings with a
        # non-zero start radius stay on the existing exact band path for now.
        if abs(coords[2]) > 1e-6 or coords[5] <= 1e-6:
            return None
        stops = _gradient_stops(shade, alpha, color_params)
        if stops is None:
            return None
        transform = _concat_matrices(_raw_matrix(shade.matrix), _matrix(ctm))
        x0, y0, x1, y1 = bounds
        if x1 <= x0 or y1 <= y0:
            return ()
        commands = _ellipse_commands(transform, coords[3], coords[4], coords[5])
        center = _transform_point(transform, coords[3], coords[4])
        origin = _transform_point(transform, coords[0], coords[1])
        radius_x = _transform_point(transform, coords[3] + coords[5], coords[4])
        radius_y = _transform_point(transform, coords[3], coords[4] + coords[5])
        return (
            ClipPush(_rect_commands(x0, y0, x1, y1)),
            VectorRadialGradient(
                commands, center, origin,
                (math.hypot(radius_x[0] - center[0], radius_x[1] - center[1]),
                 math.hypot(radius_y[0] - center[0], radius_y[1] - center[1])),
                stops),
            ClipPop())

    def fill_path(self, _context, path, even_odd, ctm, colorspace, color,
                  alpha, color_params):
        try:
            self._features.add("vector")
            self._append_item(VectorPath(
                _path_commands(path), bool(even_odd),
                fill_argb=_device_color(
                    colorspace, color, alpha, color_params),
                transform=_matrix(ctm)))
        except Exception as error:
            self._set_failure(str(error))

    def stroke_path(self, _context, path, stroke, ctm, colorspace, color,
                    alpha, color_params):
        try:
            self._features.add("vector")
            commands = _path_commands(path)
            transform = _matrix(ctm)
            argb = _device_color(colorspace, color, alpha, color_params)
            width, style = _stroke_parameters(stroke)
            if style is not None:
                self._features.add("stroke-style")
            if self.items and isinstance(self.items[-1], VectorPath):
                previous = self.items[-1]
                if previous.commands == commands and \
                        previous.transform == transform and \
                        previous.stroke_argb is None:
                    self.items[-1] = replace(
                        previous, stroke_argb=argb, stroke_width=width,
                        stroke_style=style)
                    return
            self._append_item(VectorPath(
                commands, stroke_argb=argb, stroke_width=width,
                stroke_style=style, transform=transform))
        except Exception as error:
            self._set_failure(str(error))

    def clip_path(self, _context, path, even_odd, ctm, _scissor):
        try:
            self._features.add("vector-clip")
            self._append_item(ClipPush(
                _path_commands(path), bool(even_odd), _matrix(ctm)))
            self._clip_depth += 1
        except Exception as error:
            self._set_failure(str(error))

    def pop_clip(self, _context):
        if self._clip_depth <= 0:
            self._set_failure("unbalanced clip stack")
            return
        self._append_item(ClipPop())
        self._clip_depth -= 1

    def _text_outlines(self, text, ctm):
        outlines = []
        span_ptr = text.head
        while span_ptr:
            next_span = span_ptr.next
            span = _mupdf.FzTextSpan(span_ptr)
            span.thisown = False
            font = span.font()
            base = span.trm()
            page_matrix = _mupdf.FzMatrix(ctm)
            for index in range(span.m_internal.len):
                item = span.items(index)
                gid = int(item.gid)
                if gid < 0:
                    gid = _encoded_glyph_id(font, item.ucs)
                    if gid < 0:
                        if _is_invisible_text_codepoint(item.ucs):
                            continue
                        raise ValueError("text glyph has no usable glyph id")
                    self._features.add("text-glyph-cmap")
                matrix = _mupdf.FzMatrix(
                    base.a, base.b, base.c, base.d, base.e, base.f)
                matrix.e = item.x
                matrix.f = item.y
                matrix = _mupdf.fz_concat(matrix, page_matrix)
                key = (font.m_internal_value(), gid)
                commands = self._glyphs.get(key)
                if commands is None:
                    outline = font.fz_outline_glyph(
                        gid, _mupdf.FzMatrix())
                    if not outline:
                        if _is_invisible_text_codepoint(item.ucs):
                            self._glyphs[key] = ()
                            continue
                        raise ValueError("font glyph has no vector outline")
                    commands = _path_commands(outline, allow_empty=True)
                    if not commands and not _is_invisible_text_codepoint(
                            item.ucs):
                        raise ValueError("font glyph has no vector outline")
                    self._glyphs[key] = commands
                if commands:
                    outlines.append((commands, _matrix(matrix)))
            span_ptr = next_span
        return outlines

    def fill_text(self, _context, text, ctm, colorspace, color,
                  alpha, color_params):
        try:
            self._features.add("text")
            argb = _device_color(colorspace, color, alpha, color_params)
            for commands, transform in self._text_outlines(text, ctm):
                self._append_item(VectorPath(
                    commands, fill_argb=argb,
                    transform=transform, groupable=True))
        except Exception as error:
            self._set_failure(str(error))

    def fill_image(self, _context, image, ctm, alpha, _color_params):
        source_index = self._source_image_index
        self._source_image_index += 1
        try:
            self._features.add("image")
            source = _mupdf.FzImage(image)
            source.thisown = False
            factor = _image_downsample_factor(
                int(source.w()), int(source.h()), ctm, self._raster_scale)
            key = self._image_cache_key(source, "image", (factor,))
            self._reserve_image_bytes(source, key, ctm)
            cached = self._images.get(key) if key is not None else None
            if cached is None:
                pixmap = pymupdf.Pixmap(
                    source.fz_get_unscaled_pixmap_from_image())
                if pixmap.n - pixmap.alpha != 3:
                    # PDF images may be Gray/CMYK/ICC-based; Direct2D receives BGRA.
                    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
                if not pixmap.alpha and pixmap.n == 3:
                    pixmap = pymupdf.Pixmap(pixmap, 1)
                pixmap = self._downsample_pixmap(pixmap, ctm)
                rgba = pixmap.samples
                cost = pixmap.width * pixmap.height * 4
                if pixmap.n != 4 or not pixmap.alpha or len(rgba) < cost:
                    raise ValueError("decoded image is not RGBA")
                bgra = _rgba_to_premul_bgra(rgba, pixmap.width, pixmap.height)
                cached = self._store_image_bytes(
                    key, bytes(bgra), pixmap.width, pixmap.height,
                    pixmap.width * 4)
            pixels, width, height, stride = cached
            self._append_item(VectorImage(
                pixels, width, height, stride, _matrix(ctm),
                max(0.0, min(1.0, float(alpha))),
                bool(source.interpolate()), source_index))
        except Exception as error:
            self._set_failure(str(error))

    def stroke_text(self, _context, text, stroke, ctm, colorspace, color,
                    alpha, color_params):
        try:
            self._features.add("stroked-text")
            width, style = _stroke_parameters(stroke)
            width *= _uniform_scale(ctm)
            argb = _device_color(colorspace, color, alpha, color_params)
            for commands, transform in self._text_outlines(text, ctm):
                self._append_item(VectorPath(
                    _transform_commands(commands, transform),
                    stroke_argb=argb, stroke_width=width,
                    stroke_style=style))
        except Exception as error:
            self._set_failure(str(error))

    def clip_text(self, _context, text, ctm, _scissor):
        try:
            self._features.add("text-clip")
            commands = []
            for outline, transform in self._text_outlines(text, ctm):
                commands.extend(_transform_commands(outline, transform))
            if not commands:
                raise ValueError("text clip has no vector outline")
            self._append_item(ClipPush(tuple(commands)))
            self._clip_depth += 1
        except Exception as error:
            self._set_failure(str(error))

    def clip_stroke_text(self, _context, text, stroke, ctm, _scissor):
        try:
            self._features.add("stroked-text-clip")
            width, style = _stroke_parameters(stroke)
            width *= _uniform_scale(ctm)
            commands = []
            for outline, transform in self._text_outlines(text, ctm):
                commands.extend(_transform_commands(outline, transform))
            if not commands:
                raise ValueError("stroked text clip has no vector outline")
            self._append_item(ClipStrokePush(
                tuple(commands), width, style))
            self._clip_depth += 1
        except Exception as error:
            self._set_failure(str(error))

    def clip_stroke_path(self, _context, path, stroke, ctm, _scissor):
        try:
            self._features.add("stroked-vector-clip")
            width, style = _stroke_parameters(stroke)
            self._append_item(ClipStrokePush(
                _path_commands(path), width, style, _matrix(ctm)))
            self._clip_depth += 1
        except Exception as error:
            self._set_failure(str(error))

    def fill_image_mask(self, _context, image, ctm, colorspace, color,
                        alpha, color_params):
        try:
            self._features.add("stencil")
            source = _mupdf.FzImage(image)
            source.thisown = False
            argb = _device_color(
                colorspace, color, 1.0, color_params)
            factor = _image_downsample_factor(
                int(source.w()), int(source.h()), ctm, self._raster_scale)
            key = self._image_cache_key(source, "stencil", (argb, factor))
            self._reserve_image_bytes(source, key, ctm)
            cached = self._images.get(key) if key is not None else None
            if cached is None:
                pixmap = pymupdf.Pixmap(
                    source.fz_get_unscaled_pixmap_from_image())
                if pixmap.n != 1 or not pixmap.alpha:
                    raise ValueError("decoded stencil is not an alpha mask")
                pixmap = self._downsample_pixmap(pixmap, ctm)
                red = (argb >> 16) & 0xff
                green = (argb >> 8) & 0xff
                blue = argb & 0xff
                bgra = bytearray(pixmap.width * pixmap.height * 4)
                for index, opacity in enumerate(pixmap.samples):
                    offset = index * 4
                    bgra[offset:offset + 4] = (
                        (blue * opacity + 127) // 255,
                        (green * opacity + 127) // 255,
                        (red * opacity + 127) // 255,
                        opacity)
                cached = self._store_image_bytes(
                    key, bytes(bgra), pixmap.width, pixmap.height,
                    pixmap.width * 4)
            pixels, width, height, stride = cached
            self._append_item(VectorImage(
                pixels, width, height, stride, _matrix(ctm),
                max(0.0, min(1.0, float(alpha))),
                bool(source.interpolate())))
        except Exception as error:
            self._set_failure(str(error))

    def clip_image_mask(self, _context, image, ctm, _scissor):
        try:
            source = _mupdf.FzImage(image)
            source.thisown = False
            transform = _matrix(ctm)
            factor = _image_downsample_factor(
                int(source.w()), int(source.h()), ctm, self._raster_scale)
            key = self._image_cache_key(source, "clip-mask", (factor,))
            self._reserve_image_bytes(source, key, ctm)
            cached = self._images.get(key) if key is not None else None
            if cached is None:
                pixmap = pymupdf.Pixmap(
                    source.fz_get_unscaled_pixmap_from_image())
                if pixmap.n != 1 or not pixmap.alpha:
                    raise ValueError("decoded clip mask is not an alpha mask")
                pixmap = self._downsample_pixmap(pixmap, ctm)
                if pixmap.samples and min(pixmap.samples) == 255:
                    self._append_item(ClipPush(
                        UNIT_RECT_COMMANDS, transform=transform))
                    self._clip_depth += 1
                    self._features.add("clip-mask")
                    self._features.add("vector-clip")
                    return
                bgra = bytearray(pixmap.width * pixmap.height * 4)
                for index, opacity in enumerate(pixmap.samples):
                    offset = index * 4
                    bgra[offset:offset + 4] = (
                        opacity, opacity, opacity, opacity)
                cached = self._store_image_bytes(
                    key, bytes(bgra), pixmap.width, pixmap.height,
                    pixmap.width * 4)
            pixels, width, height, stride = cached
            mask_area = _image_mask_area(transform, self._page_rect)
            if mask_area is None:
                return
            self._extend_items((
                MaskBegin(mask_area, False, 0),
                VectorImage(
                    pixels, width, height, stride, transform,
                    interpolate=bool(source.interpolate())),
                MaskEnd()))
            self._clip_depth += 1
            self._features.add("clip-mask")
        except Exception as error:
            self._set_failure(str(error))

    def fill_shade(self, _context, shade_ptr, ctm, alpha, color_params):
        try:
            self._features.add("shading")
            shade = _mupdf.FzShade(shade_ptr)
            shade.thisown = False
            matrix = _mupdf.FzMatrix(ctm)
            bound = shade.fz_bound_shade(matrix)
            page_x0, page_y0, page_x1, page_y1 = self._page_rect
            values = (float(bound.x0), float(bound.y0),
                      float(bound.x1), float(bound.y1))
            if all(math.isfinite(value) for value in values):
                x0 = max(page_x0, values[0])
                y0 = max(page_y0, values[1])
                x1 = min(page_x1, values[2])
                y1 = min(page_y1, values[3])
            else:
                x0, y0, x1, y1 = self._page_rect
            if x1 <= x0 or y1 <= y0:
                return
            vector_shade = self._linear_shade_gradient(
                shade_ptr, matrix, alpha, color_params, (x0, y0, x1, y1))
            if vector_shade is None:
                vector_shade = self._radial_shade_gradient(
                    shade_ptr, matrix, alpha, color_params, (x0, y0, x1, y1))
            if vector_shade is None:
                vector_shade = self._linear_shade_paths(
                    shade_ptr, matrix, alpha, color_params, (x0, y0, x1, y1))
            if vector_shade is None:
                vector_shade = self._radial_shade_paths(
                    shade_ptr, matrix, alpha, color_params, (x0, y0, x1, y1))
            if vector_shade is not None:
                self._extend_items(vector_shade)
                self._features.add("vector-shading")
                if any(isinstance(item, (VectorLinearGradient, VectorRadialGradient))
                       for item in vector_shade):
                    self._features.add("gradient-primitive")
                if vector_shade:
                    self._features.add("vector-clip")
                return
            scale = SHADE_RASTER_SCALE
            self._features.add("raster-shading")
            left = math.floor(x0 * scale)
            top = math.floor(y0 * scale)
            right = math.ceil(x1 * scale)
            bottom = math.ceil(y1 * scale)
            width = right - left
            height = bottom - top
            estimated = width * height * 4
            if estimated > MAX_GPU_IMAGE_BYTES or \
                    self._image_bytes + estimated > MAX_GPU_IMAGE_BYTES:
                raise ValueError("page shading data exceeds GPU scene limit")
            target = _mupdf.fz_device_rgb()
            target.thisown = False
            bbox = _mupdf.FzIrect(left, top, right, bottom)
            pixmap = _mupdf.fz_new_pixmap_with_bbox(
                target, bbox, _mupdf.FzSeparations(), 1)
            _mupdf.fz_clear_pixmap(pixmap)
            render_matrix = _mupdf.fz_concat(
                matrix, _mupdf.FzMatrix(scale, 0, 0, scale, 0, 0))
            shade.fz_paint_shade(
                _mupdf.FzColorspace(), render_matrix, pixmap,
                _mupdf.FzColorParams(color_params), bbox,
                _mupdf.FzOverprint())
            image = pymupdf.Pixmap(pixmap)
            if image.n != 4 or not image.alpha:
                raise ValueError("rasterized shading is not RGBA")
            cost = width * height * 4
            rgba = image.samples
            if len(rgba) < cost:
                raise ValueError("rasterized shading data is incomplete")
            bgra = _rgba_to_premul_bgra(rgba, width, height)
            self._append_item(VectorImage(
                bytes(bgra), width, height, width * 4,
                (width / scale, 0.0, 0.0, height / scale,
                 left / scale, top / scale),
                max(0.0, min(1.0, float(alpha)))))
            self._image_bytes += cost
        except Exception as error:
            self._set_failure(str(error))

    def begin_mask(self, _context, area, luminosity, colorspace, background,
                   color_params):
        try:
            if luminosity:
                background_argb = _device_color(
                    colorspace, background, 1.0, color_params)
            else:
                background_argb = 0
            self._append_item(MaskBegin(
                (float(area.x0), float(area.y0),
                 float(area.x1), float(area.y1)),
                bool(luminosity), background_argb))
            self._mask_depth += 1
            self._features.add("soft-mask")
        except Exception as error:
            self._set_failure(str(error))

    def end_mask(self, _context, function):
        if self._mask_depth <= 0:
            self._set_failure("unbalanced soft mask stack")
            return
        try:
            transfer = _transfer_function_samples(function)
            if transfer:
                self._features.add("soft-mask-transfer-function")
            self._append_item(MaskEnd(transfer))
        except Exception as error:
            self._set_failure(str(error))
            return
        self._mask_depth -= 1
        self._clip_depth += 1

    def begin_group(self, _context, _area, colorspace, isolated, knockout,
                    blendmode, alpha):
        try:
            self._features.add("transparency-group")
            opacity = float(alpha)
            mode = int(blendmode)
            passthrough = (
                not isolated and not knockout and mode == 0 and
                opacity >= 1.0 - 1e-6)
            if not 0 <= mode <= 15:
                raise ValueError("unsupported blend mode: %s" % mode)
            if mode:
                self._features.add("blend-mode")
            if colorspace:
                source = _mupdf.FzColorspace(colorspace)
                source.thisown = False
                channels = source.fz_colorspace_n()
                valid_device_space = (
                    _mupdf.fz_colorspace_is_device(source) and
                    (channels == 3 or (self._mask_depth and channels == 1)))
                pass_through_group = (
                    bool(isolated) and mode == 0 and
                    opacity >= 1.0 - 1e-6)
                if not valid_device_space and not (
                        pass_through_group or passthrough):
                    raise ValueError("unsupported transparency group colorspace")
            if not math.isfinite(opacity) or opacity < 0.0 or opacity > 1.0:
                raise ValueError("invalid transparency group opacity")
            if not passthrough:
                self._append_item(GroupPush(
                    opacity, mode, bool(isolated), bool(knockout)))
            self._group_depth += 1
            self._group_passthrough.append(passthrough)
        except Exception as error:
            self._set_failure(str(error))

    def end_group(self, _context):
        if self._group_depth <= 0:
            self._set_failure("unbalanced transparency group stack")
            return
        passthrough = self._group_passthrough.pop() \
            if self._group_passthrough else False
        if not passthrough:
            self._append_item(GroupPop())
        self._group_depth -= 1

    def begin_tile(self, _context, area, view, xstep, ystep, ctm, _id, _n):
        try:
            if self._tile_stack:
                raise ValueError("nested tile patterns are unsupported")
            self._features.add("tile-pattern")
            self._tile_stack.append(_TileState(
                len(self.items), _rect_tuple(area), _rect_tuple(view),
                float(xstep), float(ystep), _matrix(ctm)))
        except Exception as error:
            self._set_failure(str(error))
        return 0

    def end_tile(self, *_args):
        if not self._tile_stack:
            self._set_failure("unbalanced tile pattern stack")
            return
        state = self._tile_stack.pop()
        children = tuple(self.items[state.start:])
        del self.items[state.start:]
        try:
            if not children:
                return
            tiled = []
            for xoffset, yoffset in _tile_repeat_offsets(state):
                for child in children:
                    tiled.append(_offset_tile_item(
                        child, state, xoffset, yoffset))
            if tiled:
                self._features.add("vector-tile-pattern")
                self._extend_items(tiled)
        except Exception as error:
            self._set_failure(str(error))


def _validate_composite_context(items):
    """Explicit targets require properly nested group, clip and mask scopes."""
    scopes = []
    for item in items:
        if isinstance(item, (ClipPush, ClipStrokePush)):
            scopes.append("clip")
        elif isinstance(item, ClipPop):
            if not scopes or scopes[-1] != "clip":
                return "unbalanced composite clip stack"
            scopes.pop()
        elif isinstance(item, MaskBegin):
            scopes.append("mask")
        elif isinstance(item, MaskEnd):
            if not scopes or scopes[-1] != "mask":
                return "unbalanced composite mask stack"
            scopes[-1] = "clip"
        elif isinstance(item, GroupPush):
            if not item.isolated:
                return "unsupported non-isolated group in blended scene"
            scopes.append("group")
        elif isinstance(item, GroupPop):
            if not scopes or scopes[-1] != "group":
                return "unbalanced composite group stack"
            scopes.pop()
    return "unbalanced composite scope stack" if scopes else ""


def vector_page_from_pymupdf(
        page, raster_scale=1.0, timeout_seconds=None,
        *, aggressive_band_merge=False):
    """Return a complete GPU scene only when every operation is supported."""
    rect = page.rect
    scale = max(1.0, float(raster_scale))
    deadline = None
    if timeout_seconds is not None:
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    cookie = _mupdf.FzCookie()
    device = _DisplayListDevice(
        (rect.x0, rect.y0, rect.x1, rect.y1), scale, cookie, deadline)
    try:
        _mupdf.fz_run_page(
            page.this, device, _mupdf.FzMatrix(), cookie)
        if not device.failure and device._clip_depth:
            device.failure = "unbalanced clip stack"
        if not device.failure and device._group_depth:
            device.failure = "unbalanced transparency group stack"
        if not device.failure and device._mask_depth:
            device.failure = "unbalanced soft mask stack"
        if not device.failure and device._tile_stack:
            device.failure = "unbalanced tile pattern stack"
        if not device.failure:
            try:
                items, image_bytes, islanded = _flatten_or_cpu_island_groups(
                    tuple(device.items), page, scale, device._image_bytes)
                device.items = list(items)
                device._image_bytes = image_bytes
                if islanded:
                    device._features.add("cpu-island")
                    if islanded == "approximate":
                        device._features.add("cpu-island-approximate")
                compacted, fill_merged, text_merged, aggressive_merged = \
                    _compact_consecutive_fill_paths(
                        tuple(device.items),
                        aggressive_band_merge=aggressive_band_merge)
                gradient_compacted, gradient_merged = _compact_gradient_clip_triplets(
                    compacted)
                if gradient_merged:
                    compacted = gradient_compacted
                    device._features.add("gradient-clip-merge")
                if fill_merged or text_merged or gradient_merged:
                    device.items = list(compacted)
                if fill_merged:
                    device._features.add("baked-gradient-band-merge")
                if text_merged:
                    device._features.add("text-outline-merge")
                if aggressive_merged:
                    device._features.add("aggressive-band-merge")
            except Exception as error:
                device._set_failure(str(error))
        if not device.failure and ("blend-mode" in device._features or
                                   any(isinstance(item, MaskBegin) for item in device.items)):
            device.failure = _validate_composite_context(device.items)
    except Exception as error:
        device._set_failure(str(error))
    finally:
        _mupdf.fz_close_device(device)
    if device.failure:
        return VectorPage(
            False, reason=device.failure,
            features=tuple(sorted(device._features)),
            raster_scale=scale)
    items = tuple(device.items)
    paths = tuple(item for item in items if isinstance(item, VectorPath))
    return VectorPage(
        True, paths, items=items,
        features=tuple(sorted(device._features)),
        raster_scale=scale)
