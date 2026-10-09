# Changelog

## Unreleased

### 성능 개선

- Reuse the existing GPU raster during animated zoom on pages with complex transparency instead of repeating composition at every intermediate scale.
- Keep bounded GPU snapshots of expensive transparency and mask groups, including their backdrop, across nearby zoom scales. Redraw vectors outside those groups at the current scale; edge and interpolation differences are accepted for display.
- Reduce high-zoom refresh work by cropping display rasters to the viewport with a small pan margin, caching visible group portions with coverage checks, skipping offscreen scopes, and composing source-over-only groups with vector clip/opacity layers instead of temporary backdrop images.
- Prefer speed when refreshing expensive display groups: compose at 75% linear display density, resample with high-quality cubic interpolation, reuse snapshots up to 2× their stored scale, and share one bounded scratch bitmap. Vectors outside those groups and saved PDF content retain their original rendering.
- After zoom or pan settles, prepare an exact GPU frame on a separate rendering context and replace the fast display when it is ready. Cancel outdated jobs, share immutable scene resources, and keep one active job plus the latest pending request with bounded viewport-sized results.
- Prepare full-density GPU composition in 512 px tiles, prioritize the viewport center, and display completed tiles progressively. Cull individual drawing commands using retained bounds, use vector layers for ordinary source-over scopes, and keep a small overlap at tile edges while preserving the fast page until all sharp tiles are ready.
- Start sharp GPU refinement after 90 ms of inactivity to reduce the wait after zooming stops.

### 기타

- Add the Microsoft Store download link to both READMEs and recommend it for the stable version.

## 1.35.0 - 2026-10-08

### 개선

- Choose whether to remove document metadata and Leaflet object re-editing information when saving as PDF. Both options are off by default and preserve visible content.
- Bundle source, dependency-source directions and checksums into one release-files ZIP, and stop creating sPDF-named installer and executable aliases.
- Select existing images placed directly on PDF pages to move, resize, or delete them, with undo and redo. Images inside groups or clipping scopes are excluded.
- Click an image or editable object in the editor to select it automatically; text clicks continue to edit or select text.
- Highlight editable objects on hover and resize selections with eight handles, image aspect locking and Shift-constrained movement. Organize position and size controls in the right properties panel.
- Delete selected objects with Delete, move them with arrow keys, cancel or clear selections with Esc, and hold Space to pan temporarily while keeping the editing state.

### 성능 개선

- Open files faster when the reader is resident by forwarding launches before GUI initialization and reducing repeated interface translation during tab creation.
- Reduce installer and MSIX size by omitting unused video libraries, AVIF codecs, Qt web-display components and unused Qt translations while preserving GPU rendering, supported image imports and OCR process isolation.

## 1.34.8 - 2026-10-07

### 개선

- Select multiple files in the Open dialog and open each in its own tab, reusing existing tabs for already-open files.

### 버그 수정

- Ask before removing files that cannot be opened from Recent Files and Favorites, without deleting the original file.
- Refresh the entire window, including the title bar and child surfaces, after monitor scaling changes and window dragging ends.

## 1.34.7 - 2026-10-06

### 새 기능

- Reopen closed documents with Ctrl+Shift+T, restoring their page and zoom.
- Move a tab to a new window from its context menu while preserving edits.
- Drag tabs out into new windows or into another window's tab strip, with insertion markers and Escape cancellation.

### 버그 수정

- Remove temporary backups after successful saves and automatically remove Windows save-lock files when saving ends.
- Fix false text-box overflow errors when replacing text that fits the original line box.
- Preserve original fonts, sizes and positions when editing a fragment within mixed-format text, such as a date or number.
- Fix failures when starting the editor workspace.
- Refresh window layout and native rendering surfaces after display scaling changes, without changing document zoom.
- Keep nested blends inside non-isolated Normal transparency groups on the GPU, and prepare luminosity masks before the first GPU frame.

## 1.34.5 - 2026-09-30

### 버그 수정

- Keep filled text without font outlines on the GPU by rendering the original text to transparent images and refreshing their resolution when zooming.

## 1.34.4 - 2026-09-29

### 버그 수정

- Keep pages with empty font glyphs on the GPU, preserving empty text clipping and visible text.

## 1.34.3 - 2026-09-29

### 성능 개선

- Prepare nearby pages in the direction of travel and pause background work when the current page or available memory needs priority.
- Reuse prepared vector scenes across zoom changes while refining image resolution separately.

## 1.34.2 - 2026-09-29

### 성능 개선

- Adjust rendering caches to available RAM and GPU memory, and prepare nearby pages in a low-priority background process while idle.
- Reuse GPU-rendered complex pages at the same scale to reduce repeated mask and transparency processing while scrolling. Very large or rotated pages retain direct rendering.
- Refresh the title bar and tab strip after the first document layout settles.

## 1.34.1 - 2026-09-28

### 개선

- Render more overlapping transparency and masked images on the GPU instead of rasterizing their regions on the CPU.
- Fix missing artwork in nested GPU transparency groups.

## 1.34.0 - 2026-09-27

### 새 기능

- Open EPS files with an installed Ghostscript interpreter. Save edited results as PDF while preserving the EPS source.
- Ghostscript is not bundled. Install it separately to use EPS files.

### 개선

- Smooth enlarged photos and bitmap images on the GPU to reduce blocky pixels.
- Remove unnecessary pixel copies before GPU upload, redundant RGBA buffers for opaque images, and repeated hashing of shared image pixels.
- Distinguish PDF, AI and EPS file icons with extension badges and separate colors.

## 1.33.12 - 2026-09-27

### 개선

- Replace app and installer icons with a paper-and-leaf Leaflet mark and match the PDF file icon color.

## 1.33.11 - 2026-09-26

### Bug fixes

- Make GitHub release URL validation tolerant of harmless API URL formatting differences.

English | [한국어](CHANGELOG.ko.md)

## 1.33.10 - 2026-09-26

### 성능 개선

- Start uncached GPU scene preparation in a separate process after the first preview has been painted.
- Reuse prepared scenes immediately in automatic and GPU modes, and persist worker results in the background.

## 1.33.9 - 2026-09-26

### 성능 개선

- Calculate whole-file GPU cache hashes in the background without blocking rendering or GPU preparation.
- Defer cache writes until hashing completes and cancel pending work when a document changes or closes.

## 1.33.8 - 2026-09-24

### 성능 개선

- Reuse immutable document snapshots during GPU preparation to avoid copying and recompressing large pages.
- Open worker input directly from disk to reduce temporary memory use.
- Export current pages separately for edited or encrypted documents to preserve rendering and isolation.

## 1.33.7 - 2026-09-24

### 개선

- Use Leaflet names for installers, executables, MSIX packages, and source release files.
- Preserve automatic updates from older versions and existing user settings.

## 1.33.6 - 2026-09-23

### Bug fixes

- Reserve space for the initial vertical scrollbar before rendering so fit-width zoom is accurate without drawing the page twice.

## 1.33.5 - 2026-09-23

### Bug fixes

- Recalculate fit-width zoom after the first render if a vertical scrollbar narrows the document viewport.

## 1.33.4 - 2026-09-23

### Improvements

- Add a small app icon beside Leaflet in the reader and editor title bars.
