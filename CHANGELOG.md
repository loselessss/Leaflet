# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.31.0 - 2026-09-11

### New features

- Add rectangles and images, then drag to move or resize them with an outline preview.
- Enter position and dimensions in millimetres in the collapsible properties panel.
- Save and reopen sPDF-created objects in PDF files, with undo/redo shared with existing edits. Existing artwork is not automatically converted into editable objects.

### Other

- License sPDF's original source code under the MIT License. Bundled third-party components retain their own licenses.

### Performance improvements

- Refine image quality after zooming without re-extracting supported vector content. GPU-priority mode also prepares the replacement in the background.
- Keep GPU disk caches across app-only updates; rendering-format, ABI, engine or document changes still invalidate them.

- Prepare GPU scenes faster on first use by reusing repeated geometry and gradient calculations within each extraction.
- Reduce opaque Gray/CMYK images to display resolution before color conversion. Image edges may differ slightly; original PDF content and CPU rendering remain unchanged.
