# Leaflet

English | [한국어](README.ko.md)

A Windows PDF reader and editor with GPU-accelerated zooming and panning,
annotations, page organization, text editing, and offline Korean/English OCR.

**Version: 1.38.0 (2026-11-05)** · Windows · English and Korean

## Download

**Get the stable version from [Microsoft Store](https://apps.microsoft.com/detail/9PCB1BH4WBDT).**

Standalone installers are available from [GitHub Releases](https://github.com/loselessss/Leaflet/releases/latest).
See [release notes](docs/releases/RELEASE_NOTES.md) for recent improvements.

## What you can do

- **Read:** Zoom up to 3200%, pan smoothly, search, use bookmarks and two-page view, and detach tabs into separate windows.
- **Appearance:** Follow Windows light or dark mode while preserving the PDF's original colors.
- **Copy in reading order:** Press Ctrl+Shift+C to analyze the selected text or current page locally. Model memory is released after each job.
- **Annotate:** Highlight text, add notes, and manage annotations in one window.
- **Edit:** Change text and add or adjust images and shapes.
- **Organize:** Reorder, rotate, crop, merge, split, and extract pages.
- **Recognize scans:** Add searchable Korean and English text with local OCR.
- **Export:** Print, compress PDFs, and convert between PDFs and images.

Launch **Leaflet** or **Leaflet Editor** from the Start menu. Switch with
**Edit → Open in editor** (Ctrl+E) or **Back to reader**, and press **F1** for help.

Text editing works within the selected line or box; replacement fonts may look different.
Some complex illustrations may look slightly different in GPU mode. Use CPU mode for an exact appearance check.
For editing details, shortcuts, and AI/EPS support, see the [usage guide](docs/usage/GUIDE.md).

## Documentation and development

| Looking for | Start here |
| --- | --- |
| All documentation | [Documentation index](docs/README.md) |
| Build and source availability | [Source and build guide](SOURCE_CODE.md) |
| Development launch and tests | [Developer guide](docs/development/README.md) |
| Reader API | [Reader integration](docs/architecture/READER_INTEGRATION.md) |
| Current work and history | [Changelog](docs/releases/CHANGELOG.md) |

Application code is in `pdfeditor/`, native rendering code in `native/`, developer
tools in `tools/`, and packaging configuration in `packaging/`.
Run the development app with `python run.py` or `python run.pyw` after setup.

## License and privacy

Leaflet's original code uses the [MIT License](LICENSE). Third-party components
retain their own terms; builds using AGPL PyMuPDF and GPL PyQt5 are subject to those terms.
See [third-party notices](LICENSES.md), [source availability](SOURCE_CODE.md), and the [privacy policy](PRIVACY.md).
