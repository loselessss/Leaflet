"""Viewport-sized GPU compositor with bounded, on-demand CPU PDF tiles.

Direct2D draws supported PDF scenes; CPU tiles provide a fallback. Background
scene workers own separate PDF snapshots and never share the GUI's MuPDF state.
One CPU tile per timer tick yields between fallback rendering requests.
"""

from collections import OrderedDict
import math
import os
import pickle
import shutil
import subprocess
import tempfile
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QColor, QImage, QMouseEvent, QPainter, QPixmap,
                         QTransform)
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView, QOpenGLWidget, QWidget

from . import settings
from .d2d_backend import D2DSurface, probe_d2d_backend
from .widgets import (EDIT_BOX_COLOR, SEARCH_COLOR, SEARCH_CUR_COLOR, SEL_COLOR,
                      PageCanvas, qimage_from_render)

TILE_PIXELS = 512
TILE_CACHE_BYTES = 64 * 1024 * 1024
PREVIEW_PIXELS = 1_000_000
VIEWPORT_PIXELS = 6_000_000
MAX_VISIBLE_TILES = 48
GPU_SCENE_TIMEOUT_SECONDS = 1.0
FORCED_GPU_SCENE_TIMEOUT_SECONDS = 10.0
AUTO_GPU_SCENE_COMPLEXITY_LIMIT = 3000
DEFERRED_GPU_SCENE_TIMEOUT_SECONDS = 10.0
GPU_SCENE_WORKER_TIMEOUT_SECONDS = 12.0
VECTOR_SCENE_REFINE_DELAY_MS = 120
ZOOM_ANIMATION_DURATION_SECONDS = 0.12
ZOOM_ANIMATION_FRAME_MS = 16
_CURRENT_ZOOM_ANCHOR = object()


def _axis_aligned_clip_rect(item):
    """Return a simple local rectangle that stays axis-aligned on the page."""
    transform = item.transform
    if transform is not None and (abs(transform[1]) > 1e-8 or
                                  abs(transform[2]) > 1e-8):
        return None
    points = []
    for command in item.commands:
        if command[0] in ("move", "line") and len(command) == 3:
            points.append((float(command[1]), float(command[2])))
        elif command[0] != "close":
            return None
    if len(points) == 5 and points[-1] == points[0]:
        points.pop()
    if len(points) != 4 or len(set(points)) != 4:
        return None
    xs = {point[0] for point in points}
    ys = {point[1] for point in points}
    if len(xs) != 2 or len(ys) != 2:
        return None
    closed = points[1:] + points[:1]
    if any(first[0] != second[0] and first[1] != second[1]
           for first, second in zip(points, closed)):
        return None
    return min(xs), min(ys), max(xs), max(ys)


def opengl_allowed():
    return (os.name == "nt" and
            os.environ.get("QT_QPA_PLATFORM", "").lower() not in ("offscreen", "minimal") and
            os.environ.get("SPDF_DISABLE_GPU", "").lower() not in ("1", "true", "yes") and
            settings.render_backend() != "cpu")


class _ReaderCanvas(PageCanvas):
    """Reuse selection/link interaction state, not a page-sized native surface."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(owner)
        self.hide()

    def update(self, *args):
        self.owner.viewport().update()

    def setCursor(self, cursor):
        super().setCursor(cursor)
        self.owner.viewport().setCursor(cursor)

    def _page_point(self, pos):
        point = QPointF(pos)
        for page, _pixmap, rect in self._pages:
            if rect.contains(point):
                inverse, valid = self.owner._page_transforms[page].inverted()
                if valid:
                    return page, inverse.map(point)
        return None


class ReaderPageView(QGraphicsView):
    zoom_changed = pyqtSignal(float)
    page_flip = pyqtSignal(int)
    viewport_changed = pyqtSignal()
    render_failed = pyqtSignal(str)
    render_device_changed = pyqtSignal(str)
    ZOOM_MIN, ZOOM_MAX = 0.1, 8.0
    FLIP_THRESHOLD = 120

    def __init__(self, parent=None, *, use_opengl=None):
        super().__init__(parent)
        self.setObjectName("documentViewport")
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignCenter)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.zoom = 1.0
        self._flip_accum = 0
        self._document = None
        self._page_sizes = {}
        self._page_transforms = {}
        self._rotations = {}
        self._previews = {}
        self._tiles = OrderedDict()
        self._tile_bytes = 0
        self._pending = []
        self._wanted = set()
        self._updating = False
        self._gpu_surface = None
        self._d2d_surface = None
        self._d2d_size = None
        self._d2d_previews = {}
        self._d2d_tiles = {}
        self._vector_pages = {}
        self._d2d_vector_paths = {}
        self._reported_render_device = None
        self._rasterized_pages = {}
        self._tile_timer = QTimer(self)
        self._tile_timer.setSingleShot(True)
        self._tile_timer.timeout.connect(self._render_next_tile)
        self._refine_timer = QTimer(self)
        self._refine_timer.setSingleShot(True)
        self._refine_timer.timeout.connect(self._plan_tiles)
        self._vector_refine_timer = QTimer(self)
        self._vector_refine_timer.setSingleShot(True)
        self._vector_refine_timer.timeout.connect(
            self._refresh_next_vector_page)
        self._vector_refine_pages = []
        self._vector_refine_document = None
        self._vector_refine_scale = 1.0
        self._vector_refine_process = None
        self._vector_refine_job = None
        self._vector_refine_attempted = set()
        self._vector_refine_poll_timer = QTimer(self)
        self._vector_refine_poll_timer.setInterval(30)
        self._vector_refine_poll_timer.timeout.connect(
            self._poll_vector_refine_worker)
        self._zoom_animation_timer = QTimer(self)
        self._zoom_animation_timer.setSingleShot(True)
        self._zoom_animation_timer.timeout.connect(self._animate_zoom_step)
        self._zoom_animation_start = self.zoom
        self._zoom_animation_target = self.zoom
        self._zoom_animation_position = None
        self._zoom_animation_anchor = None
        self._zoom_animation_started = 0.0
        self.canvas = _ReaderCanvas(self)
        enable_opengl = opengl_allowed() if use_opengl is None else use_opengl
        render_mode = settings.render_backend() if use_opengl is None else "auto"
        self._render_mode = render_mode
        d2d = probe_d2d_backend() if enable_opengl else None
        self._backend_failure = (d2d.reason if d2d is not None and
                                 not d2d.available else "")
        self._d2d_requested = bool(
            d2d is not None and d2d.available and
            (render_mode != "gpu" or d2d.driver == "hardware"))
        if self._d2d_requested:
            viewport = QWidget()
            viewport.setAttribute(Qt.WA_NativeWindow)
            viewport.setAttribute(Qt.WA_OpaquePaintEvent)
            viewport.setAttribute(Qt.WA_NoSystemBackground)
            self.setViewport(viewport)
        elif enable_opengl and render_mode != "gpu":
            try:
                self._gpu_surface = QOpenGLWidget()
                self.setViewport(self._gpu_surface)
            except (RuntimeError, ImportError):
                self._gpu_surface = None
                self.setViewport(QWidget())
        self.viewport().setObjectName("documentViewportSurface")
        self.setMouseTracking(True)
        self.canvas.refresh_cursor()
        self.canvas.pan_requested.connect(self._pan_canvas)
        self.horizontalScrollBar().valueChanged.connect(self._viewport_moved)
        self.verticalScrollBar().valueChanged.connect(self._viewport_moved)

    @property
    def composition_backend(self):
        if self._d2d_surface is not None:
            return "direct2d"
        return "opengl" if self._gpu_surface is not None and self._gpu_surface.isValid() else "cpu"

    @property
    def render_device(self):
        if self._d2d_surface is not None:
            return "gpu" if self._d2d_surface.info.driver == "hardware" else "cpu"
        if self._gpu_surface is not None and self._gpu_surface.isValid():
            return "gpu"
        return "cpu"

    def render_diagnostic(self, page):
        """Return the actual per-page display path for optional UI diagnostics."""
        if self._d2d_surface is not None and self.render_device != "gpu":
            return {"mode": "cpu", "reason": "Direct2D WARP",
                    "features": ()}
        if self._d2d_requested:
            scene = self._vector_pages.get(page)
            if scene is None:
                return {"mode": "pending", "reason": "scene pending",
                        "features": ()}
            if not scene.supported:
                if scene.reason in (
                        "GPU scene deferred by complexity probe",
                        "GPU scene time budget exceeded"):
                    return {"mode": "pending", "reason": scene.reason,
                            "features": scene.features}
                return {"mode": "fallback", "reason": scene.reason,
                        "features": scene.features}
            bitmap_features = {"image", "stencil", "raster-shading", "clip-mask", "cpu-island"}
            mode = ("composite" if bitmap_features.intersection(scene.features)
                    else "direct")
            return {"mode": mode, "reason": "",
                    "features": scene.features}
        if self.composition_backend == "opengl":
            return {"mode": "composite", "reason": "OpenGL CPU tiles",
                    "backend_failure": self._backend_failure, "features": ()}
        return {"mode": "cpu", "reason": self._backend_failure or "PyMuPDF",
                "features": ()}

    def _vector_raster_scale(self):
        scale = max(1.0, self.zoom * self.viewport().devicePixelRatioF())
        bucket = 1.0
        while bucket < scale and bucket < self.ZOOM_MAX:
            bucket *= 2.0
        return bucket

    def _gpu_vector_page(self, document, page):
        scale = self._vector_raster_scale()
        # Large on-disk scenes can take over a second to decode and replay
        # source images. Only inspect the in-memory cache before the cheap
        # complexity probe; deferred workers restore disk scenes off the UI.
        cached = document.cached_gpu_vector_page(page, scale, memory_only=True)
        if cached is not None:
            return cached
        if self._render_mode == "auto":
            score, _operations = document.gpu_scene_complexity(page)
            if score >= AUTO_GPU_SCENE_COMPLEXITY_LIMIT:
                from .gpu_raster import VectorPage
                return VectorPage(
                    False, reason="GPU scene deferred by complexity probe",
                    features=("deferred-scene",), raster_scale=scale)
        return document.gpu_vector_page(
            page, scale,
            timeout_seconds=self._gpu_scene_timeout_seconds())

    def _gpu_scene_timeout_seconds(self):
        return (FORCED_GPU_SCENE_TIMEOUT_SECONDS
                if self._render_mode == "gpu"
                else GPU_SCENE_TIMEOUT_SECONDS)

    def _refresh_vector_page_for_zoom(self, page):
        scene = self._vector_pages.get(page)
        if self._document is None or scene is None or not scene.supported:
            return scene
        if "image-downsample" not in scene.features:
            return scene
        target_scale = self._vector_raster_scale()
        if scene.raster_scale >= target_scale:
            return scene
        refreshed = self._document.gpu_vector_page(
            page, target_scale,
            timeout_seconds=self._gpu_scene_timeout_seconds())
        if not refreshed.supported and refreshed.reason == \
                "GPU scene time budget exceeded":
            return scene
        if refreshed is not scene:
            self._discard_native_vector_page(page)
        self._vector_pages[page] = refreshed
        return refreshed

    def _schedule_vector_refine(self, delay=VECTOR_SCENE_REFINE_DELAY_MS):
        self._vector_refine_timer.stop()
        self._vector_refine_pages.clear()
        self._vector_refine_document = self._document
        self._vector_refine_scale = self._vector_raster_scale()
        if self._document is None or not self.isVisible():
            return
        exposed = self._visible_scene_rect()
        candidates = []
        for page, _preview, rect in self.canvas._pages:
            scene = self._vector_pages.get(page)
            if scene is None:
                continue
            generation = getattr(self._document, "render_generation", 0)
            key = (generation, page, self._vector_refine_scale)
            deferred = (
                self._render_mode == "auto" and not scene.supported and
                scene.reason in ("GPU scene deferred by complexity probe",
                                 "GPU scene time budget exceeded") and
                key not in self._vector_refine_attempted)
            image_refine = (
                scene.supported and "image-downsample" in scene.features and
                scene.raster_scale < self._vector_refine_scale and
                key not in self._vector_refine_attempted)
            if not deferred and not image_refine:
                continue
            candidates.append((not rect.intersects(exposed), page))
        self._vector_refine_pages = [page for _hidden, page in sorted(candidates)]
        if self._vector_refine_pages:
            self._vector_refine_timer.start(max(0, int(delay)))

    def _refresh_next_vector_page(self):
        if not self._vector_refine_pages or \
                self._document is not self._vector_refine_document or \
                self._vector_raster_scale() != self._vector_refine_scale:
            self._vector_refine_pages.clear()
            return
        if self._vector_refine_process is not None:
            # Keep the newest settled-scale request queued while an older
            # snapshot is still being extracted.
            return
        page = self._vector_refine_pages.pop(0)
        scene = self._vector_pages.get(page)
        if self._render_mode in ("auto", "gpu") and scene is not None and (
                (not scene.supported and scene.reason in (
                    "GPU scene deferred by complexity probe",
                    "GPU scene time budget exceeded")) or
                (scene.supported and "image-downsample" in scene.features and
                 scene.raster_scale < self._vector_refine_scale)):
            self._start_vector_refine_worker(page)
            return
        try:
            self._refresh_vector_page_for_zoom(page)
        except Exception as error:
            self.render_failed.emit(str(error))
        self.viewport().update()
        if self._vector_refine_pages:
            self._vector_refine_timer.start(0)

    def _start_vector_refine_worker(self, page):
        if self._document is None or self._vector_refine_process is not None:
            return
        scale = self._vector_refine_scale
        generation = getattr(self._document, "render_generation", 0)
        key = (generation, page, scale)
        self._vector_refine_attempted.add(key)
        directory = tempfile.mkdtemp(prefix="spdf-gpu-scene-")
        snapshot_path = os.path.join(directory, "page.pdf")
        result_path = os.path.join(directory, "scene.pickle")
        try:
            worker_page = self._document.write_gpu_page_snapshot(page, snapshot_path)
            from .paths import gpu_scene_worker_command, is_frozen, resource
            command = gpu_scene_worker_command()
            arguments = [snapshot_path, result_path, "--scale", str(scale),
                         "--page", str(worker_page),
                         "--timeout", str(DEFERRED_GPU_SCENE_TIMEOUT_SECONDS)]
            cache_key = self._document.gpu_scene_disk_cache_key(page, scale)
            if cache_key:
                arguments.extend(("--disk-cache-key", cache_key))
            from .gpu_raster import can_refine_images
            base = self._vector_pages.get(page)
            if can_refine_images(base) and base.raster_scale < scale:
                from dataclasses import replace
                from .gpu_raster import VectorImage
                # Refinement regenerates pixels; send only the scene recipe.
                recipe = replace(base, items=tuple(
                    replace(item, pixels=b"") if isinstance(item, VectorImage) else item
                    for item in base.items))
                base_path = os.path.join(directory, "base.pickle")
                with open(base_path, "wb") as stream:
                    pickle.dump(recipe, stream, protocol=pickle.HIGHEST_PROTOCOL)
                arguments.extend(["--base-scene", base_path])
            if os.environ.get("SPDF_GPU_AGGRESSIVE_BAND_MERGE", "").lower() in \
                    ("1", "true", "yes", "on"):
                arguments.append("--aggressive-band-merge")
            environment = None
            cwd = None
            if not is_frozen():
                cwd = resource()
                environment = dict(os.environ)
                previous = environment.get("PYTHONPATH", "")
                environment["PYTHONPATH"] = (cwd + os.pathsep + previous
                                               if previous else cwd)
            process = subprocess.Popen(
                command + arguments, cwd=cwd, env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as error:
            shutil.rmtree(directory, ignore_errors=True)
            self._finish_failed_vector_refine(page)
            self.render_failed.emit(str(error))
            if self._vector_refine_pages:
                self._vector_refine_timer.start(0)
            return
        self._vector_refine_process = process
        self._vector_refine_job = {
            "document": self._document, "generation": generation,
            "page": page, "scale": scale, "directory": directory,
            "result": result_path,
            "deadline": time.monotonic() + GPU_SCENE_WORKER_TIMEOUT_SECONDS,
        }
        self._vector_refine_poll_timer.start()

    def _poll_vector_refine_worker(self):
        process = self._vector_refine_process
        job = self._vector_refine_job
        if process is None or job is None:
            self._vector_refine_poll_timer.stop()
            return
        if process.poll() is None:
            if time.monotonic() < job["deadline"]:
                return
            if not job.get("terminating"):
                process.terminate()
                job["terminating"] = True
                job["deadline"] = time.monotonic() + 0.5
            else:
                process.kill()
            return
        self._vector_refine_poll_timer.stop()
        self._vector_refine_process = None
        self._vector_refine_job = None
        scene = None
        try:
            if process.returncode == 0 and os.path.isfile(job["result"]):
                with open(job["result"], "rb") as stream:
                    scene = pickle.load(stream)
        except Exception:
            scene = None
        finally:
            shutil.rmtree(job["directory"], ignore_errors=True)
        document = job["document"]
        current = (document is self._document and
                   job["generation"] == getattr(
                       document, "render_generation", 0) and
                   job["page"] in self._page_sizes)
        from .gpu_raster import VectorPage
        usable = isinstance(scene, VectorPage) and scene.supported
        scale_matches = (job["scale"] == self._vector_raster_scale() or
                         (usable and
                          "image-downsample" not in scene.features))
        if current and usable:
            document.install_gpu_vector_page(job["page"], scene, persist=False)
        if current and usable and scale_matches:
            self._discard_native_vector_page(job["page"])
            self._vector_pages[job["page"]] = scene
            self.viewport().update()
        elif current and not usable:
            self._finish_failed_vector_refine(job["page"])
        if self._vector_refine_pages:
            self._vector_refine_timer.start(0)

    def _finish_failed_vector_refine(self, page):
        # Keep a usable lower-resolution scene when image refinement fails.
        from .gpu_raster import VectorPage
        previous = self._vector_pages.get(page)
        if previous is None or not previous.supported:
            self._vector_pages[page] = VectorPage(
                False, reason="GPU scene preparation failed")
            self.viewport().update()

    def _stop_vector_refine_worker(self):
        self._vector_refine_poll_timer.stop()
        process = self._vector_refine_process
        job = self._vector_refine_job
        self._vector_refine_process = None
        self._vector_refine_job = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
        if job is not None:
            shutil.rmtree(job["directory"], ignore_errors=True)

    def rasterization_device(self, page):
        """Last completed page frame, not the device used to composite tiles.

        Decoding embedded images is not PDF rasterization. Only raster shading
        and CPU composition islands require CPU page-content rasterization.
        """
        if self._d2d_surface is None or self.render_device != "gpu":
            return "CPU"
        return self._rasterized_pages.get(page, "CPU")

    def _notify_render_device(self):
        device = self.render_device
        state = (device, tuple(sorted(self._rasterized_pages.items())))
        if state != self._reported_render_device:
            self._reported_render_device = state
            self.render_device_changed.emit(device)

    def _ensure_d2d(self):
        if not self._d2d_requested or self._d2d_surface is not None or not self.isVisible():
            return
        ratio = max(1.0, self.viewport().devicePixelRatioF())
        self._d2d_surface = D2DSurface(
            int(self.viewport().winId()),
            round(self.viewport().width() * ratio),
            round(self.viewport().height() * ratio),
            96.0 * ratio)
        self._d2d_size = (self.viewport().size(), ratio)
        self._notify_render_device()

    def _release_d2d_surface(self, *, disable=False):
        for _key, bitmap in tuple(self._d2d_previews.values()):
            bitmap.close()
        for _key, bitmap in tuple(self._d2d_tiles.values()):
            bitmap.close()
        for _scene, _draws, resources, retained in tuple(
                self._d2d_vector_paths.values()):
            if retained is not None:
                retained.close()
            for path in resources:
                path.close()
        self._d2d_previews.clear()
        self._d2d_tiles.clear()
        self._d2d_vector_paths.clear()
        if self._d2d_surface is not None:
            self._d2d_surface.close()
            self._d2d_surface = None
        self._d2d_size = None
        if disable:
            self._d2d_requested = False
            QTimer.singleShot(0, self._schedule_refine)
        self._rasterized_pages.clear()
        self._notify_render_device()

    def _discard_native_vector_page(self, page):
        cached = self._d2d_vector_paths.pop(page, None)
        if cached is None:
            return
        _scene, _draws, resources, retained = cached
        if retained is not None:
            retained.close()
        for resource in resources:
            resource.close()

    @staticmethod
    def _bitmap_bytes(pixmap):
        image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
        bits = image.constBits()
        bits.setsize(image.byteCount())
        return bytes(bits), image.width(), image.height(), image.bytesPerLine()

    def _native_bitmap(self, cache, key, pixmap):
        identity = pixmap.cacheKey()
        cached = cache.get(key)
        if cached is not None and cached[0] == identity and not cached[1].closed:
            return cached[1]
        if cached is not None:
            cached[1].close()
        pixels, width, height, stride = self._bitmap_bytes(pixmap)
        bitmap = self._d2d_surface.create_bitmap_bgra(pixels, width, height, stride)
        cache[key] = (identity, bitmap)
        return bitmap

    def _set_page_transform(self, transform):
        viewport_origin = self.mapFromScene(QPointF(0, 0))
        self._d2d_surface.set_transform(
            transform.m11(), transform.m12(), transform.m21(), transform.m22(),
            transform.dx() + viewport_origin.x(), transform.dy() + viewport_origin.y())

    def _set_item_transform(self, page_transform, item_transform):
        if item_transform is None:
            self._set_page_transform(page_transform)
            return
        ia, ib, ic, id_, ie, iff = item_transform
        pa, pb = page_transform.m11(), page_transform.m12()
        pc, pd = page_transform.m21(), page_transform.m22()
        pe, pf = page_transform.dx(), page_transform.dy()
        viewport_origin = self.mapFromScene(QPointF(0, 0))
        self._d2d_surface.set_transform(
            pa * ia + pc * ib,
            pb * ia + pd * ib,
            pa * ic + pc * id_,
            pb * ic + pd * id_,
            pa * ie + pc * iff + pe + viewport_origin.x(),
            pb * ie + pd * iff + pf + viewport_origin.y())

    def _native_vector_draws(self, page, scene):
        cached = self._d2d_vector_paths.get(page)
        if cached is not None and cached[0] is scene and \
                all(not path.closed for path in cached[2]):
            return cached[1]
        if cached is not None:
            if cached[3] is not None:
                cached[3].close()
            for path in cached[2]:
                path.close()
        from .gpu_raster import (ClipPop, ClipPush, ClipStrokePush, GroupPop,
                                 GroupPush, MaskBegin, MaskEnd, VectorImage,
                                 VectorLinearGradient, VectorPath,
                                 VectorRadialGradient)

        items = scene.drawables
        unique = {}
        bitmaps = {}
        stroke_styles = {}
        auxiliary = set()
        native_items = []
        for item in items:
            if isinstance(item, (ClipPop, GroupPush, GroupPop,
                                 MaskBegin, MaskEnd)):
                native_items.append(None)
                continue
            if isinstance(item, VectorImage):
                key = (id(item.pixels), item.width, item.height, item.stride)
                bitmap = bitmaps.get(key)
                if bitmap is None:
                    bitmap = self._d2d_surface.create_bitmap_bgra(
                        item.pixels, item.width, item.height, item.stride)
                    bitmaps[key] = bitmap
                native_items.append(bitmap)
                continue
            if isinstance(item, (VectorLinearGradient, VectorRadialGradient)):
                native_items.append(self._d2d_surface.create_path(
                    item.commands, even_odd=item.even_odd))
                continue
            if isinstance(item, ClipStrokePush):
                key = (item.commands, False)
                source = unique.get(key)
                if source is None:
                    source = self._d2d_surface.create_path(item.commands)
                    unique[key] = source
                    auxiliary.add(source)
                native_style = None
                if item.stroke_style is not None:
                    native_style = stroke_styles.get(item.stroke_style)
                    if native_style is None:
                        native_style = self._d2d_surface.create_stroke_style(
                            item.stroke_style)
                        stroke_styles[item.stroke_style] = native_style
                        auxiliary.add(native_style)
                native_items.append(self._d2d_surface.create_stroked_path(
                    source, item.stroke_width, native_style))
                continue
            key = (item.commands, item.even_odd)
            path = unique.get(key)
            if path is None:
                path = self._d2d_surface.create_path(
                    item.commands, even_odd=item.even_odd)
                unique[key] = path
            native_items.append(path)
        resources = {resource for resource in native_items
                     if resource is not None} | auxiliary
        draws = []
        composite_groups = any(
            isinstance(item, MaskBegin) or
            (isinstance(item, GroupPush) and
             (item.blend_mode or item.knockout)) for item in items)
        composite_clips = set()
        if composite_groups:
            open_clips = []
            for position, item in enumerate(items):
                if isinstance(item, (ClipPush, ClipStrokePush)):
                    open_clips.append(position)
                    continue
                if isinstance(item, MaskBegin):
                    composite_clips.update(
                        opener for opener in open_clips
                        if opener is not None)
                    # MaskEnd turns the capture into a clip that is closed by
                    # the following ClipPop, just like an explicit clip push.
                    open_clips.append(None)
                    continue
                if isinstance(item, GroupPush):
                    # A composite target cannot be entered while an ordinary
                    # Direct2D layer is open. Only clips that actually enclose
                    # the target switch need the more expensive bitmap-backed
                    # clip group; unrelated clips stay as native layers.
                    composite_clips.update(
                        opener for opener in open_clips
                        if opener is not None)
                    continue
                if isinstance(item, ClipPop) and open_clips:
                    open_clips.pop()
        axis_clips = {}
        if self._render_mode in ("auto", "gpu"):
            axis_clips = {
                position: rect
                for position, item in enumerate(items)
                if position not in composite_clips and
                isinstance(item, ClipPush) and
                (rect := _axis_aligned_clip_rect(item)) is not None
            }
        clip_groups = []
        index = 0
        while index < len(items):
            item = items[index]
            if isinstance(item, (ClipPush, ClipStrokePush)):
                composite_clip = index in composite_clips
                axis_rect = axis_clips.get(index)
                clip_kind = ("group" if composite_clip else
                             "axis" if axis_rect is not None else "path")
                clip_groups.append(clip_kind)
                kind = ("clip_group_push" if composite_clip else
                        "rect_clip_push" if axis_rect is not None else
                        "clip_push")
                values = ((item.transform, axis_rect)
                          if axis_rect is not None else (item.transform,))
                draws.append((kind, native_items[index], *values))
                index += 1
                continue
            if isinstance(item, ClipPop):
                clip_kind = clip_groups.pop()
                kind = ("clip_group_pop" if clip_kind == "group" else
                        "rect_clip_pop" if clip_kind == "axis" else
                        "clip_pop")
                draws.append((kind, None))
                index += 1
                continue
            if isinstance(item, GroupPush):
                if composite_groups:
                    draws.append(("composite_push", item.blend_mode,
                                  item.opacity, item.knockout))
                else:
                    draws.append(("group_push", item.opacity))
                index += 1
                continue
            if isinstance(item, GroupPop):
                draws.append(("composite_pop" if composite_groups else "group_pop", None))
                index += 1
                continue
            if isinstance(item, MaskBegin):
                kind = "composite_mask_begin" if composite_groups else "mask_begin"
                draws.append((kind, item.area, item.luminosity,
                              item.background_argb))
                index += 1
                continue
            if isinstance(item, MaskEnd):
                clip_groups.append("group" if composite_groups else "path")
                kind = "composite_mask_end" if composite_groups else "mask_end"
                draws.append((kind, item.transfer))
                index += 1
                continue
            if isinstance(item, VectorImage):
                draws.append(("image", native_items[index], item.opacity,
                              item.transform, item.interpolate))
                index += 1
                continue
            if isinstance(item, VectorLinearGradient):
                draws.append(("linear_gradient", native_items[index],
                              item.start, item.end, item.stops,
                              item.transform))
                index += 1
                continue
            if isinstance(item, VectorRadialGradient):
                draws.append(("radial_gradient", native_items[index],
                              item.center, item.origin, item.radius,
                              item.stops, item.transform))
                index += 1
                continue
            if not isinstance(item, VectorPath):
                raise ValueError("unsupported Direct2D scene item")
            if item.groupable and item.transform is not None and \
                    item.fill_argb is not None and \
                    item.stroke_argb is None:
                end = index + 1
                while end < len(items):
                    candidate = items[end]
                    if not isinstance(candidate, VectorPath) or \
                            not candidate.groupable or \
                            candidate.transform is None or \
                            candidate.fill_argb != item.fill_argb or \
                            candidate.stroke_argb is not None or \
                            candidate.even_odd != item.even_odd:
                        break
                    end += 1
                group = self._d2d_surface.create_geometry_group(
                    [(native_items[position], items[position].transform)
                     for position in range(index, end)],
                    even_odd=item.even_odd)
                resources.add(group)
                draws.append(("path", group, item.fill_argb, None,
                              item.stroke_width, None, None))
                index = end
                continue
            native_style = None
            if item.stroke_style is not None:
                native_style = stroke_styles.get(item.stroke_style)
                if native_style is None:
                    native_style = self._d2d_surface.create_stroke_style(
                        item.stroke_style)
                    stroke_styles[item.stroke_style] = native_style
                    resources.add(native_style)
            draws.append(("path", native_items[index], item.fill_argb,
                          item.stroke_argb, item.stroke_width, item.transform,
                          native_style))
            index += 1
        draws = tuple(draws)
        retained = None
        if getattr(type(self._d2d_surface), "supports_retained_scenes", False):
            width, height = self._page_sizes[page]
            retained = self._d2d_surface.create_scene(width, height, draws)
        self._d2d_vector_paths[page] = (scene, draws, resources, retained)
        return draws

    def _draw_vector_page(self, page, scene):
        draws = self._native_vector_draws(page, scene)
        page_transform = self._page_transforms[page]
        retained = self._d2d_vector_paths[page][3]
        if retained is not None:
            viewport_origin = self.mapFromScene(QPointF(0, 0))
            self._d2d_surface.draw_scene(retained, (
                page_transform.m11(), page_transform.m12(),
                page_transform.m21(), page_transform.m22(),
                page_transform.dx() + viewport_origin.x(),
                page_transform.dy() + viewport_origin.y()))
            return
        width, height = self._page_sizes[page]
        self._d2d_surface.fill_rect(0, 0, width, height, 0xffffffff)
        for kind, resource, *values in draws:
            if kind == "clip_group_push":
                self._set_item_transform(page_transform, values[0])
                self._d2d_surface.begin_clip_group(resource)
                continue
            if kind == "clip_group_pop":
                self._d2d_surface.end_clip_group()
                continue
            if kind == "rect_clip_push":
                # Retained ABI v19 scenes use an axis-aligned clip. Keep the
                # direct fallback on the exact geometry path.
                self._set_item_transform(page_transform, values[0])
                self._d2d_surface.push_clip_path(resource)
                continue
            if kind == "rect_clip_pop":
                self._d2d_surface.pop_clip()
                continue
            if kind == "clip_push":
                self._set_item_transform(page_transform, values[0])
                self._d2d_surface.push_clip_path(resource)
                continue
            if kind == "clip_pop":
                self._d2d_surface.pop_clip()
                continue
            if kind == "group_push":
                self._set_item_transform(page_transform, None)
                self._d2d_surface.push_opacity_layer(resource)
                continue
            if kind == "group_pop":
                self._d2d_surface.pop_layer()
                continue
            if kind == "composite_push":
                self._d2d_surface.begin_composite_group(
                    resource, values[0], values[1])
                continue
            if kind == "composite_pop":
                self._d2d_surface.end_composite_group()
                continue
            if kind in ("mask_begin", "composite_mask_begin"):
                area, luminosity, background_argb = resource, *values
                self._set_item_transform(page_transform, None)
                begin_mask = (self._d2d_surface.begin_composite_mask
                              if kind == "composite_mask_begin"
                              else self._d2d_surface.begin_mask)
                begin_mask(area, luminosity, background_argb)
                continue
            if kind in ("mask_end", "composite_mask_end"):
                self._d2d_surface.set_transform(1, 0, 0, 1, 0, 0)
                if kind == "composite_mask_end":
                    self._d2d_surface.end_composite_mask(resource)
                else:
                    self._d2d_surface.end_mask(resource)
                continue
            if kind == "image":
                opacity, transform, interpolate = values
                self._set_item_transform(page_transform, transform)
                self._d2d_surface.draw_bitmap(
                    resource, 0, 0, 1, 1, opacity, interpolate=interpolate)
                continue
            if kind == "linear_gradient":
                start, end, stops, transform = values
                self._set_item_transform(page_transform, transform)
                self._d2d_surface.fill_linear_gradient(
                    resource, start, end, stops)
                continue
            if kind == "radial_gradient":
                center, origin, radius, stops, transform = values
                self._set_item_transform(page_transform, transform)
                self._d2d_surface.fill_radial_gradient(
                    resource, center, origin, radius, stops)
                continue
            fill_argb, stroke_argb, stroke_width, transform, stroke_style = \
                values
            self._set_item_transform(page_transform, transform)
            if fill_argb is not None:
                self._d2d_surface.fill_path(resource, fill_argb)
            if stroke_argb is not None:
                if stroke_style is None:
                    self._d2d_surface.stroke_path(
                        resource, stroke_argb, stroke_width)
                else:
                    self._d2d_surface.stroke_path(
                        resource, stroke_argb, stroke_width, stroke_style)
        self._set_page_transform(page_transform)

    def _draw_d2d_overlays(self):
        controller = getattr(self, "object_controller", None)
        if controller is not None:
            controller.paint_native(self._d2d_surface)
        canvas = self.canvas
        for rects, color in ((canvas._search_rects, SEARCH_COLOR),
                             (canvas._sel_rects, SEL_COLOR)):
            for rect in rects:
                self._d2d_surface.fill_rect(
                    rect.left(), rect.top(), rect.right(), rect.bottom(), color.rgba())
        if canvas._search_cur is not None:
            rect = canvas._search_cur
            self._d2d_surface.fill_rect(
                rect.left(), rect.top(), rect.right(), rect.bottom(),
                SEARCH_CUR_COLOR.rgba())
        for rect in canvas._edit_boxes:
            self._d2d_surface.stroke_rect(
                rect.left(), rect.top(), rect.right(), rect.bottom(),
                EDIT_BOX_COLOR.rgba(), 1.0 / max(0.1, self.zoom))

    def _paint_d2d(self):
        ratio = max(1.0, self.viewport().devicePixelRatioF())
        size = (self.viewport().size(), ratio)
        if size != self._d2d_size:
            self._d2d_surface.resize(
                round(self.viewport().width() * ratio),
                round(self.viewport().height() * ratio), 96.0 * ratio)
            self._d2d_size = size
        exposed = self._visible_scene_rect()
        self._d2d_surface.begin_frame(0xffe8e8e8)
        rasterized = {}
        for page, preview, rect in self.canvas._pages:
            if not rect.intersects(exposed):
                continue
            transform = self._page_transforms[page]
            self._set_page_transform(transform)
            width, height = self._page_sizes[page]
            vector_scene = self._vector_pages.get(page)
            if vector_scene is not None and vector_scene.supported:
                self._draw_vector_page(page, vector_scene)
                rasterized[page] = ("CPU+GPU" if
                    {"raster-shading", "cpu-island"}.intersection(vector_scene.features)
                    else "GPU")
            else:
                rasterized[page] = "CPU"
                bitmap = self._native_bitmap(self._d2d_previews, page, preview)
                self._d2d_surface.draw_bitmap(bitmap, 0, 0, width, height)
                for key, (pixmap, region) in self._tiles.items():
                    if key not in self._wanted or key[0] != page:
                        continue
                    if transform.mapRect(region).intersects(exposed):
                        tile = self._native_bitmap(self._d2d_tiles, key, pixmap)
                        self._d2d_surface.draw_bitmap(
                            tile, region.left(), region.top(),
                            region.right(), region.bottom())
            if page == self.canvas._active_page:
                self._draw_d2d_overlays()
        self._d2d_surface.end_frame()
        self._rasterized_pages = rasterized
        self._notify_render_device()

    def paintEvent(self, event):
        if self._d2d_requested:
            try:
                self._ensure_d2d()
                if self._d2d_surface is not None:
                    self._paint_d2d()
                    event.accept()
                    return
            except (OSError, RuntimeError, ValueError) as error:
                # A device-loss or native-load failure must never blank the PDF.
                self._backend_failure = str(error)
                self._release_d2d_surface(disable=True)
        super().paintEvent(event)

    def _verify_gpu(self):
        if self._gpu_surface is not None and not self._gpu_surface.isValid():
            # Keep document, image cache, scroll position and interaction state.
            self._gpu_surface = None
            self.setViewport(QWidget())
            self.viewport().setObjectName("documentViewportSurface")
            self.setMouseTracking(True)
            self.canvas.refresh_cursor()
            self.viewport().update()
        self._notify_render_device()

    def render_document(self, document, pages, active_page):
        self.stop_rendering()
        self._rasterized_pages.clear()
        changed = document is not self._document
        if changed:
            self._vector_refine_attempted.clear()
            if (self._document is None or
                    os.path.normcase(os.path.abspath(self._document.path)) !=
                    os.path.normcase(os.path.abspath(document.path))):
                self._rotations.clear()
            self._previews.clear()
            for _identity, bitmap in tuple(self._d2d_previews.values()):
                bitmap.close()
            self._d2d_previews.clear()
            self._vector_pages.clear()
            for _scene, _draws, resources, retained in tuple(
                    self._d2d_vector_paths.values()):
                if retained is not None:
                    retained.close()
                for path in resources:
                    path.close()
            self._d2d_vector_paths.clear()
            self._clear_tiles()
        self._document = document
        pages = list(pages)
        self._previews = {p: pix for p, pix in self._previews.items() if p in pages}
        for page in tuple(self._d2d_previews):
            if page not in pages:
                _identity, bitmap = self._d2d_previews.pop(page)
                bitmap.close()
        for page in tuple(self._d2d_vector_paths):
            if page not in pages:
                self._discard_native_vector_page(page)
        self._page_sizes = {p: document.page_size(p) for p in pages}
        for page in pages:
            if page not in self._previews:
                w, h = self._page_sizes[page]
                scale = min(0.75, math.sqrt(PREVIEW_PIXELS / max(1, w * h)))
                image = qimage_from_render(*document.render(page, scale))
                self._previews[page] = QPixmap.fromImage(image)
        # Document invalidation owns the scene cache. Ask it on every refresh
        # so an edit on the same page cannot leave stale native geometry here.
        self._vector_pages = {
            page: self._gpu_vector_page(document, page) for page in pages
        } if self._d2d_requested else {}
        self.canvas._active_page = active_page
        self._layout_pages()
        self._schedule_refine()
        self._schedule_vector_refine()
        self._notify_render_device()

    def page_rotation(self, page):
        return self._rotations.get(page, 0)

    def displayed_page_size(self, document, page):
        w, h = document.page_size(page)
        return (h, w) if self.page_rotation(page) % 180 else (w, h)

    def rotate_page_view(self, page, degrees):
        """Rotate display geometry only; never mutate the PDF or its history."""
        if self._document is None or page not in self._page_sizes:
            return
        if degrees % 90:
            raise ValueError("View rotation must be a multiple of 90 degrees")
        angle = (self.page_rotation(page) + degrees) % 360
        if angle:
            self._rotations[page] = angle
        else:
            self._rotations.pop(page, None)
        self.stop_rendering()
        self._layout_pages()
        self._schedule_refine()

    def _layout_pages(self):
        self._updating = True
        try:
            left, height = 0.0, 0.0
            self.canvas.zoom = self.zoom
            self.canvas._pages = []
            self._page_transforms = {}
            for page, (w, h) in self._page_sizes.items():
                angle = self.page_rotation(page)
                transform = QTransform().translate(left, 0)
                offset = {0: (0, 0), 90: (h, 0), 180: (w, h), 270: (0, w)}[angle]
                transform.translate(offset[0] * self.zoom, offset[1] * self.zoom)
                transform.rotate(angle)
                transform.scale(self.zoom, self.zoom)
                self._page_transforms[page] = transform
                rect = transform.mapRect(QRectF(0, 0, w, h))
                self.canvas._pages.append((page, self._previews[page], rect))
                left = rect.right() + 16
                height = max(height, rect.height())
            self.canvas._pix = next(iter(self._previews.values()), None)
            self.setSceneRect(QRectF(0, 0, max(0, left - 16), height))
        finally:
            self._updating = False
        self.viewport().update()
        self.viewport_changed.emit()

    def _apply_preview_zoom(
            self, zoom, position=None, anchor=_CURRENT_ZOOM_ANCHOR):
        if position is None:
            position = self.viewport().rect().center()
        if anchor is _CURRENT_ZOOM_ANCHOR:
            anchor = self.canvas._page_point(self.mapToScene(position))
        old_zoom = self.zoom
        self.zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        self.stop_rendering(
            keep_zoom_animation=True, keep_vector_refine_worker=True)
        self._layout_pages()
        if anchor is not None:
            page, point = anchor
            for index, _pix, rect in self.canvas._pages:
                if index == page:
                    target = self._page_transforms[page].map(point)
                    actual = self.mapToScene(position)
                    self.horizontalScrollBar().setValue(
                        self.horizontalScrollBar().value() + round(target.x() - actual.x()))
                    self.verticalScrollBar().setValue(
                        self.verticalScrollBar().value() + round(target.y() - actual.y()))
                    break
        self._schedule_refine(90)
        if self.zoom != old_zoom:
            self._schedule_vector_refine()
        self.viewport_changed.emit()
        if self.zoom != old_zoom:
            self.zoom_changed.emit(self.zoom)

    def preview_zoom(self, zoom, position=None):
        self._zoom_animation_timer.stop()
        self._zoom_animation_target = max(
            self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        self._apply_preview_zoom(self._zoom_animation_target, position)

    def _start_zoom_animation(self, zoom, position=None):
        target = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if target == self.zoom:
            self._zoom_animation_timer.stop()
            return
        if position is None:
            position = self.viewport().rect().center()
        self._zoom_animation_start = self.zoom
        self._zoom_animation_target = target
        self._zoom_animation_position = position
        self._zoom_animation_anchor = self.canvas._page_point(
            self.mapToScene(position))
        self._zoom_animation_started = time.monotonic()
        self._zoom_animation_timer.start(0)

    def _animate_zoom_step(self):
        elapsed = max(0.0, time.monotonic() - self._zoom_animation_started)
        progress = min(1.0, elapsed / ZOOM_ANIMATION_DURATION_SECONDS)
        eased = 1.0 - (1.0 - progress) ** 3
        zoom = (self._zoom_animation_target if progress >= 1.0 else
                self._zoom_animation_start +
                (self._zoom_animation_target - self._zoom_animation_start) * eased)
        self._apply_preview_zoom(
            zoom, self._zoom_animation_position, self._zoom_animation_anchor)
        if progress < 1.0:
            self._zoom_animation_timer.start(ZOOM_ANIMATION_FRAME_MS)

    def _visible_scene_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _schedule_refine(self, delay=40):
        self._tile_timer.stop()
        self._pending.clear()
        if self._document is not None and self.isVisible():
            self._refine_timer.start(delay)

    def _viewport_moved(self, *_args):
        if self._updating:
            return
        self.viewport().update()
        self.viewport_changed.emit()
        self._schedule_refine()

    def _plan_tiles(self):
        self._pending.clear()
        self._wanted.clear()
        if self._document is None or not self.isVisible():
            return
        exposed = self._visible_scene_rect()
        # Keep small text smooth at fit-page zoom without letting HiDPI or
        # oversized windows create unbounded raster requests.
        supersample = min(2.0, 2.0 / max(1.0, self.zoom))
        ratio = min(max(supersample, self.viewport().devicePixelRatioF()),
                    math.sqrt(VIEWPORT_PIXELS / max(1, exposed.width() * exposed.height())))
        scale = round(self.zoom * ratio, 6)
        requests = []
        for page, _pixmap, rect in self.canvas._pages:
            visible = rect.intersected(exposed)
            if visible.isEmpty():
                continue
            vector_scene = self._vector_pages.get(page)
            if self._d2d_requested and vector_scene is not None and vector_scene.supported:
                continue
            inverse, _valid = self._page_transforms[page].inverted()
            region = inverse.mapRect(visible)
            local = QRectF(region.x() * scale, region.y() * scale,
                           region.width() * scale, region.height() * scale)
            for y in range(max(0, math.floor(local.top() / TILE_PIXELS)),
                           math.ceil(local.bottom() / TILE_PIXELS)):
                for x in range(max(0, math.floor(local.left() / TILE_PIXELS)),
                               math.ceil(local.right() / TILE_PIXELS)):
                    key = (page, scale, x, y)
                    distance = ((x + 0.5) * TILE_PIXELS - local.center().x()) ** 2 + \
                               ((y + 0.5) * TILE_PIXELS - local.center().y()) ** 2
                    requests.append((distance, key))
        for _distance, key in sorted(requests)[:MAX_VISIBLE_TILES]:
            self._wanted.add(key)
            if key in self._tiles:
                self._tiles.move_to_end(key)
            else:
                self._pending.append(key)
        if self._pending:
            self._tile_timer.start(0)
        self.viewport().update()

    def _render_next_tile(self):
        if not self._pending or self._document is None or not self.isVisible():
            return
        key = self._pending.pop(0)
        page, scale, x, y = key
        if page not in self._page_sizes:
            return
        # One-pixel overlap prevents hairline gaps from rounded clip boundaries.
        clip = ((x * TILE_PIXELS - 1) / scale, (y * TILE_PIXELS - 1) / scale,
                ((x + 1) * TILE_PIXELS + 1) / scale,
                ((y + 1) * TILE_PIXELS + 1) / scale)
        try:
            px, py, w, h, stride, samples = self._document.render_region(page, scale, clip)
            pixmap = QPixmap.fromImage(qimage_from_render(w, h, stride, samples))
        except Exception as error:
            self._pending.clear()
            self.render_failed.emit(str(error))
            return
        tile = (pixmap, QRectF(px / scale, py / scale, w / scale, h / scale))
        cost = pixmap.width() * pixmap.height() * 4
        while self._tiles and self._tile_bytes + cost > TILE_CACHE_BYTES:
            old_key, (old_pixmap, _rect) = self._tiles.popitem(last=False)
            self._tile_bytes -= old_pixmap.width() * old_pixmap.height() * 4
            native = self._d2d_tiles.pop(old_key, None)
            if native is not None:
                native[1].close()
        self._tiles[key] = tile
        self._tile_bytes += cost
        self.viewport().update()
        if self._pending:
            self._tile_timer.start(1)

    def drawBackground(self, painter, exposed):
        painter.fillRect(exposed, QColor("#e8e8e8"))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        for page, preview, rect in self.canvas._pages:
            if not rect.intersects(exposed):
                continue
            transform = self._page_transforms[page]
            w, h = self._page_sizes[page]
            page_rect = QRectF(0, 0, w, h)
            painter.save()
            painter.setTransform(transform, True)
            painter.setClipRect(page_rect, Qt.IntersectClip)
            painter.drawPixmap(page_rect, preview, QRectF(preview.rect()))
            for key, (pixmap, region) in self._tiles.items():
                if key not in self._wanted or key[0] != page:
                    continue
                if transform.mapRect(region).intersects(exposed):
                    painter.drawPixmap(region, pixmap, QRectF(pixmap.rect()))
            if page == self.canvas._active_page:
                self.canvas.paint_overlays(painter, zoom=1, origin=QPointF())
                controller = getattr(self, "object_controller", None)
                if controller is not None:
                    controller.paint(painter)
            painter.restore()

    def _clear_tiles(self):
        self._tiles.clear()
        for _identity, bitmap in tuple(self._d2d_tiles.values()):
            bitmap.close()
        self._d2d_tiles.clear()
        self._tile_bytes = 0
        self._wanted.clear()

    def stop_rendering(self, *, keep_zoom_animation=False,
                       keep_vector_refine_worker=False):
        self._refine_timer.stop()
        self._tile_timer.stop()
        self._vector_refine_timer.stop()
        if not keep_vector_refine_worker:
            self._stop_vector_refine_worker()
        if not keep_zoom_animation:
            self._zoom_animation_timer.stop()
        self._pending.clear()
        self._vector_refine_pages.clear()

    def clear(self):
        self.stop_rendering()
        self._document = None
        self._previews.clear()
        for _identity, bitmap in tuple(self._d2d_previews.values()):
            bitmap.close()
        self._d2d_previews.clear()
        for _scene, _draws, resources, retained in tuple(
                self._d2d_vector_paths.values()):
            if retained is not None:
                retained.close()
            for path in resources:
                path.close()
        self._d2d_vector_paths.clear()
        self._page_sizes.clear()
        self._page_transforms.clear()
        self._rotations.clear()
        self._vector_pages.clear()
        self._clear_tiles()
        self.canvas.clear()
        self.setSceneRect(QRectF())
        self.viewport_changed.emit()

    def set_interaction_mode(self, mode):
        self.canvas.set_interaction_mode(mode)

    def _pan_canvas(self, delta):
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())

    def visible_page_rect(self):
        page = self.canvas.active_page_rect()
        visible = page.intersected(self._visible_scene_rect())
        if page.isEmpty() or visible.isEmpty() or visible == page:
            return None
        return QRectF((visible.x() - page.x()) / page.width(),
                      (visible.y() - page.y()) / page.height(),
                      visible.width() / page.width(), visible.height() / page.height())

    def center_on_page_fraction(self, point):
        page = self.canvas.active_page_rect()
        if not page.isEmpty():
            self.centerOn(page.left() + max(0, min(1, point.x())) * page.width(),
                          page.top() + max(0, min(1, point.y())) * page.height())
            self.viewport_changed.emit()

    def ensure_rect_visible(self, rect):
        transform = self._page_transforms.get(self.canvas._active_page)
        if transform is not None:
            self.ensureVisible(transform.mapRect(rect), 40, 40)

    def center_on_document_point(self, point):
        transform = self._page_transforms.get(self.canvas._active_page)
        if transform is not None:
            self.centerOn(transform.map(point))

    def _forward_mouse(self, name, event):
        controller = getattr(self, "object_controller", None)
        if controller is not None and controller.mouse(name, event):
            event.accept()
            return
        point = self.mapToScene(event.pos())
        proxy = QMouseEvent(event.type(), point, QPointF(event.globalPos()),
                            event.button(), event.buttons(), event.modifiers())
        getattr(self.canvas, name)(proxy)
        event.accept()

    def mousePressEvent(self, event):
        self._forward_mouse("mousePressEvent", event)

    def mouseMoveEvent(self, event):
        self._forward_mouse("mouseMoveEvent", event)

    def mouseReleaseEvent(self, event):
        self._forward_mouse("mouseReleaseEvent", event)

    def mouseDoubleClickEvent(self, event):
        self._forward_mouse("mouseDoubleClickEvent", event)

    def keyPressEvent(self, event):
        controller = getattr(self, "object_controller", None)
        if controller is not None and controller.active and event.key() == Qt.Key_Escape:
            controller.cancel()
            self.viewport().update()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        point = self.canvas._activate_at(self.mapToScene(event.pos()))
        if point is not None:
            self.canvas.context_requested.emit(point, event.globalPos())
        event.accept()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            base = (self._zoom_animation_target
                    if self._zoom_animation_timer.isActive() else self.zoom)
            zoom = (base * (1.25 if delta > 0 else 0.8)
                    if event.modifiers() & Qt.ControlModifier else
                    round(base + (0.01 if delta > 0 else -0.01), 2))
            self._start_zoom_animation(zoom, event.pos())
            event.accept()
            return
        bar = self.verticalScrollBar()
        if (delta < 0 and bar.value() >= bar.maximum()) or \
                (delta > 0 and bar.value() <= bar.minimum()):
            self._flip_accum += delta
            if abs(self._flip_accum) >= self.FLIP_THRESHOLD:
                direction = 1 if self._flip_accum < 0 else -1
                self._flip_accum = 0
                self.page_flip.emit(direction)
            event.accept()
        else:
            self._flip_accum = 0
            super().wheelEvent(event)

    def reset_flip(self):
        self._flip_accum = 0

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._verify_gpu)
        if self._d2d_requested:
            QTimer.singleShot(0, self.viewport().update)
        self._schedule_refine()
        self._schedule_vector_refine()

    def hideEvent(self, event):
        self.stop_rendering()
        self._release_d2d_surface()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "canvas"):
            self._viewport_moved()


# ReaderPageView remains as the compatibility name used by embedded consumers
# and existing tests. Standalone reader and editor workspaces share the class,
# but each process owns its own document, timers, cache and GPU context.
TiledPageView = ReaderPageView
