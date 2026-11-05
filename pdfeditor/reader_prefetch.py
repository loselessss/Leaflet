"""Idle, cancellable preparation of nearby pages using the scene worker."""

import logging
import os
import time

from .render_memory import render_memory, vector_gpu_budget, MIB
from .zoom_limits import MAX_PREFETCH_RASTER_SCALE

_log = logging.getLogger(__name__)


class ReaderPrefetchMixin:
    def _init_prefetch_state(self):
        self._prefetch_direction = 1
        self._prefetch_anchor = None
        self._prefetch_ready = {}
        self._prefetch_failures = {}
        self._page_switch_started = None
        self._prefetch_metrics = {
            "scene_prepare_ms": 0.0, "prefetch_hit": 0,
            "page_switch_to_first_frame_ms": 0.0, "cancelled_jobs": 0,
        }

    def prefetch_diagnostic(self):
        return dict(self._prefetch_metrics, cache_bytes=(
            self._document._gpu_vector_cache_bytes if self._document else 0))

    def _prefetch_enabled(self):
        return os.environ.get("LEAFLET_SCENE_PREFETCH", "1").lower() not in (
            "0", "false", "off", "no")

    def _begin_page_switch(self, document, active_page):
        changed = document is not self._document
        if changed:
            self._prefetch_direction = 1
            self._prefetch_ready.clear()
            self._prefetch_failures.clear()
        elif self._prefetch_anchor is not None and active_page != self._prefetch_anchor:
            self._prefetch_direction = 1 if active_page > self._prefetch_anchor else -1
        self._prefetch_anchor = active_page
        self._page_switch_started = time.perf_counter()

    def _record_first_page_frame(self):
        if self._page_switch_started is not None:
            self._prefetch_metrics["page_switch_to_first_frame_ms"] = (
                time.perf_counter() - self._page_switch_started) * 1000
            self._page_switch_started = None
            _log.debug("reader prefetch %s", self.prefetch_diagnostic())

    def _trim_nearby_native_pages(self):
        from .core import _gpu_scene_cost
        video = None
        surface = self._d2d_surface
        if surface is not None and getattr(type(surface), 'supports_video_memory_query', False):
            video = surface.video_memory()
        budget = vector_gpu_budget(self._document.gpu_scene_memory_budget(), video)
        self._native_retention_budget = budget
        used = 0
        kept = len(self._page_sizes)
        for page in reversed(tuple(self._d2d_vector_paths)):
            cached = self._d2d_vector_paths[page]
            if page in self._page_sizes:
                continue
            cost = _gpu_scene_cost(cached[0])
            current = (self._vector_viewport_pages.get(page)
                       if getattr(self, '_document_generation', None) == self._document.render_generation else None)
            if current is not cached[0]:
                current = self._document.cached_gpu_vector_page(
                    page, cached[0].raster_scale, memory_only=True)
            if current is not cached[0] or used + cost > budget or kept >= 128:
                self._discard_native_vector_page(page)
            else:
                used += cost
                kept += 1
        self._vector_viewport_pages = {p: scene for p, scene in self._vector_viewport_pages.items()
            if p in self._page_sizes or p in self._d2d_vector_paths}

    def _nearby_prefetch_pages(self):
        if self._document is None or not self._page_sizes:
            return []
        count = render_memory().prefetch_pages
        first, last = min(self._page_sizes), max(self._page_sizes)
        candidates = []
        for distance in range(1, count + 1):
            pair = [last + distance, first - distance]
            candidates.extend(pair if self._prefetch_direction > 0 else reversed(pair))
        return [page for page in candidates if 0 <= page < self._document.page_count
                and page not in self._page_sizes][:count]

    def _schedule_page_prefetch(self):
        self._prefetch_timer.stop()
        if (self._prefetch_enabled() and self._document is not None and
                self._d2d_requested and self.isVisible()):
            self._prefetch_timer.start(180)

    def _pause_page_prefetch(self):
        # Scrolling alone does not invalidate preparation of the next page.
        # A foreground request or memory pressure still preempts this worker.
        self._schedule_page_prefetch()

    def _prefetch_next_page(self):
        document = self._document
        if (not self._prefetch_enabled() or document is None or
                not self.isVisible() or not self._d2d_requested):
            return
        document.trim_gpu_scene_memory(self._page_sizes)
        self._trim_nearby_native_pages()
        if (self._vector_refine_process is not None or self._vector_refine_pages or
                self._zoom_animation_timer.isActive() or
                getattr(self, "_gpu_initial_frame_pending", False)):
            self._schedule_page_prefetch()
            return
        budget = document.gpu_scene_memory_budget()
        if budget - document._gpu_vector_cache_bytes < 32 * MIB:
            return
        # Speculation prepares a whole page. Keep its existing density ceiling;
        # the visible page can then refine only its bounded high-zoom viewport.
        scale = min(self._vector_raster_scale(), MAX_PREFETCH_RASTER_SCALE)
        generation = document.render_generation
        nearby = self._nearby_prefetch_pages()
        self._prefetch_ready = {page: value for page, value in self._prefetch_ready.items()
                                if page in nearby and value[0] == generation}
        self._prefetch_failures = {page: value for page, value in self._prefetch_failures.items()
                                   if page in nearby and value[0] == generation and value[1] == scale}
        self._prefetch_attempted = {key for key in self._prefetch_attempted
                                   if key[0] == generation and key[1] in nearby and key[2] == scale}
        for page in nearby:
            key = generation, page, scale
            prepared = document.cached_gpu_vector_page(page, scale, memory_only=True)
            if prepared is not None:
                # Upload at most one modest vector page per idle turn. Complex
                # posters still defer their expensive upload until displayed.
                from .core import _gpu_scene_cost
                resident = sum(_gpu_scene_cost(cached[0]) for p, cached in self._d2d_vector_paths.items()
                               if p not in self._page_sizes)
                if (self._d2d_surface is not None and prepared.compiled_packet and
                        resident + _gpu_scene_cost(prepared) <= self._native_retention_budget and
                        prepared.command_count <= 2048 and page not in self._d2d_vector_paths):
                    try:
                        self._native_vector_draws(page, prepared)
                        self._trim_nearby_native_pages()
                    except (OSError, RuntimeError, ValueError):
                        self._discard_native_vector_page(page)
                    else:
                        self._schedule_page_prefetch()
                        return
                continue
            if key in self._prefetch_attempted or page in self._prefetch_failures:
                continue
            self._prefetch_attempted.add(key)
            self._vector_refine_scale = scale
            self._start_vector_refine_worker(page, speculative=True)
            return
