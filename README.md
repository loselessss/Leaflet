# Leaflet

English | [한국어](README.ko.md)

A Windows PDF reader and editor with GPU-accelerated zooming and panning,
text editing, page organization, annotations, and offline OCR.

**Version: 1.35.0** · Windows · English and Korean

EPS opening requires [Ghostscript](https://www.ghostscript.com/releases/gsdnld.html) installed on the PC. Leaflet converts EPS to a private PDF for viewing and editing; save the result as PDF. Ghostscript is not bundled.

## Download

[Privacy policy / 개인정보 처리방침](PRIVACY.md)

Get the installer from the [latest release](https://github.com/loselessss/Leaflet/releases/latest).

Launch **Leaflet Reader** or **Leaflet Editor** from the Start menu.
Use **Edit mode** in the reader or **Back to reader** in the editor to switch.
Press **F1** for the full usage guide.

## Features

- **Reading:** GPU rendering, zoom up to 800%, search, bookmarks, draggable tabs that detach and merge,
  two-page view, and presentation mode.
- **Editing:** Change text, fonts, sizes, and colors. Add rectangles and images,
  then move or resize them. Select existing direct PDF images to move, resize, or delete them.
- **Pages:** Reorder, rotate, crop, merge, split, and extract pages.
  Adjust page size and bleed, or add binding and folding guides.
- **Annotations:** Highlights, notes, and text watermarks.
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

| Shortcut | Action |
| --- | --- |
| Ctrl+O / Ctrl+S / Ctrl+P | Open / save / print |
| Ctrl+F | Find text |
| Ctrl+E | Open the editor / toggle text editing |
| Ctrl+Shift+P | Page organization |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Delete / Arrow keys / Shift+Arrow keys | Delete / move / move farther with an object selected on the editor canvas |
| Esc / Hold Space | Cancel a gesture or clear object selection / temporarily pan in the editor |
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
