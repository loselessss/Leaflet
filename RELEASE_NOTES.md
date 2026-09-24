# Leaflet Release Notes

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

- Add a small Leaflet icon beside the title in reader and editor windows.
- Keep fit-width zoom accurate when a vertical scrollbar appears on first display, without rendering the page twice.

## 1.33.5 - 2026-09-23

- Add a small Leaflet icon beside the title in reader and editor windows.
- Keep fit-width zoom accurate when a vertical scrollbar appears on first display.

## 1.33.4 - 2026-09-23

- Add a small app icon beside Leaflet in the reader and editor title bars.

## 1.33.3 - 2026-09-23

- Use Leaflet consistently in the interface and installer, and explain the reader and editor roles on the start page.
- Make the top, bottom and corner resize targets easier to grab in reader and editor windows.
- Speed up image-mask conversion and reuse repeated gradient-opacity calculations without changing rendered output.

- Avoid rendering the first page twice while the initial window layout settles.
- Reduce repeated UI translation work and prepare thumbnails one at a time to keep document opening responsive.

## 1.33.2 - 2026-09-23

- Reduce unnecessary native window-message processing.
- Skip delayed initial page layout after document closure or completed initialization.

## 1.33.1 - 2026-09-21

- Right-click a document tab to save, print, open its folder or close it.

- Configure language, startup, rendering and system integration in Help → Preferences.
- Put installers and their matching source files together under one release.

## 1.33.0 - 2026-09-20

- Edit fragmented text together, or drag several lines to edit a paragraph inside a box.
- Adjust box size, alignment and line spacing with a PDF output preview and overflow checks.
- Show the Leaflet name at the far left of the title bar.
- Avoid CPU fallback for harmless empty fill operations emitted by PDF generators.

## 1.32.2 - 2026-09-14

- Align the title-bar divider beneath tabs and window controls in both workspaces.
- Align update dialog buttons and show download percentages without clipping; format release-note headings.
- Fix unnecessary CPU fallback and duplicate glyphs when PDF text maps one glyph to multiple characters.

## 1.32.1 - 2026-09-13

- Installer downloads are separate from the linked source archives.
- Add preparation for MSIX packaging.

## 1.32.0 - 2026-09-12

- Edit text directly on the page with a small font, size and color palette. Apply with Enter or cancel with Esc.
- Add printable binding or folding guides with page ranges, line styles and mirrored even pages, then save as PDF.

- Reduce interface stalls while preparing complex pages for GPU display.
- Correct the status shown when GPU preparation fails.

## 1.31.1 - 2026-09-11

- Reader and editor toolbars now share the same spacing, icon sizes and button colors.
- **Cleaner editor toolbar:** Object selection, rectangle insertion and image placement now use compact icons with tooltips.
- **Consistent workspace controls:** Reader/editor switching uses the same compact visual style, and the caption divider now spans the full window width.

## 1.31.0 - 2026-09-11

- **Zoom refinement:** Reuse supported vector content while images are refreshed in the background, including in GPU-priority mode.
- **Cache continuity:** App-only updates no longer discard GPU disk caches. This rendering-format upgrade requires one initial rebuild; later rendering or document changes still invalidate incompatible caches.
- **License:** sPDF's original source code is now provided under the MIT License. Bundled third-party components retain their own licenses.

- **Object placement:** Add rectangles and images. Select an object to move it, or drag its corner handle to resize it. Dragging shows an outline preview; Esc cancels the drag.

- **Precise properties:** Enter position, width and height in millimetres in the collapsible object properties panel.
- **Continue editing:** Save the PDF and reopen it to edit sPDF-created objects again. Undo and redo follow the same order as other document edits.
- **Faster first GPU scene:** Repeated calculations and oversized image color conversion are reduced even without a saved scene cache. Some image edges may look slightly different; original PDF content and CPU rendering are unchanged.

Existing PDF artwork is not converted into editable objects. Full-content drag previews, multiple selection and text frames are not included yet. Other PDF tools may remove the editing information; changed page boxes or rewritten object streams disable re-editing of the affected objects.
