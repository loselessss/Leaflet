"""Idle, cancellable preparation of nearby pages using the scene worker."""

import logging
import os
import time

from .render_memory import render_memory, vector_gpu_budget, MIB
from .zoom_limits import MAX_PREFETCH_RASTER_SCALE

_log = logging.getLogger(__name__)
MAX_PREFETCH_WORKERS = 4
PREFETCH_WORKER_RESERVE = 128 * MIB


class ReaderPrefetchMixin:
    def _init_prefetch_state(self):
        self._prefetch_direction = 1
        self._prefetch_anchor = None
        self._prefetch_ready = {}
        self._prefetch_failures = {}
        self._prefetch_jobs = {}
        self._page_switch_started = None
        self._prefetch_metrics = {
            "scene_prepare_ms": 0.0, "prefetch_hit": 0,
            "page_switch_to_first_frame_ms": 0.0, "cancelled_jobs": 0,
        }

    def prefetch_diagnostic(self):
        packed = getattr(self._document, '_gpu_packed_cache', None)
        return dict(self._prefetch_metrics, cache_bytes=(
            self._document._gpu_vector_cache_bytes if self._document else 0),
            packed_pages=len(packed.entries) if packed else 0,
            packed_bytes=packed.bytes if packed else 0,
            packed_hits=packed.hits if packed else 0,
            active_workers=len(self._prefetch_jobs),
            worker_reserved_bytes=self._prefetch_worker_bytes())

    def _prefetch_worker_bytes(self):
        return sum(job.get("reservation", PREFETCH_WORKER_RESERVE)
                   for job in self._prefetch_jobs.values())

    def _prefetch_worker_room(self):
        return (len(self._prefetch_jobs) < MAX_PREFETCH_WORKERS and
                self._prefetch_worker_bytes() + PREFETCH_WORKER_RESERVE <= render_memory().scene_bytes)

    def _stop_prefetch_workers(self):
        for page in tuple(self._prefetch_jobs):
            self._cancel_prefetch_worker(page)

    def _cancel_prefetch_worker(self, page):
        job = self._prefetch_jobs.pop(page, None)
        if job is not None:
            self._prefetch_metrics["cancelled_jobs"] += 1
            self._prefetch_attempted.discard((job["generation"], job["page"], job["scale"]))
            self._dispose_vector_refine_job(job["process"], job)

    def _trim_prefetch_workers(self):
        from .render_memory import process_memory_bytes
        nearby = self._nearby_prefetch_pages()
        enabled = self._document is not None and self._prefetch_enabled() and self.isVisible()
        for page, job in tuple(self._prefetch_jobs.items()):
            if (not enabled or job["document"] is not self._document or
                    job["generation"] != self._document.render_generation or page not in nearby):
                self._cancel_prefetch_worker(page)
                continue
            job["reservation"] = max(job["reservation"],
                process_memory_bytes(job["process"]) + 32 * MIB)
        # The worker allowance is separate from the bounded hot/packed cache.
        # Together these use at most twice the adaptive scene budget.
        limit = render_memory().scene_bytes if render_memory().prefetch_pages else 0
        for page in reversed(tuple(self._prefetch_jobs)):
            if self._prefetch_worker_bytes() <= limit:
                break
            self._cancel_prefetch_worker(page)

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
        for page in reversed(tuple(self._d2d_vector_paths)):
            cached = self._d2d_vector_paths[page]
            if page in self._page_sizes:
                continue
            cost = _gpu_scene_cost(cached[0])
            current = (self._vector_viewport_pages.get(page)
                       if getattr(self, '_document_generation', None) == self._document.render_generation else None)
            if current is not cached[0]:
                current = self._document.cached_gpu_vector_page(
                    page, cached[0].raster_scale, memory_only=True, restore_compressed=False)
            if self._document.has_packed_gpu_scene(page, cached[0].raster_scale):
                current = None  # Release the raw packet reference held by inactive native scenes too.
            if current is not cached[0] or used + cost > budget:
                self._discard_native_vector_page(page)
            else:
                used += cost
        self._vector_viewport_pages = {p: scene for p, scene in self._vector_viewport_pages.items()
            if p in self._page_sizes or p in self._d2d_vector_paths}

    def _nearby_prefetch_pages(self):
        if self._document is None or not self._page_sizes:
            return []
        memory = render_memory()
        count = memory.prefetch_pages
        if not count:
            return []
        samples = len(self._document._gpu_vector_cache)
        if samples:
            # Small papers can fit many more pages than image-heavy posters.
            average = max(MIB, self._document._gpu_vector_cache_bytes // samples)
            budget = min(memory.scene_bytes * 3 // 4, self._document.gpu_scene_memory_budget())
            count = max(count, budget // average)
        count = min(count, self._document.page_count)
        first, last = min(self._page_sizes), max(self._page_sizes)
        candidates = []
        for distance in range(1, count + 1):
            pair = [last + distance, first - distance]
            candidates.extend(pair if self._prefetch_direction > 0 else reversed(pair))
        return [page for page in candidates if 0 <= page < self._document.page_count
                and page not in self._page_sizes][:count]

    def _schedule_page_prefetch(self, delay=180):
        self._prefetch_timer.stop()
        if (self._prefetch_enabled() and self._document is not None and
                self._d2d_requested and self.isVisible()):
            self._prefetch_timer.start(delay)

    def _pause_page_prefetch(self):
        # Scrolling alone does not invalidate preparation of the next page.
        # A foreground request or memory pressure still preempts this worker.
        self._schedule_page_prefetch()

    def _prefetch_next_page(self):
        document = self._document
        if (not self._prefetch_enabled() or document is None or
                not self.isVisible() or not self._d2d_requested):
            return
        self._trim_prefetch_workers()
        document.reserve_gpu_scene_memory(32 * MIB, self._page_sizes)
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
            if document.has_packed_gpu_scene(page, scale):
                continue  # Leave the RAM archive packed until the reader actually needs it.
            prepared = document.cached_gpu_vector_page(page, scale, memory_only=True,
                                                       restore_compressed=False)
            if prepared is not None:
                # Upload one page per idle turn, including complex posters.
                # Actual RAM/VRAM budgets replace command-count/page-count caps.
                from .core import _gpu_scene_cost
                resident = sum(_gpu_scene_cost(cached[0]) for p, cached in self._d2d_vector_paths.items()
                               if p not in self._page_sizes)
                if (self._d2d_surface is not None and prepared.compiled_packet and
                        resident + _gpu_scene_cost(prepared) <= self._native_retention_budget and
                        page not in self._d2d_vector_paths):
                    try:
                        self._native_vector_draws(page, prepared)
                        self._trim_nearby_native_pages()
                    except (OSError, RuntimeError, ValueError):
                        self._discard_native_vector_page(page)
                    else:
                        self._schedule_page_prefetch()
                        return
                continue
            if page in self._prefetch_jobs or key in self._prefetch_attempted or page in self._prefetch_failures:
                continue
            if not self._prefetch_worker_room():
                return
            self._prefetch_attempted.add(key)
            self._vector_refine_scale = scale
            self._start_vector_refine_worker(page, speculative=True)
            return
