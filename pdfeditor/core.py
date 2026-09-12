"""PyMuPDF 래핑 — 문서 열기/저장/렌더/텍스트 추출.

Qt에 의존하지 않는다(설계 계획서 §4). GUI 없이 단독 테스트가 가능해야
하므로 이 모듈에서는 PyQt를 import 하지 말 것.
"""
from collections import OrderedDict
import os
import shutil
import tempfile
import sys
from dataclasses import fields, is_dataclass

import fitz

from .filetypes import is_illustrator_document
from .access import document_annotation, document_write


ANTIALIAS_LEVEL = 8
GPU_VECTOR_CACHE_BYTES = 128 * 1024 * 1024


def _aggressive_gpu_band_merge_enabled():
    return os.environ.get("SPDF_GPU_AGGRESSIVE_BAND_MERGE", "").lower() in \
        ("1", "true", "yes", "on")


def _gpu_scene_cost(scene):
    cached = getattr(scene, "_memory_cost", None)
    if cached is not None:
        return cached
    total, seen, pending = 0, set(), [scene]
    while pending:
        value = pending.pop()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        total += sys.getsizeof(value)
        if is_dataclass(value):
            total += sys.getsizeof(value.__dict__)
            pending.extend(getattr(value, field.name) for field in fields(value))
        elif isinstance(value, (tuple, list)):
            pending.extend(value)
    object.__setattr__(scene, "_memory_cost", total)
    return total


def configure_antialiasing(tools=None):
    """MuPDF 텍스트·그래픽 렌더링을 최고 품질 AA로 고정한다.

    PDF 페이지는 RGB 비트맵으로 Qt에 전달되므로 LCD 서브픽셀 순서에
    의존하는 ClearType 대신 모든 모니터에서 안전한 그레이스케일 AA를 쓴다.
    """
    tools = tools or fitz.TOOLS
    setter = getattr(tools, "set_aa_level", None)
    if setter is not None:
        setter(ANTIALIAS_LEVEL)


configure_antialiasing()


class PasswordRequired(Exception):
    """암호가 걸린 PDF — 호출부가 비밀번호를 받아 다시 시도해야 한다."""


class Document:
    """열린 PDF 한 건. 페이지 렌더와 텍스트 추출의 단일 창구."""

    def __init__(self, path, password=None, *, read_only=False,
                 annotations_enabled=None, isolated=False, snapshot=None):
        self._read_only = bool(read_only)
        self._annotations_enabled = (not read_only if annotations_enabled is None
                                     else bool(annotations_enabled))
        self._annotation_store = None
        self.annotation_error = None
        self.path = path
        # 같은 경로로 저장할 때 핸들을 닫았다가 다시 열어야 해서(save_as 참고)
        # 비밀번호를 들고 있어야 한다.
        self._password = password
        self._snapshot = snapshot
        if isolated and self._snapshot is None:
            from .document_snapshot import DocumentSnapshot
            self._snapshot = DocumentSnapshot(path)
        try:
            self._doc = self._open(self._snapshot.path if self._snapshot else path, password)
        except Exception:
            if self._snapshot:
                self._snapshot.close()
            raise
        self._source_revision = self._snapshot.revision if self._snapshot else None
        self._display_cache = {}
        self._gpu_vector_cache = OrderedDict()
        self._gpu_vector_cache_bytes = 0
        self._gpu_scene_probe_cache = {}
        self._render_generation = 0
        self._disk_cache_source = None
        try:
            source = self._snapshot.path if self._snapshot else path
            stat = os.stat(source)
            self._disk_cache_source = (source, (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except OSError:
            pass
        sidecar_exists = os.path.exists(os.path.realpath(path) + ".spdf-annotations.json")
        if self.read_only and (self.annotation_mode or sidecar_exists):
            try:
                if self.annotation_mode:
                    self.ensure_annotatable(require_store=False)
                if self.password_protected:
                    raise PermissionError("Protected PDFs cannot use unencrypted annotation sidecars.")
                from .annotation_store import AnnotationStore
                store = AnnotationStore(path)
                annotated = store.rebuild(lambda: self._open(
                    self._snapshot.path if self._snapshot else path, password))
                self._doc.close()
                self._doc = annotated
                self._annotation_store = store
            except Exception as error:
                # A corrupt/mismatched sidecar must not stop PDF viewing or be
                # silently replaced by an empty annotation history.
                self.annotation_error = str(error)

    @classmethod
    def from_snapshot(cls, path, data, *, read_only=False):
        """다른 프로세스에서 받은 현재 편집 상태를 원래 경로의 문서로 연다."""
        document = cls.__new__(cls)
        document._read_only = bool(read_only)
        document._annotations_enabled = not read_only
        document._annotation_store = None
        document.annotation_error = None
        document.path = path
        document._password = None
        document._doc = fitz.open("pdf", data)
        document._display_cache = {}
        document._gpu_vector_cache = OrderedDict()
        document._gpu_vector_cache_bytes = 0
        document._gpu_scene_probe_cache = {}
        document._render_generation = 0
        return document

    @staticmethod
    def _open(path, password):
        # PDF-compatible Illustrator files contain a PDF representation, but
        # their .ai extension is not consistently auto-detected by MuPDF.
        doc = fitz.open(path, filetype="pdf") \
            if is_illustrator_document(path) else fitz.open(path)
        if doc.needs_pass:
            if password is None or not doc.authenticate(password):
                doc.close()
                raise PasswordRequired(path)
        return doc

    # --- 수명 주기 ---------------------------------------------------

    def close(self):
        if self._doc is not None:
            self._display_cache.clear()
            self._gpu_vector_cache.clear()
            self._gpu_vector_cache_bytes = 0
            self._gpu_scene_probe_cache.clear()
            self._doc.close()
            self._doc = None
        if getattr(self, "_snapshot", None) is not None:
            self._snapshot.close()
            self._snapshot = None

    @property
    def page_count(self):
        return self._doc.page_count

    @property
    def password_protected(self):
        """Whether this document required a password when it was opened."""
        if self._password or self._doc.metadata.get("encryption"):
            return True
        try:
            probe = fitz.open(self.path, filetype="pdf") \
                if is_illustrator_document(self.path) else fitz.open(self.path)
            try:
                return bool(probe.needs_pass or probe.metadata.get("encryption"))
            finally:
                probe.close()
        except Exception:
            return False

    # --- 렌더 -------------------------------------------------------

    def render(self, index, zoom=1.0):
        """페이지를 RGB888 픽셀로 렌더. (width, height, stride, bytes) 반환.

        Qt 타입(QImage)을 여기서 만들지 않는 건 이 모듈을 Qt 비의존으로
        유지하기 위해서다 — 조립은 widgets.py가 한다.
        """
        display = self._display_list(index)
        pix = display.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return pix.width, pix.height, pix.stride, pix.samples

    def _display_list(self, index):
        display = self._display_cache.get(index)
        if display is None:
            display = self._doc[index].get_displaylist()
            if len(self._display_cache) >= 5:
                self._display_cache.pop(next(iter(self._display_cache)))
            self._display_cache[index] = display
        return display

    def render_region(self, index, zoom, rect):
        """Rasterize a bounded PDF-coordinate clip; include pixel origin.

        Returning MuPDF's rounded pixel origin avoids seams at fractional zoom
        and keeps rotated/cropped pages aligned with their low-resolution image.
        """
        import math
        if not math.isfinite(zoom) or zoom <= 0:
            raise ValueError("Invalid render scale")
        clip = fitz.Rect(rect)
        if not all(math.isfinite(value) for value in clip):
            raise ValueError("Invalid render region")
        clip &= self._doc[index].rect
        if clip.is_empty or clip.is_infinite:
            raise ValueError("Empty render region")
        if (math.ceil(clip.width * zoom) + 2) * (math.ceil(clip.height * zoom) + 2) > 4_000_000:
            raise ValueError("Render region exceeds the tile pixel budget")
        pix = self._display_list(index).get_pixmap(
            matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        return pix.x, pix.y, pix.width, pix.height, pix.stride, pix.samples

    def invalidate_render(self, index=None):
        self._render_generation += 1
        if index is None:
            self._display_cache.clear()
            self._gpu_vector_cache.clear()
            self._gpu_vector_cache_bytes = 0
            self._gpu_scene_probe_cache.clear()
        else:
            self._display_cache.pop(index, None)
            self._gpu_scene_probe_cache.pop(index, None)
            for key in tuple(self._gpu_vector_cache):
                if key[0] == index:
                    scene = self._gpu_vector_cache.pop(key, None)
                    if scene is not None:
                        self._gpu_vector_cache_bytes -= _gpu_scene_cost(scene)

    def gpu_vector_page(self, index, raster_scale=1.0, timeout_seconds=None):
        """Return a conservative Direct2D scene or an unsupported result."""
        scale = max(1.0, float(raster_scale))
        aggressive_band_merge = _aggressive_gpu_band_merge_enabled()
        key = (index, scale, aggressive_band_merge)
        scene = self._gpu_vector_cache.get(key)
        if scene is None:
            for cached_key, candidate in reversed(self._gpu_vector_cache.items()):
                if cached_key[0] != index or \
                        cached_key[2] != aggressive_band_merge or \
                        not candidate.supported:
                    continue
                if candidate.raster_scale >= scale or \
                        "image-downsample" not in candidate.features:
                    self._gpu_vector_cache.move_to_end(cached_key)
                    return candidate
        if scene is None:
            scene = self._load_disk_gpu_scene(index, scale)
        if scene is None:
            from .gpu_raster import vector_page_from_pymupdf, refine_page_images
            base = next((value for cache_key, value in reversed(self._gpu_vector_cache.items())
                         if cache_key[0] == index and cache_key[2] == aggressive_band_merge
                         and value.supported and value.raster_scale < scale), None)
            if base is not None:
                import time
                started = time.monotonic()
                scene = refine_page_images(self._doc[index], base, scale, timeout_seconds)
                if timeout_seconds is not None:
                    timeout_seconds = max(0.0, timeout_seconds - (time.monotonic() - started))
            if scene is None:
                scene = vector_page_from_pymupdf(
                    self._doc[index], scale, timeout_seconds=timeout_seconds,
                    aggressive_band_merge=aggressive_band_merge)
            self._save_disk_gpu_scene(index, scene)
            cost = _gpu_scene_cost(scene)
            self._gpu_vector_cache[key] = scene
            self._gpu_vector_cache_bytes += cost
            while (self._gpu_vector_cache_bytes > GPU_VECTOR_CACHE_BYTES and
                   len(self._gpu_vector_cache) > 1):
                _old_key, old_scene = self._gpu_vector_cache.popitem(last=False)
                self._gpu_vector_cache_bytes -= _gpu_scene_cost(old_scene)
        else:
            self._gpu_vector_cache.move_to_end(key)
        return scene

    def cached_gpu_vector_page(self, index, raster_scale=1.0, *, memory_only=False):
        """Return a reusable supported scene without starting extraction."""
        scale = max(1.0, float(raster_scale))
        aggressive_band_merge = _aggressive_gpu_band_merge_enabled()
        for cached_key, candidate in reversed(self._gpu_vector_cache.items()):
            if cached_key[0] != index or \
                    cached_key[2] != aggressive_band_merge or \
                    not candidate.supported:
                continue
            if candidate.raster_scale >= scale or \
                    "image-downsample" not in candidate.features:
                self._gpu_vector_cache.move_to_end(cached_key)
                return candidate
        return None if memory_only else self._load_disk_gpu_scene(index, scale)

    def gpu_scene_disk_cache_key(self, index, raster_scale=1.0):
        from . import scene_disk_cache as disk
        return disk.key(self, index, max(1.0, float(raster_scale)),
                        _aggressive_gpu_band_merge_enabled())

    def _load_disk_gpu_scene(self, index, scale):
        from . import scene_disk_cache as disk
        cache_key = disk.key(self, index, scale, _aggressive_gpu_band_merge_enabled())
        misses = getattr(self, "_disk_cache_misses", None)
        if misses is None:
            misses = self._disk_cache_misses = set()
        if cache_key is None or cache_key in misses:
            return None
        scene = disk.load(cache_key, self._doc[index])
        if scene is None or scene.raster_scale != scale:
            misses.add(cache_key)
            return None
        return self.install_gpu_vector_page(index, scene, persist=False)

    def _save_disk_gpu_scene(self, index, scene):
        from . import scene_disk_cache as disk
        disk.save(disk.key(self, index, scene.raster_scale,
                           _aggressive_gpu_band_merge_enabled()), scene)

    @property
    def render_generation(self):
        return self._render_generation

    def gpu_scene_complexity(self, index):
        result = self._gpu_scene_probe_cache.get(index)
        if result is None:
            from .gpu_raster import probe_gpu_scene_complexity
            result = probe_gpu_scene_complexity(self._doc[index])
            self._gpu_scene_probe_cache[index] = result
        return result

    def gpu_page_snapshot(self, index):
        """Return one current page as an isolated worker-safe PDF snapshot."""
        snapshot = fitz.open()
        try:
            snapshot.insert_pdf(self._doc, from_page=index, to_page=index)
            return snapshot.tobytes(garbage=0, deflate=True)
        finally:
            snapshot.close()

    def install_gpu_vector_page(self, index, scene, *, persist=True):
        """Install a scene produced from the current page snapshot."""
        aggressive_band_merge = _aggressive_gpu_band_merge_enabled()
        key = (index, float(scene.raster_scale), aggressive_band_merge)
        previous = self._gpu_vector_cache.pop(key, None)
        if previous is not None:
            self._gpu_vector_cache_bytes -= _gpu_scene_cost(previous)
        self._gpu_vector_cache[key] = scene
        self._gpu_vector_cache_bytes += _gpu_scene_cost(scene)
        while (self._gpu_vector_cache_bytes > GPU_VECTOR_CACHE_BYTES and
               len(self._gpu_vector_cache) > 1):
            _old_key, old_scene = self._gpu_vector_cache.popitem(last=False)
            self._gpu_vector_cache_bytes -= _gpu_scene_cost(old_scene)
        if persist:
            self._save_disk_gpu_scene(index, scene)
        return scene

    def page_size(self, index):
        r = self._doc[index].rect
        return r.width, r.height

    def bookmarks(self):
        """Return PDF outline entries as ``(level, title, one-based page)``."""
        try:
            return [tuple(entry[:3])
                    for entry in self._doc.get_toc(simple=True)]
        except Exception:
            # A damaged outline must not prevent an otherwise valid PDF from
            # opening and being edited.
            return []

    def link_at(self, index, x, y):
        """Return a normalized link dictionary at a PDF page coordinate."""
        point = fitz.Point(float(x), float(y))
        kinds = {
            fitz.LINK_GOTO: "goto",
            fitz.LINK_URI: "uri",
            fitz.LINK_GOTOR: "gotor",
            fitz.LINK_LAUNCH: "launch",
        }
        for link in self._doc[index].get_links():
            if point not in fitz.Rect(link.get("from")):
                continue
            target = link.get("to")
            return {
                "kind": kinds.get(link.get("kind"), "unsupported"),
                "page": int(link.get("page", -1)),
                "to": (float(target.x), float(target.y))
                if hasattr(target, "x") else None,
                "uri": str(link.get("uri") or ""),
                "file": str(link.get("file") or ""),
            }
        return None

    @property
    def read_only(self):
        return self._read_only

    @property
    def annotation_mode(self):
        return self.read_only and self._annotations_enabled

    @property
    def annotations_enabled(self):
        return (self._annotations_enabled and not self.annotation_error and
                bool(self._doc.permissions & fitz.PDF_PERM_ANNOTATE))

    def ensure_annotatable(self, require_store=True):
        if not self.annotations_enabled:
            raise PermissionError(self.annotation_error or "Annotation editing is disabled.")
        if require_store and self.annotation_mode and self._annotation_store is None:
            raise PermissionError("The annotation store is unavailable.")

    @property
    def annotations_dirty(self):
        return bool(self._annotation_store and self._annotation_store.dirty)

    @property
    def can_undo_annotation(self):
        return bool(self._annotation_store and self._annotation_store.cursor > 0)

    @property
    def can_redo_annotation(self):
        store = self._annotation_store
        return bool(store and store.cursor < len(store.operations))

    def step_annotation_history(self, forward=False):
        self.ensure_annotatable()
        store = self._annotation_store
        if store is None or not (self.can_redo_annotation if forward else self.can_undo_annotation):
            return False
        restored = store.rebuild(lambda: self._open(self.path, self._password),
                                 store.cursor + (1 if forward else -1))
        self._doc.close()
        self._doc = restored
        self.invalidate_render()
        return True

    def save_annotations(self):
        self.ensure_annotatable()
        if self._annotation_store is None:
            raise ValueError("Separate annotation saving requires a read-only annotation window.")
        self._annotation_store.save()

    def export_annotated_pdf(self, out_path):
        """Export a separate PDF without switching the source or sidecar."""
        self.ensure_annotatable()
        out_path = os.path.abspath(os.fspath(out_path))
        same_path = os.path.normcase(os.path.realpath(out_path)) == os.path.normcase(
            os.path.realpath(self.path))
        if same_path or (os.path.exists(out_path) and os.path.samefile(out_path, self.path)):
            raise ValueError("Choose a different file; the original PDF must be preserved.")
        if self._annotation_store:
            sidecar = str(self._annotation_store.path)
            if (os.path.normcase(os.path.realpath(out_path)) == os.path.normcase(sidecar) or
                    (os.path.exists(out_path) and os.path.exists(sidecar) and
                     os.path.samefile(out_path, sidecar))):
                raise ValueError("Cannot replace the annotation sidecar with a PDF.")
        fd, temporary = tempfile.mkstemp(prefix=".spdf-export-", suffix=".pdf",
                                          dir=os.path.dirname(out_path))
        os.close(fd)
        try:
            self._doc.save(temporary, garbage=3, deflate=True,
                           encryption=fitz.PDF_ENCRYPT_KEEP)
            os.replace(temporary, out_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def ensure_editable(self):
        if self.read_only:
            raise PermissionError("This document is open in read-only mode.")
        if not self._doc.permissions & fitz.PDF_PERM_MODIFY:
            raise PermissionError("This PDF does not permit document changes.")

    @document_write
    def add_bookmark(self, title, page):
        self.ensure_editable()
        if not title.strip() or not 0 <= page < self.page_count:
            raise ValueError("Invalid bookmark.")
        toc = self._doc.get_toc(False)
        toc.append([1, title.strip(), page + 1])
        self._doc.set_toc(toc)

    @document_write
    def rename_bookmark(self, index, title):
        self.ensure_editable()
        toc = self._doc.get_toc(False)
        if not 0 <= index < len(toc):
            raise ValueError("Invalid bookmark.")
        if not title.strip():
            raise ValueError("A bookmark needs a title.")
        self._doc.set_toc_item(index, title=title.strip())

    @document_write
    def delete_bookmark(self, index):
        self.ensure_editable()
        toc = self._doc.get_toc(False)
        if not 0 <= index < len(toc):
            raise ValueError("Invalid bookmark.")
        level = toc[index][0]
        end = index + 1
        while end < len(toc) and toc[end][0] > level:
            end += 1
        del toc[index:end]
        self._doc.set_toc(toc)

    @document_write
    def reorder_bookmarks(self, order):
        self.ensure_editable()
        toc = self._doc.get_toc(False)
        if sorted(index for level, index in order) != list(range(len(toc))):
            raise ValueError("Invalid bookmark order.")
        result = []
        previous = 0
        for level, index in order:
            if not 1 <= level <= previous + 1:
                raise ValueError("Invalid bookmark hierarchy.")
            result.append([level] + toc[index][1:])
            previous = level
        self._doc.set_toc(result)

    @document_write
    def replace_bookmarks(self, entries):
        self.ensure_editable()
        toc = []
        previous = 0
        for level, title, page in entries:
            level, page = int(level), int(page)
            if (not str(title).strip() or not 1 <= page <= self.page_count or
                    not 1 <= level <= previous + 1):
                raise ValueError("Invalid bookmark outline.")
            toc.append([level, str(title).strip(), page])
            previous = level
        if not toc:
            raise ValueError("The bookmark outline is empty.")
        self._doc.set_toc(toc)

    @document_write
    def crop_pages(self, indices, fractions):
        """Crop visible margins by relative DISPLAY coordinates, not redaction."""
        self.ensure_editable()
        x0, y0, x1, y1 = map(float, fractions)
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("Invalid crop rectangle.")
        indices = sorted(set(indices))
        if not indices or indices[0] < 0 or indices[-1] >= self.page_count:
            raise ValueError("Invalid page selection.")
        crops = []
        for index in indices:
            page = self._doc[index]
            w, h = page.rect.width, page.rect.height
            selected = fitz.Rect(x0 * w, y0 * h, x1 * w, y1 * h)
            rect = selected * page.derotation_matrix
            origin = page.cropbox_position
            rect = fitz.Rect(rect.x0 + origin.x, rect.y0 + origin.y,
                             rect.x1 + origin.x, rect.y1 + origin.y)
            if rect.width < 1 or rect.height < 1:
                raise ValueError("The crop area is too small.")
            crops.append((index, rect))
        for index, rect in crops:
            self._doc[index].set_cropbox(rect)
        self.invalidate_render()

    @document_write
    def set_page_canvas_size(self, index, width, height):
        """Set the current page canvas size in PDF points."""
        self.ensure_editable()
        index = int(index)
        width = float(width)
        height = float(height)
        if not 0 <= index < self.page_count or width < 1 or height < 1:
            raise ValueError("Invalid canvas size.")
        if width > 20000 or height > 20000:
            raise ValueError("The canvas size is too large.")
        page = self._doc[index]
        rect = fitz.Rect(0, 0, width, height)
        page.set_mediabox(rect)
        page.set_cropbox(rect)
        page.set_trimbox(rect)
        page.set_bleedbox(rect)
        self.invalidate_render(index)

    @document_write
    def set_page_bleed(self, index, left, top, right, bottom):
        """Set TrimBox/BleedBox around the visible page without scaling art."""
        self.ensure_editable()
        index = int(index)
        margins = tuple(float(value) for value in (left, top, right, bottom))
        if not 0 <= index < self.page_count or any(value < 0 for value in margins):
            raise ValueError("Invalid bleed margins.")
        if any(value > 720 for value in margins):
            raise ValueError("Bleed margins are too large.")
        page = self._doc[index]
        width, height = page.rect.width, page.rect.height
        if width < 1 or height < 1:
            raise ValueError("Invalid page size.")
        left, top, right, bottom = margins
        self._translate_page_contents(index, left, bottom)
        media = fitz.Rect(0, 0, width + left + right, height + top + bottom)
        trim = fitz.Rect(left, top, left + width, top + height)
        page = self._doc[index]
        page.set_mediabox(media)
        page.set_cropbox(trim)
        page.set_trimbox(trim)
        page.set_bleedbox(media)
        self.invalidate_render(index)

    def page_bleed_margins(self, index):
        page = self._doc[int(index)]
        trim = page.trimbox
        bleed = page.bleedbox
        return (
            max(0.0, trim.x0 - bleed.x0),
            max(0.0, trim.y0 - bleed.y0),
            max(0.0, bleed.x1 - trim.x1),
            max(0.0, bleed.y1 - trim.y1),
        )

    def _translate_page_contents(self, index, dx, dy):
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return
        page = self._doc[int(index)]
        prefix = ("q 1 0 0 1 %.6f %.6f cm\n" % (dx, dy)).encode("ascii")
        for xref in page.get_contents():
            stream = self._doc.xref_stream(xref)
            self._doc.update_stream(xref, prefix + stream + b"\nQ")

    @document_write
    def add_watermark(self, indices, text, fontsize=42, opacity=0.2,
                      angle=-35):
        """Place a centered text watermark over selected pages."""
        self.ensure_editable()
        text = str(text).strip()
        indices = sorted(set(int(index) for index in indices))
        fontsize, opacity, angle = float(fontsize), float(opacity), float(angle)
        if not text or not indices or indices[0] < 0 or \
                indices[-1] >= self.page_count:
            raise ValueError("Invalid watermark selection.")
        if not 4 <= fontsize <= 240 or not 0.01 <= opacity <= 1:
            raise ValueError("Invalid watermark appearance.")
        fontname = "helv" if text.isascii() else "korea"
        for index in indices:
            page = self._doc[index]
            center = fitz.Point(
                page.rect.x0 + page.rect.width / 2,
                page.rect.y0 + page.rect.height / 2)
            width = self._render_width(text, fontsize, fontname)
            origin = fitz.Point(center.x - width / 2,
                                center.y + fontsize * 0.35)
            page.insert_text(
                origin, text, fontsize=fontsize, fontname=fontname,
                color=(0.45, 0.45, 0.45), fill_opacity=opacity,
                overlay=True, morph=(center, fitz.Matrix(angle)))
            self.invalidate_render(index)

    def page_image_bytes(self, index, image_format="png", dpi=150):
        image_format = str(image_format).lower()
        if image_format not in ("png", "jpeg"):
            raise ValueError("Unsupported image format.")
        dpi = int(dpi)
        if not 72 <= dpi <= 600 or not 0 <= index < self.page_count:
            raise ValueError("Invalid image export options.")
        pixmap = self._doc[index].get_pixmap(
            matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        return pixmap.tobytes("jpg" if image_format == "jpeg" else "png")

    # --- 텍스트 -----------------------------------------------------

    def words(self, index):
        """단어별 (x0, y0, x1, y1, text, block, line, word_no) 목록 —
        PDF 좌표계(zoom=1 기준).

        선택/복사(§3.2)가 이 좌표를 쓴다. 화면 좌표 변환은 보는 쪽이
        zoom을 곱해서 처리. block/line 번호는 복사할 때 줄바꿈을 복원하는
        용도.
        """
        return list(self._doc[index].get_text("words"))

    def search(self, index, needle):
        """페이지 안에서 문자열 검색 — 일치 영역 (x0,y0,x1,y1) 목록."""
        return [(r.x0, r.y0, r.x1, r.y1)
                for r in self._doc[index].search_for(needle)]

    def has_text(self, index):
        """텍스트 레이어 유무 — 스캔본이면 False(→ OCR 필요)."""
        return bool(self._doc[index].get_text("text").strip())

    def spans(self, index):
        """편집 단위(span = 같은 글꼴/크기로 이어진 한 토막) 목록.

        편집은 이 단위로 한다 — PDF는 글자를 좌표에 찍어놓은 포맷이라
        '문단'이라는 개념이 없기 때문(설계 §3.4).
        """
        out = []
        for block in self._doc[index].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    if not sp["text"].strip():
                        continue
                    c = sp["color"]
                    out.append({
                        "bbox": tuple(sp["bbox"]),
                        "origin": tuple(sp["origin"]),  # 글자 baseline 시작점
                        "text": sp["text"],
                        "size": sp["size"],
                        "flags": sp["flags"],
                        "font": sp["font"],
                        # PyMuPDF는 색을 int로 준다 → RGB 0~1 튜플로
                        "rgb": (((c >> 16) & 255) / 255.0,
                                ((c >> 8) & 255) / 255.0,
                                (c & 255) / 255.0),
                    })
        return out

    # --- 주석 (형광펜/메모) -------------------------------------------

    # 주의: 아래 메서드들은 page 객체를 지역변수로 반드시 붙들어야 한다.
    # self._doc[index].add_...() 처럼 임시로 쓰면 그 줄이 끝날 때 page가
    # GC되면서 annot이 "not bound to any page"로 죽는다(PyMuPDF 특성).

    @document_annotation
    def add_highlight(self, index, rects):
        """형광펜 — rects는 (x0,y0,x1,y1) 목록(줄 단위 권장)."""
        page = self._doc[index]
        annot = page.add_highlight_annot([fitz.Rect(*r) for r in rects])
        annot.update()
        return annot.xref

    @document_annotation
    def add_note(self, index, x, y, text):
        """스티키 노트 — 아이콘이 (x, y)에 붙는다."""
        page = self._doc[index]
        annot = page.add_text_annot(fitz.Point(x, y), text)
        annot.update()
        return annot.xref

    def annots(self, index):
        """페이지의 주석 목록 — 우클릭 히트테스트/편집용."""
        page = self._doc[index]
        out = []
        for a in page.annots():
            r = a.rect
            out.append({"xref": a.xref, "kind": a.type[1],
                        "rect": (r.x0, r.y0, r.x1, r.y1),
                        "text": a.info.get("content", "")})
        return out

    @document_annotation
    def set_note_text(self, index, xref, text):
        page = self._doc[index]
        for a in page.annots():
            if a.xref == xref:
                a.set_info(content=text)
                a.update()
                return

    @document_annotation
    def delete_annot(self, index, xref):
        page = self._doc[index]
        for a in page.annots():
            if a.xref == xref:
                page.delete_annot(a)
                return

    # --- OCR --------------------------------------------------------

    @document_write
    def insert_ocr_text(self, index, items):
        """OCR 결과를 보이지 않는 텍스트 레이어로 삽입(설계 §3.3).

        items: (x0, y0, x1, y1, text) 목록, PDF 좌표계.
        render_mode=3이 '그리지 않는 텍스트' — 화면 외관은 그대로 두고
        검색/선택만 가능하게 만든다.

        폰트: 영문만인 줄은 비례폭 Helvetica("helv")로 쓴다 — 내장 CJK
        폰트("korea")는 라틴 글자를 전각(약 2배 폭)으로 그려 이미지 글자와
        폭이 크게 어긋난다. 한글이 섞인 줄만 CJK("korea")를 쓴다.

        가로 맞춤(중요): VL은 '줄 단위' 박스를 주는데 대체폰트의 글자 폭이
        원본 이미지와 달라, 그냥 쓰면 줄 오른쪽으로 갈수록 보이지 않는
        글자가 실제 글자에서 벗어나 검색/선택 하이라이트가 어긋난다(줄 끝
        단어가 여백 밖으로까지 밀리기도 한다). 그래서 x0(줄 시작)을
        고정점으로 글자열을 가로로만 스케일해 박스 폭에 맞춘다. 스케일 계수는
        폰트 메트릭 예측이 아니라 '실제 렌더 폭'을 재서 구한다 — 폰트에 따라
        예측이 크게 빗나가기 때문(예: korea 폰트의 전각 라틴).
        """
        page = self._doc[index]
        n = 0
        for x0, y0, x1, y1, text in items:
            if not text.strip():
                continue
            h = y1 - y0
            box_w = x1 - x0
            fontsize = max(4.0, h * 0.85)
            # 베이스라인은 박스 바닥에서 살짝 위 — 선택 영역이 원문과
            # 대충 겹치기만 하면 된다(어차피 안 보이는 글자).
            baseline = y1 - h * 0.18
            fontname = "helv" if text.isascii() else "korea"
            morph = None
            actual_w = self._render_width(text, fontsize, fontname)
            if actual_w > 1 and box_w > 1:
                # [0.5,2.5]로 제한 — 오검출로 박스가 비정상일 때만 걸린다.
                scale = max(0.5, min(2.5, box_w / actual_w))
                morph = (fitz.Point(x0, baseline),
                         fitz.Matrix(scale, 0, 0, 1, 0, 0))
            page.insert_text((x0, baseline), text, fontsize=fontsize,
                             fontname=fontname, render_mode=3, morph=morph)
            n += 1
        return n

    # 실제 렌더 폭을 재는 스크래치 문서(insert_ocr_text 전용) — 폰트 메트릭
    # 예측이 빗나가는 폰트(전각 라틴 등)에도 정확한 스케일을 얻기 위함.
    _MEASURE_DOC = None

    @classmethod
    def _render_width(cls, text, fontsize, fontname):
        """text를 fontname/fontsize로 실제로 써 봤을 때의 가로 폭(pt)."""
        if cls._MEASURE_DOC is None:
            cls._MEASURE_DOC = fitz.open()
        doc = cls._MEASURE_DOC
        page = doc.new_page(width=20000, height=100)
        try:
            page.insert_text((0, 50), text, fontsize=fontsize,
                             fontname=fontname, render_mode=3)
            words = page.get_text("words")
            if not words:
                return 0.0
            return max(w[2] for w in words) - min(w[0] for w in words)
        finally:
            doc.delete_page(len(doc) - 1)

    # --- 텍스트 편집 (설계 §3.4) --------------------------------------

    @document_write
    def replace_span(self, index, bbox, origin, new_text, size, rgb, *, fit=True,
                     fontname="korea", fontfile=None):
        """한 span의 글자를 지우고(redaction) 같은 baseline에 다시 쓴다.

        한계(설계 §3.4): 원본 폰트를 그대로 못 쓰는 경우가 많아 CJK 내장
        폰트("korea")로 다시 쓴다 → 한글+영문은 커버되지만 글자 모양이
        미묘하게 달라질 수 있다. 리플로우는 없다 — 길어져도 그 자리에서만
        교체(넘치면 폭에 맞춰 자간이 아니라 폰트 크기를 줄인다).

        fill=None: 배경을 칠하지 않고 글자만 지운다. 흰 배경이면 티가 안
        나고, 배경색이 있으면 그 자리가 지워질 수 있다(§3.4 한계).
        """
        fontname, font = self._edit_font(fontname, fontfile)
        self._validate_edit_glyphs(font, new_text)
        page = self._doc[index]
        rect = fitz.Rect(*bbox)
        page.add_redact_annot(rect, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        page = self._doc[index]  # apply_redactions 후 페이지 재취득
        fontsize = self._fit_fontsize(new_text, size, rect.width, font=font) if fit else size
        page.insert_text((origin[0], origin[1]), new_text,
                         fontsize=fontsize, fontname=fontname, fontfile=fontfile, color=rgb)

    @staticmethod
    def _edit_font(fontname, fontfile):
        if fontfile:
            import hashlib
            font = fitz.Font(fontfile=fontfile)
            return "spdf" + hashlib.sha256(font.buffer).hexdigest()[:16], font
        return fontname, fitz.Font("cjk" if fontname == "korea" else fontname)

    @staticmethod
    def _validate_edit_glyphs(font, text):
        if any(not char.isspace() and not font.has_glyph(ord(char)) for char in text):
            raise ValueError("선택한 글꼴에 없는 글자가 있습니다. / The selected font lacks some characters.")

    def _fit_fontsize(self, text, size, max_width, *, font=None):
        """새 글자가 원래 폭을 넘으면 폰트 크기를 줄여 한 줄에 맞춘다.
        리플로우가 없으므로(그 줄 안에서만 교체) 최소한의 안전장치."""
        if max_width <= 0:
            return size
        font = font or fitz.Font("cjk")
        width = font.text_length(text, fontsize=size)
        if width <= max_width:
            return size
        return max(4.0, size * max_width / width)

    # --- 스캔본 편집 (설계 §3.4) ----------------------------------------

    def is_scanned_area(self, index, bbox):
        """그 자리에 이미지가 깔려 있나 — 스캔본이면 글자가 이미지 픽셀이라
        리댁션만으로는 안 지워지고 배경색으로 덮어칠해야 한다."""
        page = self._doc[index]
        r = fitz.Rect(bbox)
        for img in page.get_images():
            for ir in page.get_image_rects(img[0]):
                if ir.intersects(r):
                    return True
        return False

    def sample_bg_fg(self, index, bbox, pad=4):
        """bbox 주변에서 배경색(종이)과 전경색(글자)을 추출 → (bg, fg) RGB 0~1.

        작은 영역만 렌더하므로 큰 페이지에서도 부담이 없다. numpy가 없으면
        흰 배경/검은 글자로 가정.
        """
        page = self._doc[index]
        r = fitz.Rect(bbox)
        outer = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)
        outer = outer & page.rect
        if outer.is_empty:
            return (1, 1, 1), (0, 0, 0)
        pix = page.get_pixmap(clip=outer, matrix=fitz.Matrix(2, 2), alpha=False)
        try:
            import numpy as np
        except ImportError:
            return (1, 1, 1), (0, 0, 0)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, 3)
        lum = arr.mean(axis=2)
        # 밝기 중간값으로 종이/글자를 가른다. 고정 퍼센타일로 나누면 배경이
        # 대부분인 영역에서 '어두운 15%'가 글자 획이 아니라 안티앨리어싱
        # 가장자리라 글자색이 흐릿한 회색으로 잡혔다.
        lo, hi = float(lum.min()), float(lum.max())
        thresh = (lo + hi) / 2.0
        bright = arr[lum >= thresh]
        dark = arr[lum < thresh]
        bg = tuple(np.median(bright, axis=0) / 255.0) if len(bright) else (1, 1, 1)
        if len(dark):
            fg = tuple(np.median(dark, axis=0) / 255.0)
        else:
            fg = (0, 0, 0)
        # 대비가 거의 없는 영역(글자가 없거나 흐린 스캔)에서 뽑힌 연한 색으로
        # 쓰면 읽을 수 없다 — 그럴 땐 검정으로.
        if sum(fg) / 3.0 > 0.55:
            fg = (0, 0, 0)
        return bg, fg

    @document_write
    def replace_scanned_text(self, index, bbox, origin, new_text, size,
                             bg=None, fg=None, *, fontname="korea", fontfile=None):
        """스캔본 글자 교체 — 배경색으로 덮고 그 자리에 새 글자를 쓴다.

        기존 OCR 텍스트 레이어(보이지 않는 글자)도 함께 지운다 — 안 그러면
        검색이 옛 글자를 계속 찾아낸다.
        """
        fontname, font = self._edit_font(fontname, fontfile)
        self._validate_edit_glyphs(font, new_text)
        if bg is None or fg is None:
            sbg, sfg = self.sample_bg_fg(index, bbox)
            bg = bg or sbg
            fg = fg or sfg
        page = self._doc[index]
        rect = fitz.Rect(bbox)
        # 1) 그 자리의 텍스트(OCR 레이어)만 제거 — 이미지는 보존
        page.add_redact_annot(rect, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        page = self._doc[index]
        # 2) 이미지에 찍혀 있는 원래 글자를 배경색으로 덮기
        #    가장자리 1px 여유 — 글자 획이 bbox를 살짝 삐져나오는 경우가 있다
        page.draw_rect(fitz.Rect(rect.x0 - 1, rect.y0 - 1,
                                 rect.x1 + 1, rect.y1 + 1),
                       color=None, fill=bg, width=0)
        # 3) 새 글자 쓰기
        if new_text.strip():
            page.insert_text(origin, new_text, fontsize=size,
                             fontname=fontname, fontfile=fontfile, color=fg)

    @document_write
    def add_text_box(self, index, point, text, size=11, bg=None, fg=(0, 0, 0), *,
                     fontname="korea", fontfile=None):
        """임의 위치에 텍스트 박스 — OCR 없이도 스캔본에 글자를 얹는 자유 편집.

        bg가 있으면 글자 뒤에 배경 사각형을 깔아 밑에 있는 내용을 가린다.
        """
        fontname, font = self._edit_font(fontname, fontfile)
        self._validate_edit_glyphs(font, text)
        page = self._doc[index]
        if bg is not None:
            w = font.text_length(text, fontsize=size)
            rect = fitz.Rect(point[0] - 1, point[1] - size,
                             point[0] + w + 2, point[1] + size * 0.3)
            page.draw_rect(rect, color=None, fill=bg, width=0)
        page.insert_text(point, text, fontsize=size, fontname=fontname,
                         fontfile=fontfile, color=fg)

    # --- 페이지 조작 ---------------------------------------------------

    @document_write
    def rotate_page(self, index, degrees):
        """페이지 회전 — 기존 각도에 상대적으로 더한다(0/90/180/270로 정규화)."""
        page = self._doc[index]
        page.set_rotation((page.rotation + degrees) % 360)

    @document_write
    def delete_page(self, index):
        self._doc.delete_page(index)

    @document_write
    def move_page(self, src, dst):
        """src 페이지를 dst 위치로 이동."""
        if src == dst:
            return
        # PyMuPDF의 move_page(to=)는 '그 위치 앞에 끼운다' 의미라, 뒤로
        # 옮길 때 한 칸 밀린다 — 사용자가 기대하는 최종 인덱스로 맞춘다.
        self._doc.move_page(src, dst + 1 if dst > src else dst)

    @document_write
    def reorder_pages(self, order):
        """현재 페이지를 ``order`` 순서로 재배열한다."""
        order = list(order)
        if sorted(order) != list(range(self.page_count)):
            raise ValueError("페이지 순서는 모든 페이지를 정확히 한 번 포함해야 합니다.")
        self._doc.select(order)

    @document_write
    def delete_pages(self, indices):
        """여러 페이지를 원래 인덱스 기준으로 한 번에 삭제한다."""
        indices = sorted(set(indices), reverse=True)
        if self.page_count - len(indices) < 1:
            raise ValueError("문서에는 최소 한 페이지가 남아 있어야 합니다.")
        for index in indices:
            self._doc.delete_page(index)

    @document_write
    def insert_pdf(self, path, at=None, password=None):
        """다른 PDF를 통째로 끼워넣는다(병합). at=None이면 맨 뒤.

        반환: 삽입된 페이지 수.
        """
        other = self._open(path, password)
        try:
            n = other.page_count
            self._doc.insert_pdf(other, start_at=at)
            return n
        finally:
            other.close()

    @document_write
    def extract_pages(self, indices, out_path):
        """선택한 페이지만 새 PDF로 저장(분할). 원본은 그대로 둔다."""
        if not indices:
            raise ValueError("추출할 페이지가 없습니다.")
        new = fitz.open()
        out_dir = os.path.dirname(os.path.abspath(out_path))
        prefix = ".%s." % os.path.basename(out_path)
        fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=out_dir)
        os.close(fd)
        os.unlink(tmp)  # PyMuPDF는 존재하지 않는 새 경로에 저장해야 한다.
        try:
            for i in indices:
                new.insert_pdf(self._doc, from_page=i, to_page=i)
            new.save(tmp, garbage=3, deflate=True)
            os.replace(tmp, out_path)
        finally:
            new.close()
            if os.path.exists(tmp):
                os.remove(tmp)

    def snapshot(self):
        """현재 문서 전체를 바이트로 — 되돌리기 스택용(설계: 저널링 대신).

        PyMuPDF 1.28의 내장 저널링은 텍스트 삽입과 함께 쓰면 깨져서
        (연산 중 폰트 등록 불가) 스냅샷 방식을 쓴다. 텍스트 편집은 보통
        용량이 크지 않은 문서에서 일어나므로 감당 가능.
        """
        return self._doc.tobytes(garbage=0, deflate=True)

    @document_write
    def restore(self, data):
        """스냅샷으로 되돌린다 — 내부 문서를 통째로 교체."""
        self._doc.close()
        self._doc = fitz.open("pdf", data)
        self._display_cache = {}
        self._gpu_vector_cache.clear()
        self._gpu_vector_cache_bytes = 0
        self._gpu_scene_probe_cache.clear()
        self._render_generation += 1

    # --- 저장 -------------------------------------------------------

    @document_write
    def save_as(self, out_path, backup=True):
        """항상 새 파일로 쓴 뒤 교체한다(설계 §4) — 저장 중 죽어도 원본이 남는다.

        incremental save는 쓰지 않는다: 원본 파일에 직접 덧쓰기 때문에
        실패 시 파손 위험이 있다.

        Windows 주의: 열려 있는 원본과 같은 경로로 교체하려면 먼저 그
        핸들을 닫아야 한다(os.replace가 WinError 5로 거부됨). 그래서
        임시 파일에 저장 → 원본 핸들 닫기 → 교체 → 결과를 다시 여는
        순서로 처리한다.
        """
        out_path = os.fspath(out_path)
        if getattr(self, "_snapshot", None) is not None:
            return self._save_isolated(out_path, backup)
        fd, tmp = tempfile.mkstemp(prefix=".spdf-save-", suffix=".pdf",
                                   dir=os.path.dirname(os.path.abspath(out_path)))
        os.close(fd)
        same_path = os.path.normcase(os.path.abspath(out_path)) == \
            os.path.normcase(os.path.abspath(self.path))
        try:
            self._doc.save(tmp, garbage=3, deflate=True,
                           encryption=fitz.PDF_ENCRYPT_KEEP)
            if backup and os.path.exists(out_path):
                shutil.copy2(out_path, out_path + ".bak")
            if same_path:
                self._display_cache.clear()
                self._gpu_vector_cache.clear()
                self._gpu_vector_cache_bytes = 0
                self._doc.close()
                self._doc = None
            try:
                os.replace(tmp, out_path)
            except OSError:
                if same_path:
                    # Preserve pending edits even when another process keeps the
                    # destination locked. The extra memory is only used on error.
                    with open(tmp, "rb") as stream:
                        self._doc = fitz.open("pdf", stream.read())
                    if self._doc.needs_pass:
                        self._doc.authenticate(self._password or "")
                raise
            if same_path:
                self._doc = self._open(out_path, self._password)
                self.path = out_path
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _save_isolated(self, out_path, backup):
        """No source handle release, no reader handshake, no in-place writes.

        Cooperating writers use a nonblocking OS lock. A changed source is a
        conflict, never silently overwritten by a stale editor. External locks
        simply fail the save, leaving both the document and pending edits intact.
        """
        from .document_snapshot import file_revision
        from .save_transaction import destination_lock, atomic_backup
        same = os.path.normcase(os.path.realpath(out_path)) == os.path.normcase(os.path.realpath(self.path))
        expected = self._source_revision if same else file_revision(out_path)
        folder = os.path.dirname(os.path.abspath(out_path))
        fd, temporary = tempfile.mkstemp(prefix=".spdf-save-", suffix=".pdf", dir=folder)
        os.close(fd)
        try:
            self._doc.save(temporary, garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            # Validate and flush the completed file before touching the target.
            probe = self._open(temporary, self._password)
            try:
                if probe.page_count != self.page_count or probe.page_count < 1:
                    raise OSError("Saved PDF validation failed")
            finally:
                probe.close()
            with open(temporary, "rb+") as stream:
                os.fsync(stream.fileno())
            with destination_lock(out_path):
                if file_revision(out_path) != expected:
                    raise OSError("The PDF was changed by another writer. Use Save As to preserve both versions.")
                if backup and expected is not None:
                    atomic_backup(out_path)
                if file_revision(out_path) != expected:
                    raise OSError("The PDF changed during backup. Use Save As.")
                os.replace(temporary, out_path)
                self._source_revision = file_revision(out_path)
            # Keep editing the private copy; source handles are never reopened.
            self.path = out_path
            return self._source_revision
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
