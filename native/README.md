# sPDF Windows native renderer

This directory contains the Windows rendering boundary. On supported Windows
systems the reader loads it automatically; a missing or failed DLL falls back
to the existing Qt compositor without losing the open document.

## Build

Install Visual Studio 2022 C++ Build Tools with the Desktop C++ workload and a
Windows SDK, then run:

```bat
native\build_d2d_renderer.bat
```

Generated objects, import libraries, and PDBs under `native\bin` are not committed.
The tracked x64 `spdf_d2d_renderer.dll` must match the Python backend ABI.

## Current ABI

ABI version 20 can:

- composite non-isolated Normal groups with nested blends against a GPU backdrop,
  applying group opacity once to premultiplied pixels (group flag bit 1);
- replay retained scenes with luminosity-mask color tables prepared before drawing;

- probe a hardware D3D11 device and fall back to WARP;
- create Direct2D and DirectWrite devices on the same DXGI device;
- create a flip-model swap chain for an HWND;
- upload premultiplied BGRA bitmaps and draw them into a frame;
- apply page transforms and draw translucent selection/edit rectangles;
- create immutable line/Bézier path geometries and rasterize their fill/stroke
  directly through Direct2D;
- create transformed geometry groups and cached fill realizations for repeated
  embedded-font glyph outlines;
- push and pop nested antialiased vector-path clipping layers;
- push and pop opacity layers for supported isolated transparency groups;
- apply PDF soft-mask transfer functions through a Direct2D alpha table
  transfer effect;
- clear/present, resize, and destroy the surface and bitmap resources.

PyMuPDF still parses PDF content, extracts exact glyph outlines, and decodes
images, colored stencil masks, and bounded shading bitmaps on the CPU. Supported
page scenes, exact glyph clips, and ordinary isolated transparency groups are
rasterized or composed through Direct2D; unsupported page features keep the
bounded 512 px CPU-tile path.
Native resources are released with the tab, and page image scene data is capped
at 64 MiB before falling back.
