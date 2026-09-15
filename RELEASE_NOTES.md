# sPDF Release Notes

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
