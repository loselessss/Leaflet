# 3200% zoom validation

2026-11-02. Pending version 1.37.4; native ABI 24 and scene/cache formats unchanged.

## Display and preparation limits

- Maximum displayed/input zoom is 3200% in reader, page editor and artboards.
  Raw scene zoom is `32 * physicalDpiX / 72`, so the UI limit stays 3200%
  across monitors rather than becoming 2400% at 96 DPI or 1600% at 144 DPI.
- Percent input, shortcuts, reading-position validation, help and both README
  feature entries follow that limit. Existing 1.37.4 changes remain accumulated.
- Native raster preparation keeps its existing 64x maximum. Text/vector drawing
  uses the display transform. Dense displays may reach this bitmap preparation
  ceiling before reaching the display limit; no higher-resolution source detail
  is invented for raster images.
- Visible high-zoom image jobs still prepare a viewport plus nearby margin,
  bounded by 12 million projected pixels. CPU fallback tiles remain approximately
  512 px with overlap, at most 48 visible requests and a 64 MiB tile cache.
- Nearby-page speculation still prepares whole pages, so it is capped at the
  former 8x density. It must not eagerly prepare full neighboring pages at 64x.
  The visible page refines its bounded viewport at the higher target density.
- Artboard previews retain the 500,000-pixel per-page and 32 MiB cache limits.

## Curve quality

The old geometry realization uses a 0.05-local-unit flattening tolerance.
At high zoom that error can exceed half a device pixel. Filled paths now use
their original Direct2D geometry whenever projected error can exceed 0.5 px,
accounting for target DPI, rotation and shear. A command list recorded at low
zoom is also bypassed in that case. Normal-zoom tessellation storage does not
increase for every page. Existing sharp-frame/tile reuse remains available.

An independent circular-coverage test first records the low-zoom scene, then
draws at 64 device pixels per source unit, at both 96 and 192 DPI. Integrating
antialiased pixel coverage yields these maximum radial-edge errors against
the analytic circle:

| Renderer | Maximum error | Mean error |
|---|---:|---:|
| Previous renderer | 1.019 px | 0.637 px |
| Current renderer | 0.139 px | 0.043 px |

The half-pixel regression check fails with the previous DLL and passes with
the current one. The cubic circle differs from the analytic reference by less
than approximately 0.06 px in this test; this is not a claim about all PDF curves.

## Real-window check

Reproduce with `python -m tests.benchmark_high_zoom PDF --output REPORT.json`.
The harness uses isolated settings/recovery, disables disk cache, opens the real
standalone reader, enters 800% then 3200% through the percent widget, and pans
1.5 view widths and 1.25 heights beyond the previously prepared region.
Each stage waits for the new retained GPU scene and a short settling interval.

The test monitor reports 113 physical DPI in device-independent coordinates:
800% corresponds to raw zoom 12.556 and 3200% to 50.222. Native image preparation
uses density buckets 16 and 64 respectively. Window size is 1100 x 800.

| Poster | Display at 3200% | RSS at 800% | RSS at 3200% | RSS after pan |
|---|---|---:|---:|---:|
| ACB 2015 | CPU+GPU | 415.9 MiB | 442.6 MiB | 441.1 MiB |
| ACB 2019 | GPU | 349.8 MiB | 350.7 MiB | 355.9 MiB |

Prepared viewport area is about 8,386,066 pixels in every high-zoom stage,
below the unchanged 12-million-pixel bound. CPU tile storage stays 11,095,200
bytes. Scene packets at 800% -> 3200% -> new panned region:

- ACB 2015: 1,662,071 -> 1,631,670 -> 1,631,281 bytes.
- ACB 2019: 1,101,219 -> 361,295 -> 402,479 bytes.

These are single-process observations on this PC, not a VRAM measurement or a
universal memory guarantee. Caches, driver resources and native worker memory
can vary by document. The 2015 process grows by about 27 MiB on enlargement;
the renderer does not allocate a whole-page bitmap with sixteen times the area.
Private poster PDFs and raw reports stay outside source control.

## Checks

- Full isolated-module regression: 829 tests passed across 98 modules/cases.
  `git diff --check` also passed. Application/installer remain at pending 1.37.4.
- DPI cases 72/96/144/192: actual 3200% input, limits, fine zoom and saved state.
- High-DPI raster density stays within the native 64x contract.
- CPU high-zoom paths use bounded tiles rather than whole-page rasterization.
- GPU viewport margins stay bounded; moving past coverage requests a new region.
- Whole-page prefetch remains at 8x maximum when the visible view is at 3200%.
- Existing renderer, reader/editor, embedded-mode and DPI checks are included
  in the full regression run.

The benchmark explicitly owns QApplication and unlocks its private recovery
store before temporary-directory cleanup. This avoids a test-harness cleanup
failure from deleting a live QLockFile; application recovery behavior is unchanged.
