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
The build also uses the Windows SDK's x64 `fxc.exe` to compile
`d2d_renderer/mask_lerp.hlsl` into an ignored header in `native/bin`. The shader
bytecode is embedded in the DLL; runtime shader compilation is not required.

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
Composite captures retain explicit Flush/CopyFromBitmap boundaries for GPU
backdrop copies, while redundant mask-coverage and scope-ending Flush calls are
omitted. Later scratch writes follow consuming draws on that context; raw mask
inputs remain owned until the applied scope closes, within its existing
four-bitmap reservation. Diagnostic readback and EndDraw retain their submission
boundaries. A compact byte per scene command classifies replay roles up front,
avoiding repeated scope/simple/no-op hash searches for every command in each tile.
Scope ranges use packed records and a direct command-to-record index. Worker
preparation copies these contiguous arrays, omitting the four construction-only
simple/no-op sets; replay uses the existing role bytes. This reduces queueing
work on the UI thread and removes scope hash lookups without retaining pixels.
See the [scope index comparison](../docs/GPU_SCOPE_INDEX_BENCHMARK_2026-10-20.md).
Clip/mask closing can replace the three Composite effect nodes with one custom
pixel shader. It quantizes the inside and outside terms separately to preserve
the original UNORM8 intermediate rounding, then adds them. Backdrop copying,
cropped origins, transforms and submission boundaries remain the same. Failed
effect registration or creation keeps the original graph, including on worker
contexts. This does not add a rendered-result cache or change tile dimensions.
Worker refinement combines an isolated Normal group and its sole geometric clip
into one transparent source. FillGeometry draws that source through the clip with
a bitmap brush, applying group opacity without a separate coverage bitmap. The
brush uses the inverse clip transform, kept separately from the parent's restore
transform for nested captures. Antialiasing remains enabled; edge rounding can
differ slightly from the old UNORM8 mask route. The opening Flush remains before
pooled source writes. COPY parents, mask-building ancestors, non-isolated/knockout/
blended groups, noninvertible transforms and full-target rectangle bypasses retain
their general routes. The same bitmap budget, final tile grid and ABI 24 remain in
use. See the [direct clip comparison](../docs/GPU_DIRECT_CLIP_BENCHMARK_2026-10-21.md).
Scene creation also removes balanced native path/rectangle clip and opacity layers
that contain no commands, including recursively empty layers. Captured composite
and mask scopes remain intact. Invalid layer parameters keep their original error
route. Command storage is shrunk before building scope/culling indexes and worker
cloning, reducing retained CPU memory without storing any rendered results.
Exact worker replay also culls bounded batches of consecutive sibling draws and
complete scopes before walking their individual commands. Mask build/apply
transitions and unknown bounds break a batch; partial replay ranges never jump
beyond their end. The index contains only command ranges and conservative page
bounds, is rebuilt with each scene, and is cloned to its worker context. It does
not retain rendered output or change display density, backdrop dependencies,
rotation or the existing antialiasing border.
An exact four-corner rectangular clip may bypass its bitmap capture only when
its axis-aligned transformed bounds cover the entire current target plus a
two-physical-pixel antialiasing margin. The lightweight scope preserves the
parent transform and primitive blend; arbitrary paths, holes, partial coverage
and sheared transforms retain the general capture path. This removes copies
without retaining rendered results or changing the final refinement tile grid.
Zero/full non-isolated opacity avoids unnecessary interpolation, and full-opacity
blend input avoids an identity ColorMatrix. These changes apply to fresh exact
composition as well as display rendering; no additional result cache is needed.
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
