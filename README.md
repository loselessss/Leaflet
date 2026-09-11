# sPDF

English | [한국어](README.ko.md)

sPDF is a Windows desktop PDF reader and editor with a **GPU rendering pipeline
for fast zooming, panning, and screen updates**. It combines practical page
editing, annotations, offline OCR, and multi-document tools in one application.
Documents stay on your
computer unless you explicitly use an external link or optional model download.

**Current version: 1.31.1** · English and Korean interface · Windows

Add rectangles and images in the editor, then move or resize them using dragging
or millimetre properties. sPDF-created objects remain editable after saving and
reopening the PDF; existing artwork is not automatically converted.

Zoom quality updates reuse supported vector content while refreshing images in
the background. GPU disk caches survive app-only updates; incompatible renderer
or document changes still require rebuilding them.

## What sPDF is for

### Read and navigate comfortably

- Open regular and encrypted PDFs with nearby-page rendering that stays usable
  on long documents.
- Zoom up to 800% in the reader and editor with immediate image scaling and progressive
  sharpening of visible regions. On Windows, Direct2D caches and composites visible
  tiles when available.
- Rotate the current page view left or right using the toolbar, View menu, or
  Ctrl+[ / Ctrl+]. Reader rotation is temporary and does not change the PDF;
  rotate in the editor to save a page's orientation.
- Switch the left panel between page thumbnails, PDF bookmarks, and a hidden
  view.
- Click a precise point in a sidebar thumbnail or drag its blue viewport marker
  to move around a zoomed page. Page reordering is kept in the dedicated page
  organizer.
- Use two-page view, full screen, or presentation mode, and return to earlier
  page/zoom/scroll positions with Alt+Left and Alt+Right.
- Reopen a document where you stopped reading and Ctrl+click document or web
  links.

### Edit and organize documents

- Standalone sPDF opens in a read-only reader. Use the **Edit mode**
  button at the left of the ribbon or Ctrl+E to open an editor in a **separate OS process** with the
  current page open on the detailed editing canvas. Once the editor confirms that
  the document opened, sPDF closes that reader tab and closes the reader process
  when it was the last tab. A failed or timed-out open leaves the reader unchanged.
- Choose **Help → Startup workspace → Reader first** (default) or **Editor first**
  for the next launch. The editor's **File → Open reader** checks unsaved work,
  hands the document to a reader, and then closes the source editor tab.
- The two processes overlap only until the destination confirms a successful open.
  If an editor later exits or crashes, reopen the file in a reader; independent
  recovery checkpoints remain available for unsaved editing work.
- Each workspace reads a private disk copy. Saves complete and validate a temporary
  PDF before backing up and replacing the destination. Only a completed-save
  notification refreshes readers. Failed refreshes, timeouts, or an editor stopping
  just after replacement but before notification leave the last good reader copy open.
- If another editor saved the source first, Save As preserves both versions instead
  of overwriting the newer file. Another application's file lock may prevent saving,
  but pending edits and independent recovery checkpoints stay intact.
- Each workspace needs temporary disk space roughly equal to the input size. A
  forced exit can leave temporary copies for OS temp cleanup; these are separate
  from recovery checkpoints. The small `.spdf-save.lock` file may remain normally;
  its OS lock is released when the writer exits. Automatic refresh covers connected
  workspaces; reopen the document after reconnecting or starting a new reader session.
- **Page Organization** or Ctrl+Shift+P opens a separate thumbnail grid for
  reordering pages. Double-click a page or choose Edit selected page to return
  to detailed editing. Unsaved changes and undo/redo history stay intact, and
  only visible and nearby thumbnails are rendered. The detail view shows the
  current page's original size in millimetres on the bottom status bar.
- Standalone document tabs sit in the title bar and show **[Read/GPU]** or **[Edit/CPU]**.
  Labels track page rasterization, not GPU composition of CPU tiles; mixed rasterization
  is shown as **CPU+GPU**. Presentation and full-screen
  controls stay in the reader; they are not offered in standalone editor windows.
- Change text content, font size, and color in the editor. Page organization,
  annotations, and manual OCR are available there; text editing has its own
  toolbar button.
- In editor mode, adjust the current page canvas size, set page bleed boxes,
  and resize editable text elements from the context menu.
- Select, search, and copy text; add highlights and notes.
- Correct text in ordinary or OCR-processed PDFs with undo and redo.
- Rotate, delete, reorder, insert, merge, split, and extract pages.
- Add, rename, delete, reorder, and nest PDF bookmarks.
- Import a bookmark outline from a plain-text file, including nested entries.
- Crop visible page margins by dragging a preview, for one page, a range, or the
  whole document.
- Add text watermarks to selected pages and convert images to PDF or PDF pages
  to PNG/JPEG.
- Use one print window for preview, printer selection, portrait/landscape/auto
  orientation, copies, all/current/range pages, reverse order, and one-sided or
  two-sided output.
- Reduce file size with lossless, balanced, or strong compression presets.

### Work with scanned documents

- Run Korean and English OCR locally with RapidOCR; no network connection is
  required for the default engine.
- Add a searchable, selectable text layer to scanned PDFs and edit recognized
  text using its page coordinates.
- Optionally install PaddleOCR-VL for difficult pages that benefit from a
  heavier OCR model.

### Keep a practical desktop workflow

- Open multiple documents in tabs and drag saved or unsaved tabs between sPDF
  windows with the same mode. Reader and editor tabs stay separate.
- Use favorites and recent files, thumbnail position markers, fit-page and
  fit-width controls, and hand/text-selection tools.
- Recover unsaved edits after an interrupted standalone session from a separate
  copy, without automatically overwriting the original.
- Open PDF-compatible Adobe Illustrator (`.ai`) files and export edits as PDF so
  the Illustrator source is preserved.
- Use the interface, help, installer, update notice, and release notes in English
  or Korean.

## Get sPDF

Download the Windows installer from the
[latest GitHub release](https://github.com/loselessss/sPDF/releases/latest).
The installer can add sPDF to the current user's **Open with** list, but it does
not silently force sPDF as the Windows default PDF application.
It adds separate **sPDF Reader** and **sPDF Editor** Start menu shortcuts. Reader
and Editor desktop shortcuts can be selected independently during installation;
both use the same installed application and start in the named workspace.

In sPDF, **Help → Default PDF App / Browser Settings** shows the current Windows
association and offers per-user options for Edge, Chrome, and Firefox to pass PDF
links to the Windows default PDF application.

sPDF checks for updates at most once every 24 hours. You can also check manually
from **Help → Check for Updates**. Downloaded installers are accepted only when
their release version and SHA-256 digest match.

## Useful shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O / Ctrl+S / Ctrl+P | Open, save, or print |
| Ctrl+F | Find text |
| Ctrl+E | Open the editor from a reader; toggle text editing in an editor |
| Ctrl+Shift+P | Open the separate Page Organization window |
| Ctrl+Z / Ctrl+Y | Undo or redo |
| Ctrl+B | Bookmark the current page |
| Alt+Left / Alt+Right | Previous or next view |
| Ctrl+R / Ctrl+Shift+R | OCR current page or whole document |
| F5 / F11 | Presentation or full-screen mode in the reader |

Press **F1** in the application for the complete localized guide.

## Important behavior

- Text editing replaces content within the original line or box. It is not a
  full text-reflow editor, and replacement fonts can look different.
- Standalone reader and editor workspaces use viewport-sized Direct2D surfaces on
  supported Windows systems, with Qt/OpenGL and CPU display fallback. Supported
  pages rasterize vectors and exact glyph outlines through Direct2D and compose
  decoded images there. Nested vector and text clipping, colored stencil images,
  ordinary isolated transparency groups, soft and image clip masks, and complex
  stroke styles, stroked text, and stroked clipping paths are supported.
  Isolated groups can use all 15 standard non-Normal PDF blend modes, including
  Soft Light, Multiply, Screen, Overlay, Hue, Saturation, Color, and Luminosity,
  through GPU effects, including groups inside nested geometry/text clips.
  Blends and geometry clips inside alpha/luminosity and image masks are also
  supported. Luminosity uses a cached GPU color table calibrated to MuPDF's
  soft-mask color conversion. Non-isolated/knockout groups and mask transfer
  functions still use the CPU fallback. Shadings are rendered into
  a bounded high-quality image and then composed by Direct2D. Non-uniformly
  transformed stroked text and other unsupported effects retain the complete
  PyMuPDF path, so this is not yet a GPU-only PDF engine. Blend scratch buffers
  are viewport-sized and bounded to a 256 MiB reservation per surface.
  The embedded display path is unchanged.
- Reader and editor previews cover only the current one or two pages. Detailed
  tiles use a 64 MiB cache per tab; this is not a limit on total application memory.
- Margin cropping changes the visible page area; it does not erase the hidden
  content. Crop and bookmark changes support undo/redo.
- TXT bookmark import accepts `1 | Introduction`, `Introduction | 1`, or
  `1 Introduction`; indent a child entry with two spaces or one tab.
- Two-sided output still requires a duplex-capable printer and driver.
- Recovery copies refresh every 30 seconds while edits are pending. Protected
  PDFs and copies over 512 MB are excluded, and recovered documents use
  **Save As** first. Recovery complements normal saving; it does not replace it.
- PDF-compatible `.ai` files can be read because they contain a PDF
  representation. Saving edits creates a PDF instead of overwriting the
  Illustrator source.

## For developers

### License and source code

sPDF's original source code is licensed under the **MIT License**, without warranty.
Redistribution and modification are permitted under [LICENSE](LICENSE).
[Third-party notices and licensing scope](LICENSES.md) preserve each dependency's
terms. Builds using the AGPL edition of PyMuPDF and GPL edition of PyQt5 are not
distributed under MIT terms alone.
Get version-matched application sources and dependency-source directions from
the same release page as the installer. See [SOURCE_CODE.md](SOURCE_CODE.md)
for details, including build instructions. License texts are also available
offline in **Help → Open-source Licenses**.

sPDF is built with Python, PyQt5, PyMuPDF, and a small Windows Direct2D renderer.
RapidOCR runs in a separate worker process so its runtime is loaded only when OCR
is requested.

Set `SPDF_DISABLE_GPU=1` before launching to troubleshoot using the CPU display
path. Visible-region tile rendering and immediate zoom remain available.
Standalone users can also choose **Auto**, **GPU (Direct2D)**, or **CPU
(PyMuPDF)** in the display-renderer menu; restart sPDF after changing it. The
document window title shows the active `[GPU]` or `[CPU]` path, and the GPU
choice is disabled when Direct2D hardware rendering is unavailable.
Enable **Rendering diagnostics** in the same menu to label the current page as
CPU rendering, GPU rendering, CPU+GPU rendering, or CPU display while a GPU scene
is prepared in the background. Its tooltip explains the current state and scene contents.

```bash
pip install PyQt5 PyMuPDF rapidocr onnxruntime
python run.py
python run.py document.pdf
```

Use `run.pyw` to launch without a console. Windows packages are built with
`build_exe.bat` followed by `build_installer.bat`.

### Embedding as a read-only viewer

With the host's `QApplication` running, choose the mode when opening a window:

```python
from pdfeditor.app import new_window

viewer = new_window("document.pdf", read_only=True)   # reading only
annotator = new_window("document.pdf", read_only=True,
                       annotations_enabled=True, autosave_annotations=True)
```

`AppWindow` accepts the same options. Read-only mode retains zoom, navigation,
search, text selection/copy, existing notes and printing, while blocking body
editing, OCR and page/bookmark changes. `annotations_enabled=True` additionally
allows notes/highlights and their undo/redo. In this mode, annotations are saved
beside the PDF in `document.pdf.spdf-annotations.json`, never into the original.
Disable `autosave_annotations` to save explicitly with Ctrl+S. Ctrl+Shift+S exports
a separate annotated PDF. Move the sidecar together with the source PDF.

New windows inherit all options; windows with different options are not reused
and cannot exchange tabs. Options are fixed for each window. Embedded windows
do not enable sPDF's self-updater. See the [reader API guide](docs/READER_INTEGRATION.md)
for reader options, saving, conflict handling and protected-PDF limitations.

The Qt-independent `Document(path, read_only=True)` also rejects body writes
with `PermissionError`. This is an application feature switch, not DRM or a
filesystem permission: copying and printing remain available.

See [CHANGELOG.md](CHANGELOG.md) for release history, [PLAN.md](PLAN.md) for
design history and enduring constraints, and [LICENSES.md](LICENSES.md) for
open-source notices.
