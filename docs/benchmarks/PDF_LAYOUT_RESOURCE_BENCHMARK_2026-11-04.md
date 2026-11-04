# PDF layout resource experiment — 2026-11-04

This began as an isolated PyMuPDF 2.1 / MuPDF 1.28.6 experiment. At measurement
time, the application still used PyMuPDF 1.28.2 at pending Leaflet 1.37.6;
no production dependencies were changed during that experiment. The subsequent
1.38.0 implementation and validation are recorded below.

## Method

ACB 2015 and ACB 2019, first page; separate processes for the current engine,
new core without layout calls, and the layout model. Ordinary preparation extracts
`get_text("dict")` and renders a bounded 1100×800 preview. This is not total GUI
memory or a GPU-rendering benchmark. Memory is process working set (MiB), with
Windows peak working set; CPU time sums all threads. Each process analyzes twice
and idles for two consecutive two-second intervals. Core cases have two processes;
layout settings have three. Tables below use medians. The process exits after
each case, releasing its models. A 2 GiB RSS / 120 second guard was never reached.

Limited settings: ONNX Runtime intra-op threads = 2, inter-op threads = 1,
and intra/inter-op idle spinning disabled. This affects this experiment process
only; NumPy/other runtime threads remain, so total threads are not limited to 2.

## Results

| Document | Setting | Model initialization (s) | First analysis (s) | CPU init + analysis (s) | Retained RSS (MiB) | Added RSS (MiB) | Peak RSS (MiB) | Threads |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ACB 2015 | Default | 2.44 | 2.47 | 30.33 | 230 | 145 | 367 | 45 |
| ACB 2015 | Limited | 1.42 | 2.09 | 3.33 | 224 | 139 | 361 | 21 |
| ACB 2019 | Default | 2.64 | 6.19 | 30.70 | 369 | 148 | 515 | 45 |
| ACB 2019 | Limited | 1.39 | 3.86 | 5.03 | 364 | 143 | 510 | 21 |

The new core does not import ONNX Runtime or the layout module during the ordinary
operation tested. Its retained RSS is essentially unchanged from the old core
(about 85 MiB for ACB 2015 and 221 MiB for ACB 2019). The first new-core import
was about 0.91 s; the next was about 0.19 s, so filesystem/cache warmup matters.

Default inference leaves spinning workers active briefly: roughly 4.6 CPU seconds
for ACB 2015 and 7.4 CPU seconds for ACB 2019 during the first two-second idle
window. Both settle to about zero CPU usage in the next window. Limited settings
consume about zero idle CPU immediately, while retaining the model memory.

## Output validation

Default and limited settings return identical classification/coordinate hashes
(coordinates rounded to 0.0001 pt), with 21 regions for ACB 2015 and 24 for ACB 2019.
Labels include text, section headers, lists, pictures and page headers/footers.
This checks configuration equivalence; it does not establish ground-truth layout accuracy.

## Disk cost and integration decision

Installed PyMuPDF package files: 52.9 → 104.2 MiB; the new package contains 48.9 MiB of ONNX models (including alternatives).
These are source-environment package sizes, not an MSIX/installer size estimate.

The model is feasible as opt-in, page-at-a-time analysis in a separate process.
Limit inference threads and disable idle spinning; terminate the helper when it
is no longer needed to release resident model memory. Ordinary reading should
not trigger analysis. The subsequent migration required native SDK rebuilds
and GPU/scene validation (see implementation validation below). Tables, scans and long documents may behave differently;
only these two poster pages were measured.

## Reproduction

Run `tests/benchmark_pdf_layout.py --help`. Install candidate packages with
`pip --target` in a separate folder and pass it with `--packages`. Use
`--modes layout --threads 2 --no-spin` for the limited configuration. Reports
contain timing/resource metadata and detection counts, not document text.
Private PDFs and raw results remain outside Git.

[Official layout documentation](https://pymupdf.readthedocs.io/en/latest/rag.html#pymupdf-pymupdf-layout)


## Applied implementation: Leaflet 1.38.0 (unreleased)

- Upgrade PyMuPDF to 2.1 / MuPDF 1.28.6 and rebuild the native input bridge.
- Add opt-in **Copy in reading order** (Ctrl+Shift+C), selected text or current
  page only. Use original PDF words, with no generated text. No model is loaded
  during ordinary reading. Each model process exits after its single request.
- Limit ORT intra-op/inter-op threads to 2/1 and disable idle spinning. Cancel
  on page changes/document close; reject stale results. Enforce 60 s / 1.5 GiB
  worker limits and PDF copy permissions.
- Package three default ONNX models (13.6 MiB); reuse the isolated OCR runtime.
  Omit unused model variants. Uncompressed GUI + OCR payload is **373.4 MiB**,
  about 15.5 MiB above the updated pre-layout package (~358 MiB), and about
  39 MiB below the initial 412 MiB package. This is not compressed MSIX size.
- **844 automated tests pass**, including cancellation, private-file cleanup,
  selected-only copy, rotation, no-copy PDFs, stale results and embedded menus.
  One old renderer test assumed two internal drawing items for a rectangle;
  replace that assumption with scene equivalence and unchanged CPU pixels.
- Final packaged ACB 2015/2019 analysis preserves every extracted word and
  exits normally. Packaged GPU scenes match current source scenes/pixels at
  fit view and 800%: ACB 2015 CPU+GPU, ACB 2019 GPU. This comparison verifies
  source/package equivalence, not exact equivalence to the old PDF engine.
- Final packaged Korean/English/digits OCR and GUI startup pass. Ordinary GUI
  viewing does not load the ONNX runtime. Correct PyInstaller's eager QtCore
  runtime-hook initialization for headless jobs, and explicitly include the
  native `pymupdf.features` module required by layout analysis.
