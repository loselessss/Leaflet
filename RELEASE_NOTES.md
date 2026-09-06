# sPDF 1.30.1 Release Notes

Release date: 2026-09-05

## 1.28.0 highlights - 2026-09-02

### Performance improvements

- Isolated PDF groups using Soft Light, Multiply, Screen, Overlay, and seven other blend modes can now stay on the GPU path with their original backdrop and group opacity.

## 1.28.1 improvements - 2026-09-02

- Hue, Saturation, Color, and Luminosity blends in isolated PDF groups now also use GPU effects, preserving the backdrop and group opacity.

## 1.28.2 improvements - 2026-09-02

- Blended PDF groups inside nested geometry and text clips now also stay on the GPU path, preserving the backdrop and clipped edges.

## 1.28.3 improvements - 2026-09-02

- Blends and clipping inside alpha, luminosity, and image masks now also use the GPU, including nested masks.
- Colored luminosity masks follow PDF soft-mask color conversion, and grayscale mask images preserve their image interpolation settings.
- Non-isolated/knockout groups and mask transfer functions continue to use the CPU fallback.

## 1.28.4 improvements - 2026-09-02

- Standalone document tabs now sit in the title bar, using compact labels such as `file.pdf [Read/GPU]` and `[Edit/CPU]`.
- CPU/GPU labels follow actual rasterization instead of composition. CPU tiles show CPU, while mixed rasterization shows CPU+GPU.

## 1.28.5 improvements - 2026-09-03

- GPU-rendered pages keep grayscale antialiasing enabled more explicitly for smoother vector and text-outline edges.
- Expensive GPU scene preparation falls back after a short wait so difficult pages do not hold the reader for too long.
- Common linear and radial PDF gradients stay on the GPU path with fewer drawing operations.

## 1.28.6 improvement - 2026-09-03

- Some journal PDFs with missing display-list glyph ids now keep their original text outlines on the GPU path when the embedded/original font can map the character back to a vector glyph.
- The temporary Direct2D ABI overlay is no longer shown on GPU-rendered pages.

## 1.29.0 new features - 2026-09-03

- Editor mode can adjust the current page canvas size.
- Editor mode can set page bleed boxes while keeping existing artwork at its current size.
- Editable text elements can be resized from the editor context menu.
- The Direct2D renderer can now rasterize self-contained unsupported transparency groups as bounded CPU islands. Difficult local knockout effects may use a small approximate island so forced GPU rendering can stay active while page measurements and coordinates still come from the PDF model.
- Forced GPU mode now allows a longer scene preparation budget than automatic mode, so complex pages have more time to finish GPU scene extraction before falling back.

## 1.29.1 improvement - 2026-09-04

- PDF soft-mask transfer functions now stay on the Direct2D path using a GPU alpha transfer table. The native renderer ABI is now v17.
- Simple colored vector tiling patterns now expand into Direct2D scene items instead of forcing whole-page CPU fallback.
- Approximate CPU islands absorb small overlapping drawables into the same bounded raster island to reduce duplicate vector edges while keeping forced GPU rendering active.
- Consecutive same-color text glyph outlines are compacted into combined page-space paths, reducing GPU scene items and native path resources without changing PDF model coordinates.
- Linear and radial gradient primitives now remove redundant surrounding clip wrappers when the clip matches the gradient geometry, reducing scene commands on pages with many gradients.
- A disabled-by-default experimental similar-color band merge lets GPU renderer comparisons use a separate scene cache from the default exact-color path.
- Interactive zoom now transforms the current GPU scene immediately and waits until zoom input settles before refreshing image quality, avoiding scene extraction on every zoom step while preserving exact zoom values and page coordinates.

## 1.29.2 improvement - 2026-09-04

- Ctrl/Alt wheel zoom now animates the current GPU scene through exact intermediate page transforms and finishes at the requested zoom value. Image-quality scene refresh remains deferred until input settles.

## 1.29.3 performance improvement - 2026-09-04

- Direct2D pages now keep a retained native scene behind ABI v18, reducing each frame to one Python-to-native scene call. Scenes without bitmap-backed mask or blend captures are additionally compiled into reusable Direct2D command lists.

## 1.29.4 performance improvement - 2026-09-05

- Image masks and geometry clips now use bounded temporary GPU composition surfaces instead of repeatedly copying the whole window, improving interaction on complex poster and leaflet pages while preserving exact page transforms.

## 1.29.5 performance improvements - 2026-09-05

- Ordinary geometry clips on pages containing masks or blend groups now avoid unnecessary temporary GPU composition surfaces.
- Retained GPU scenes reuse gradient resources across frames, making zooming and panning substantially more responsive on gradient-heavy pages.
- Automatic and forced GPU modes accelerate simple rectangular clipping while keeping page coordinates and transforms exact. The native renderer ABI is now v19.
- Automatic mode quickly identifies highly complex pages, displays the CPU-rendered page first, and seamlessly replaces it with the GPU scene after background preparation completes.
- Deferred GPU preparation now starts reliably when a document tab becomes visible, and rendering diagnostics clearly distinguish the current CPU/GPU path from background GPU preparation.

## 1.29.6 fixes - 2026-09-05

- Fixed zoom percentages reverting after zooming in CPU and GPU modes.
- Zoom percentages now use screen DPI. Documents open fitted to the window width, including reopened documents.

- Fixed Windows fractional display scaling, including 150%, for the standalone interface.
- Rendering diagnostics distinguish CPU rendering with OpenGL composition and show Direct2D initialization failures.

## 1.29.7 improvements - 2026-09-05

- Rendering diagnostics now list CPU responsibilities alongside GPU scene contents, including tile rendering and scene/image preparation.

- GPU-drawn gradients are no longer reported as CPU bitmap work. Diagnostics distinguish rasterized gradients and CPU-composited transparency regions.

## 1.30.0 new features - 2026-09-05

- A shared 100 MiB disk cache reuses GPU scenes on subsequent opens at the same rendering scale. Old entries are removed automatically; changed files, protected documents and edited content cannot reuse stale scenes.
- Cache location: %LOCALAPPDATA%\sPDF\cache\gpu-scenes.sqlite3. Close sPDF before deleting this disposable cache.

## 1.30.1 improvements - 2026-09-06

- Disk caches store ordinary images as references to the original PDF instead of decoded pixels; drawing commands and expensive composition bitmaps are retained.
- Choose Off, 50, 100, 250 or 500 MB under rendering settings. Reducing the limit removes old entries immediately.

- Faster image preparation preserves the exact color and alpha values. Repeated images share GPU uploads, and the scene memory budget now includes vector and glyph commands.
- In automatic mode, higher-resolution image scenes are prepared in a separate process while the current view stays visible.
