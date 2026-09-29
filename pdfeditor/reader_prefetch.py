"""Idle, cancellable preparation of nearby pages using the scene worker."""

import logging
import os
import time

from .render_memory import render_memory, MIB

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
        keep = set(self._page_sizes) | set(self._nearby_prefetch_pages())
        budget = self._document.gpu_scene_memory_budget() // 2
        used = 0
        for page in reversed(tuple(self._d2d_vector_paths)):
            cached = self._d2d_vector_paths[page]
            if page in self._page_sizes:
                continue
            cost = _gpu_scene_cost(cached[0])
            current = self._document.cached_gpu_vector_page(
                page, self._vector_raster_scale(), memory_only=True)
            if page not in keep or current is not cached[0] or used + cost > budget:
                self._discard_native_vector_page(page)
            else:
                used += cost

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
            self._prefetch_timer.start(700)

    def _pause_page_prefetch(self):
        job = self._vector_refine_job
        if job and job.get("speculative"):
            self._prefetch_attempted.discard((job["generation"], job["page"], job["scale"]))
            self._stop_vector_refine_worker()
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
        scale = self._vector_raster_scale()
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
            if key in self._prefetch_attempted:
                continue
            if page in self._prefetch_failures:
                continue
            if document.cached_gpu_vector_page(page, scale, memory_only=True) is not None:
                continue
            self._prefetch_attempted.add(key)
            self._vector_refine_scale = scale
            self._start_vector_refine_worker(page, speculative=True)
            return
