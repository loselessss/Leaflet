# Type3 vector text — 2026-11-04

Pending Leaflet 1.38.0; PyMuPDF 2.1 / MuPDF 1.28.6. One private one-page
Edge/Chromium Skia invoice, with two Type0 and 26 Type3 font resources.
The Type3 programs contain 103 vector glyphs and one blank glyph. No document
text, identifiers, financial details, source file or screenshots are published.

## Implementation

The native MuPDF input adapter runs an uncolored Type3 glyph into a bounded
capture device, accepts one opaque filled path (or an empty glyph), and sends
its outline through the existing Rust/GPU path. Preserve the font/program
matrix, enclosing text color/opacity and even-odd holes. Walk packed display
paths directly, transforming owned path bytes; do not clone/mutate MuPDF's
packed path storage.

Colored glyphs, multiple independently painted paths, internal strokes/clips,
images, internal opacity, or graphics-state-dependent programs keep the existing
rendering path. MuPDF may already expand some Type3 programs directly before
text capture; preserve that behavior. Limit capture to 32 operations and retain
the existing deadline, per-path and total glyph budgets. Bump scene cache
semantics from 17 to 18 so prior raster text does not remain cached.

## Fresh-process preparation comparison

Same native executable and MuPDF DLL, swapping only the previous/current input
bridge. Three fresh processes per setting, alternating before/after order;
medians include launch, PDF preparation and scene-file output. Peak memory is
that worker's Windows peak working set, not total GUI/GPU memory. These are
preparation timings, not animation frame times.

| Scale | Before / after time | Before / after peak | Before / after scene bytes |
| --- | --- | --- | --- |
| 100% | 143.8 / 144.9 ms | 17.8 / 17.9 MiB | 437,587 / 320,693 |
| 800% | 262.0 / 146.2 ms | 39.6 / 17.9 MiB | 11,635,655 / 320,693 |
| 3200% | 872.9 / 211.8 ms | 335.3 / 17.9 MiB | failed / 320,693 |

At 3200%, the old path exceeds the compiler image budget and falls back. The
new path succeeds with zero text bitmaps. Its compiled GPU packet is identical
at all three scales. Command count falls from 299 to 270. Fit-view preparation
time is essentially unchanged; the gains are high-zoom memory, preparation and
continuous vector text during animated scaling.

## Validation

134 focused renderer/cache/worker tests pass, including glyph holes, color,
transforms, ordinary fonts, clipping, gradients, masks and complex Type3 fallback.
Compare actual native GPU frames with MuPDF CPU images at fit and animated
magnifications. The 800% animation check reuses the original 100% scene to
expose the previous bitmap upscaling: Type3 labels become visibly sharper.
Contour antialiasing can differ; this is not a pixel-identical rendering claim.

Private raw reports and visual checks are under `.test-runtime/type3/`.

Final packaged checks also pass at 100%, 800% and 3200%, with packets identical
to the source build and no text bitmap preparation. ACB 2015/2019 source/package
scenes and frames still match at fit and 800%; ordinary GUI startup passes.
The focused glyph-pixel cases include enclosing text opacity as well as color,
even-odd holes and sheared placement. At fit view and in the 800%/3200% label
crops, the new GPU frames have no differences above 3/255 in CPU-reference
interiors that are at least two pixels from an edge; edge antialiasing differs.
