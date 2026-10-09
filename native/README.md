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

ABI version 24 can:

- reuse an existing complex-page GPU raster at intermediate zoom scales without
  allocating new rasters;
- optionally retain bounded snapshots of expensive transparency/clip/mask scopes
  with their immutable backdrop across nearby display scales, refreshing above
  2× their stored scale and leaving vectors outside those scopes at the current scale;
  the original replay API preserves exact rendering for diagnostics, and this
  display-only optimization does not change PDF saving;
- asynchronously prepare exact viewport frames on a separate context of the same
  GPU device, sharing immutable resources and cloning gradient brushes;
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
Group snapshots share the existing adaptive GPU raster-cache budget and LRU
eviction. Each is capped at 64 MiB or one eighth of that budget. Visible group
portions can be stored with explicit coverage checks; panning into missing areas
refreshes them. High-zoom display rasters cover the viewport plus a 64 px margin,
and invisible scopes are skipped while refreshing. Source-over-only scopes use
vector clip/opacity layers, with fully opaque Normal wrappers omitted.
Active implicit layers, rotated pages and failed allocations retain the normal
replay path. Cache identities are weak references so closing a scene makes
all of its raster scales and group snapshots eligible for reclamation together.
Expensive display scopes are refreshed at 75% linear display density (56.25% of
the display pixel count), with cubic resampling and a single reusable scratch
bitmap. Alpha/blend order and backdrop dependencies are retained. This can soften
fine text/edges inside a cached scope; ordinary vectors outside it remain at the
display density. Allocation or coverage failures use the regular replay path.

After 90 ms of inactivity the reader queues full-density composition, then polls for
completion without waiting on the GUI thread. A multithreaded factory protects
shared resources; each context has its own target and mutable rendering state.
The worker culls invisible scopes and individual drawing commands from immutable
bounds. Blend/mask operations retain their original semantics; ordinary
source-over scopes use equivalent vector clip/opacity layers at full density.
Completed frames are admitted into the existing LRU budget and displayed only
for matching scene identity, DPI, scale/rotation and viewport coverage. A queue
holds one active job and only the newest pending request. Cancellation is checked
between commands, and closing a surface signals shutdown without joining the
worker on the GUI thread. Vsync waiting is avoided while a sharp job is pending
so presentation does not monopolize the factory lock.
Exact work uses center-prioritized 512 physical-pixel tiles with a 2 px gutter.
Each tile replays original backdrop/mask operations on a separate small target;
only its interior is copied into the bounded viewport atlas. Completed opaque
page portions replace the fast display progressively. Page edges and rotated
pages switch when the complete atlas is available, preventing repeated alpha
coverage and changes to adjacent pages.
Snapshots retain multiple scales and coverage regions; equivalent smaller
snapshots at the same scale are replaced only when the new region contains them.
Selection prefers a nearby stored scale with sufficient coverage. The cache
ceiling is 2 GiB, additionally bounded by total RAM / 16, available RAM / 8,
the DXGI local-memory budget / 4 and remaining GPU headroom / 4. Frame startup
trims expired and least-recently-used results as memory availability changes.
Sharp frames at matching DPI, scale/rotation and integer pixel phase can supply
overlapping tiles for a new viewport entirely through GPU copies. Those tiles
are omitted from the worker's replay list. Cached overlap also stays sharp while
the reader waits to queue missing tiles; translucent page edges retain the
normal completion path.
