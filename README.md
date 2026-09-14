# sPDF

English | [한국어](README.ko.md)

A Windows PDF reader and editor with GPU-accelerated zooming and panning,
text editing, page organization, annotations, and offline OCR.

**Current version: 1.32.2** · Windows · English and Korean

## Download

Get the installer from the [latest release](https://github.com/loselessss/sPDF/releases/latest).

Launch **sPDF Reader** or **sPDF Editor** from the Start menu.
Use **Edit mode** in the reader or **Back to reader** in the editor to switch.
Press **F1** for the full usage guide.

## Features

- **Reading:** GPU rendering, zoom up to 800%, search, bookmarks, tabs,
  two-page view, and presentation mode.
- **Editing:** Change text, fonts, sizes, and colors. Add rectangles and images,
  then move or resize them.
- **Pages:** Reorder, rotate, crop, merge, split, and extract pages.
  Adjust page size and bleed, or add binding and folding guides.
- **Annotations:** Highlights, notes, and text watermarks.
- **OCR:** Recognize Korean and English scans locally and add searchable text.
- **Output:** Print, compress PDFs, and convert between PDFs and images.

Text editing works within existing lines or boxes; it does not reflow paragraphs,
and replacement fonts may look different. Objects added with sPDF can be edited
again after saving; existing PDF artwork is not automatically converted into objects.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O / Ctrl+S / Ctrl+P | Open / save / print |
| Ctrl+F | Find text |
| Ctrl+E | Open the editor / toggle text editing |
| Ctrl+Shift+P | Page organization |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| F1 | Help |

## Development

Built with Python, PyQt5, PyMuPDF, Direct2D, and RapidOCR.

See [source and build instructions](SOURCE_CODE.md),
[reader integration](docs/READER_INTEGRATION.md),
[Windows rendering](docs/WINDOWS_RENDERING_BACKEND.md), and
[MSIX packaging](MSIX.md).

## License

sPDF's original source code is available under the [MIT License](LICENSE).
Third-party components retain their own licenses; builds using AGPL PyMuPDF
and GPL PyQt5 are not covered by MIT alone.
See [third-party notices](LICENSES.md) and [source availability](SOURCE_CODE.md).

[Release notes](RELEASE_NOTES.md) · [Current changes](CHANGELOG.md)
