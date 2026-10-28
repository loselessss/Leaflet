# Leaflet

English | [한국어](README.ko.md)

A Windows PDF reader and editor with GPU-accelerated zooming and panning,
text editing, page organization, annotations, and offline OCR.

**Version: 1.37.2 (2026-10-28)** · Windows · English and Korean

EPS opening requires [Ghostscript](https://www.ghostscript.com/releases/gsdnld.html) installed on the PC. Leaflet converts EPS to a private PDF for viewing and editing; save the result as PDF. Ghostscript is not bundled.

Modified AI files are saved as PDF. The Illustrator-compatible save checkbox is on by default and removes private editing data so Illustrator uses the current PDF content. Unchecking preserves existing data but may reopen old content. This does not create AI files or retain their layer/effect editing structure.

## Download

[Privacy policy / 개인정보 처리방침](PRIVACY.md)

**For the stable version, install Leaflet from [Microsoft Store](https://apps.microsoft.com/detail/9PCB1BH4WBDT?hl=ko-kr&gl=KR&ocid=pdpshare).**

The latest standalone installer is also available from [GitHub Releases](https://github.com/loselessss/Leaflet/releases/latest).

Launch **Leaflet** or **Leaflet Editor** from the Start menu.
Use **Edit mode** in the reader or **Back to reader** in the editor to switch.
Press **F1** for the full usage guide.

## Features

- **Reading:** GPU rendering, zoom up to 800%, search, bookmarks, draggable tabs that detach and merge,
  two-page view, and presentation mode.
  Exact GPU updates plan temporary surface lifetimes and batch allocations within each tile; temporary storage has a fixed slot limit.
  Small complex isolated illustrations are compiled into bounded transparent images at the requested zoom quality; surrounding text remains vector. Illustration colors and edges can differ, so use CPU mode for a fidelity check.
  Compatible raster alpha masks are folded into their images to reduce composition and memory. Different sampling rules remain separate; filtered image edges may differ slightly.
  Completed alpha sources are released during preparation, keeping more source densities within the bounded GPU image budget.
  At high zoom, prepare only visible image regions with up to one screen of margin on each side; text and paths stay vector. New regions replace the previous detail scene in the background as you pan.
- **Editing:** Change text, fonts, sizes, and colors. Add rectangles and images,
  then move or resize them. Select existing direct PDF images to move, resize, or delete them.
  Magnetic alignment snaps moving objects to page/object edges and centers; toggle it in
  the toolbar or properties. Hold Ctrl for free movement with guides, or Shift for straight movement.
- **Pages:** Reorder, rotate, crop, merge, split, and extract pages.
  Adjust page size and bleed, or add binding and folding guides.
- **Artboards:** View multiple pages on the editor canvas, zoom and pan, or drag page labels to arrange their screen positions. Double-click a page for precise editing; PDF page order is unchanged.
- **Annotations:** Highlights and notes in the reader and editor; save into the original PDF or save a copy. Text watermarks are available in the editor.
- **OCR:** Recognize Korean and English scans locally and add searchable text.
- **Output:** Print, compress PDFs, and convert between PDFs and images.
  Save As offers optional removal of document metadata and Leaflet object re-editing information.

Click nearby fragments on the same line to edit them together, or drag a box around
several lines to edit a paragraph. Adjust box dimensions, alignment and line spacing
in the small palette, and check the PDF output preview. Use Ctrl+Enter to apply
paragraph edits; Enter inserts a line break. Overflow blocks application until corrected.

Text wraps within the selected box; it does not reflow the surrounding document,
and replacement fonts may look different. Objects added with Leaflet can be edited
again after saving. Click existing direct PDF images to select them in the editor;
images inside groups or clipping scopes and existing vector artwork are not yet editable.

## Shortcuts

Open **Annotations → Annotation Manager** (Ctrl+Shift+M) to search and manage
notes and highlights in a separate window. Close the left thumbnail/bookmark
panel directly with the X button in its header.

| Shortcut | Action |
| --- | --- |
| Ctrl+O / Ctrl+S / Ctrl+P | Open / save / print |
| Ctrl+F | Find text |
| Ctrl+E | Open the editor / toggle text editing |
| Ctrl+Shift+P | Page organization |
| Ctrl+Shift+A | Editor artboard overview / precise page editing |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Delete / Arrow keys / Shift+Arrow keys | Delete / move / move farther with an object selected on the editor canvas |
| Esc / Hold Space | Cancel a gesture or clear object selection / temporarily pan in the editor |
| Middle mouse button + drag | Pan the document horizontally and vertically without changing tools |
| F1 | Help |

## Development

Built with Python, PyQt5, PyMuPDF, Direct2D, and RapidOCR.

See [source and build instructions](SOURCE_CODE.md),
[reader integration](docs/READER_INTEGRATION.md),
[Windows rendering](docs/WINDOWS_RENDERING_BACKEND.md), and
[MSIX packaging](MSIX.md).

## License

Leaflet's original source code is available under the [MIT License](LICENSE).
Third-party components retain their own licenses; builds using AGPL PyMuPDF
and GPL PyQt5 are not covered by MIT alone.
See [third-party notices](LICENSES.md) and [source availability](SOURCE_CODE.md).

[Release notes](RELEASE_NOTES.md) · [Current changes](CHANGELOG.md)
