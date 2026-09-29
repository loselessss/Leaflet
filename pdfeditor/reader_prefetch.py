"""Idle, cancellable preparation of nearby pages using the scene worker."""

from .render_memory import render_memory, MIB


class ReaderPrefetchMixin:
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
        candidates = [last + 1, first - 1, last + 2, last + 3]
        return [page for page in candidates if 0 <= page < self._document.page_count
                and page not in self._page_sizes][:count]

    def _schedule_page_prefetch(self):
        self._prefetch_timer.stop()
        if self._document is not None and self._d2d_requested and self.isVisible():
            self._prefetch_timer.start(700)

    def _pause_page_prefetch(self):
        job = self._vector_refine_job
        if job and job.get("speculative"):
            self._prefetch_attempted.discard((job["generation"], job["page"], job["scale"]))
            self._stop_vector_refine_worker()
        self._schedule_page_prefetch()

    def _prefetch_next_page(self):
        document = self._document
        if document is None or not self.isVisible() or not self._d2d_requested:
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
        self._prefetch_attempted = {key for key in self._prefetch_attempted
                                   if key[0] == generation and key[1] in nearby and key[2] == scale}
        for page in nearby:
            key = generation, page, scale
            if key in self._prefetch_attempted:
                continue
            if document.cached_gpu_vector_page(page, scale, memory_only=True) is not None:
                continue
            self._prefetch_attempted.add(key)
            self._vector_refine_scale = scale
            self._start_vector_refine_worker(page, speculative=True)
            return
