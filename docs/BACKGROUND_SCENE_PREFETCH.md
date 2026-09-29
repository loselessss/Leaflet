# Background scene prefetch

## Implemented policy (1.34.3)

- One below-normal-priority subprocess owns an immutable PDF snapshot. No PyMuPDF document is shared across Python threads.
- Visible-page preparation preempts speculative work. Input pauses prefetch; it resumes after 700 ms idle. Hidden views and closed documents stop workers.
- Forward navigation prepares next, previous, next+1, previous-1; backward navigation reverses the order. Available memory limits the window to at most four pages. No whole-document preload.
- Polling cancels speculative work on document revision changes or memory pressure. Results require matching document/revision and nearby-page membership. The process/job pair identifies the current request; stopped jobs cannot install results.
- Vector geometry is reusable across zoom buckets. A lower-resolution image scene remains visible while the existing image-refinement worker rebuilds resolution-dependent resources, including CPU islands where supported. Unsupported refinement retains the existing full-extraction fallback.
- Structural unsupported-operation results are retained only for the nearby window, matching revision and scale. Timeouts are not treated as permanent CPU-only results.
- CPU scene preparation remains separate from device resources. Unvisited pages are uploaded on display; visited nearby native scenes retain the existing bounded cache. No concurrent GPU warm-up or additional worker is introduced.

## Measurement

`ReaderPageView.prefetch_diagnostic()` reports `scene_prepare_ms` (parent-observed worker latency, including launch and IPC), `prefetch_hit` (consumed prepared scenes), `page_switch_to_first_frame_ms` (first completed paint, which can be a preview), `cache_bytes` (document CPU scene cache estimate), and `cancelled_jobs`. The `pdfeditor.reader_prefetch` debug logger emits the snapshot at first paint. These are not GPU timing or total process/VRAM measurements.

Set `LEAFLET_SCENE_PREFETCH=0` before launch for the off arm of an A/B comparison; the default is enabled. Use identical page sequences and zoom settings, and measure first preview separately from availability of the complete GPU scene. A prepared scene removes parsing/worker startup from the page transition; preview rasterization and first GPU upload can still dominate the first frame. Do not increase worker count without measurements demonstrating a net benefit.

A local five-run synthetic multi-page comparison with disk scene lookup disabled measured median scene availability after the page switch at about 180 ms without prefetch and 2 ms with a completed prefetch. This used the real subprocess and an offscreen Qt view; it excludes native GPU upload/presentation and is not a first-visible-frame speedup claim. No extra worker is justified by this measurement.

## Deferred work

Adaptive two-worker operation, unvisited-page GPU warm-up, shared cross-page glyph resources and CPU-only page tile prefetch need separate performance and memory measurements. The current RAM-based scene estimate and native GPU budgets are separate bounds, not a hard cap on the application's total resident memory.
