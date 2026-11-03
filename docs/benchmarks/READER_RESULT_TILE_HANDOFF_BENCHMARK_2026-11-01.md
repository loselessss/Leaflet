# GPU result reception and CPU tile handoff

2026-11-01. Pending version 1.37.4; scene/cache formats and renderer ABI unchanged.

## Scope

1. The GUI polls the independent Rust scene worker, then a single background
   decoder reads, validates and restores its private result. It owns result
   files until decoding and cleanup finish. The GUI polls completion at 5 ms
   and installs only results matching the document generation and display state.
2. CPU fallback tiles borrow the owned MuPDF RGB pixmap until a synchronous copy
   into Qt-owned storage. `Document.render_region(..., copy_pixels=True)` keeps
   its existing default bytes API; the reader requests `copy_pixels=False`.

Rust LZ4 decoding releases the GIL. The input is pinned immutable Python bytes;
the output is an exclusive, unpublished `PyBytes::new_with` allocation. Detached
code touches only these slices. No Qt or MuPDF objects cross worker threads.
Cancellation does not wait on decoding; cancelled queued reads skip allocation,
and cancelled completed scenes are discarded. File cleanup belongs to the reader
task so closing a document cannot race its active result file handle.

## Method

`python -m tests.benchmark_reader_handoff POSTER2015 POSTER2019 --output REPORT.json --runs 5`

- Windows x64, project Python 3.12.14, MuPDF 1.28.2, release Rust extension.
- Native worker results at 1x and 8x. Compare the previous synchronous `load()`
  route with background reception of identical result files; one warm-up and
  five measured trials, alternating route order. Input setup is outside timing.
- A real Qt event loop has a 1 ms heartbeat. Report the median of each trial's
  largest heartbeat gap, dispatch time and completion time. These are warm
  result-reception measurements, not document-open or complete-frame timings.
  The 8x benchmark intentionally uses whole-page packets; normal high-zoom
  reading prepares a bounded viewport region and generally receives less data.
- CPU tiles: 512 px cores plus overlap, scales 1.375 and 8, rotations 0 and 90.
  Compare 60 handoff samples per route and five raster-plus-handoff samples.
  Handoff includes `QPixmap.fromImage`. Python allocation peaks use tracemalloc;
  Qt/MuPDF/GPU storage and total working-set savings are not represented by it.
- Raw local JSON/logs remain under `tmp/rust-audit/`; private PDFs are not bundled.

## Result reception

All values in milliseconds; synchronous → background.

| Poster | Scale | GUI dispatch | Largest GUI heartbeat gap | Result completion |
|---|---:|---:|---:|---:|
| ACB 2015 | 1x | 15.002 → 0.115 | 15.195 → 1.938 | 15.001 → 24.957 |
| ACB 2015 | 8x | 55.366 → 0.083 | 55.652 → 9.189 | 55.366 → 70.338 |
| ACB 2019 | 1x | 27.518 → 0.085 | 27.611 → 4.606 | 27.517 → 40.098 |
| ACB 2019 | 8x | 111.973 → 0.086 | 112.811 → 18.491 | 111.971 → 134.320 |

Background reception improves responsiveness. Its scheduling, polling and
concurrent GUI work increase completion time in this run; it does not make the
PDF compiler or the result decoder itself faster. At 8x, completion increases
by approximately 15 ms / 22 ms while the largest GUI gaps fall by 83% / 84%.
Packet SHA-256 hashes match across every route and repetition.

## CPU tile handoff

Representative 8x, unrotated, 514 × 514 RGB tiles:

| Poster | Handoff ms, bytes → borrow | Raster + handoff ms | Python transient peak, bytes → borrow |
|---|---:|---:|---:|
| ACB 2015 | 0.384 → 0.342 | 8.260 → 8.399 | 793,765 → 1,123 bytes |
| ACB 2019 | 0.389 → 0.365 | 2.917 → 2.818 | 793,765 → 1,123 bytes |

Transfer alone improves slightly; overall tile time varies around the unchanged
MuPDF rasterization cost. The reliable memory change is removal of the temporary
Python RGB bytes copy (about 0.76 MiB per full-size tile). Qt still owns a complete
tile, and the bounded 64 MiB tile cache is unchanged. All eight poster/scale/rotation
cases have identical origins and zero differing RGB channels.

## Verification

- All 820 tests passed across the complete isolated-module suite, completed in
  two segments. A transient settings-file replacement lock in the untracked
  scratch tree was avoided by using the ignored `.test-runtime` directory for
  the remaining modules. No production settings/save behavior was changed.
- The development-launch fixture now waits for its real Python/Pythonw child
  to exit before deleting the temporary interpreter. Result publication alone
  preceded shutdown and intermittently left `pythonw.exe` locked on Windows.
- Actual Qt view tests cover background decode thread identity, a responsive GUI
  timer during a blocked read, close/cancel during decode, stale generations,
  queued cancellation, startup failure and specific worker/result errors.
- Concurrent Rust decoders share immutable input only. Mutable exporters are
  rejected; malformed packets remain bounded and fail without exposing output.
- CPU tile tests cover odd widths, crop/rotation, fractional scale and 8x,
  original pixel origins, document-close lifetime and Qt-owned copied images.
- The actual reader tile consumer is tested with `Pixmap.samples` disabled.
  It produces tiles without allocating Python pixel bytes.
- Real development windows open both posters with disk cache disabled, complete
  their initial GPU frame, then zoom to 800% and import the viewport scene.
  Both jobs read on the background thread and install on the GUI thread.
  ACB 2019 reports GPU and ACB 2015 reports CPU+GPU throughout. Received viewport
  packets are approximately 2.45 MB and 1.66 MB respectively in this window.
