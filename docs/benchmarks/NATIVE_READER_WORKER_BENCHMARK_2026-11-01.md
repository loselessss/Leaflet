# Independent Rust reader worker — 2026-11-01

The reader now uses `leaflet-gpu-scene-worker.exe` for background GPU scene jobs.
This replaces the Python **control worker**, whose compiler was already Rust.
The Qt window, CPU preview and parent scheduling remain in Python. Editing and
OCR were not changed.

## Path and ownership

1. The parent retains its existing immutable private PDF input, page index,
   generation and cancellation deadline. Authenticated encrypted pages are
   exported privately by the parent, and do not receive persistent cache keys.
2. The executable checks the existing SQLite cache for a compatible LFDC v1
   scene. A hit does not load MuPDF or open the PDF again.
3. On a miss, the exact-version MuPDF bridge opens the PDF and retains the page
   and SDK resources on the caller thread. Rust plans raster regions and compiles
   the native event stream directly into its owned scene.
4. The worker serializes LFSC v2, releases the owned scene, compresses independent
   blocks and writes an atomic LFSW v1 result. The parent validates the bounded
   frame and restores the same `VectorPage` before the existing native GPU upload.

MuPDF objects never cross Rust worker threads. SDK buffers and DLL lifetimes use
RAII; native FFI, Windows SQLite and SHA-256 calls are confined to the executable
modules. Bounded decoding, command/image/packet budgets and CPU fallback remain.
The SQLite schema, LRU timestamps and cache key generation are interoperable with
the Python cache. No additional cache or rendered-page retention was introduced.

## Build and protocol

`python native/build_path_packer.py` builds both the ABI3 extension and independent
executable using separate Cargo targets. The executable uses
`--no-default-features --features worker`; PyO3 is optional and absent from this
build. Its PE imports contain no Python runtime. Existing locked Rust dependencies
are reused; Windows supplies `winsqlite3.dll` and BCrypt.

`packaging/spdf.spec` requires the executable and places it in `native/`. Runtime arguments
identify the bundled bridge, exact matching MuPDF DLL/version and cache budget.
MSVC runtime DLLs required by the worker/bridge/MuPDF are copied beside the
executable, so startup does not depend on Python/Qt DLL-directory setup or a
machine-wide C++ runtime installation.
The Python worker remains available for development comparisons through
`SPDF_GPU_SCENE_WORKER=python`, and when a development executable is missing.

LFSW v1 consists of the eight-byte magic `LFSW\x01\0\0\0` followed by
`<IdI4dQ`: status, raster scale, viewport flag, viewport coordinates and payload
length. Successful payloads use LFDC v1; failures contain bounded UTF-8 text.
Trailing bytes, invalid scales/viewports and oversized/truncated payloads are
rejected. Legacy private Python worker IPC stays readable. Persistent caches do
not use pickle.

## Measurement method

`tests/benchmark_native_scene_worker.py` alternates five fresh processes per
document, mode and cache condition (40 worker launches). The baseline calls the
current Python control worker and the same Rust compiler; the new mode calls the
independent executable. Both use identical PDFs, scale 1 and scene policies.

Reported preparation time includes process launch, imports/DLL loading, PDF
opening or cache lookup, compilation when needed, result writing and parent
decoding. It excludes the parent's immutable-input preparation, GUI scheduling,
GPU upload and drawing. This is not total document-open latency. Filesystem
caches are not flushed. A cache miss means no persistent scene key, not a cold
operating-system file cache.

Worker memory is peak working set, not total application/GPU memory. Python
self-reports from its real interpreter after the job, avoiding the small Windows
virtual-environment launcher; native memory is sampled through the worker process
handle. The baseline has only a small ctypes measurement tail after its job.

## Results

Medians of five fresh worker processes per cell, milliseconds; scale 1, page 0.
The persistent-scene misses and hits are separate conditions.

| Document / condition | Python control worker | Independent Rust worker | Reduction |
| --- | ---: | ---: | ---: |
| ACB 2015, compile on miss | 1303.96 ms | 923.45 ms | 29.2% |
| ACB 2019, compile on miss | 1539.87 ms | 992.03 ms | 35.6% |
| ACB 2015, persistent-scene hit | 705.07 ms | 108.23 ms | 84.6% |
| ACB 2019, persistent-scene hit | 815.21 ms | 157.13 ms | 80.7% |

| Document / condition | Python peak working set | Rust peak working set | Reduction |
| --- | ---: | ---: | ---: |
| ACB 2015, compile on miss | 105.52 MiB | 61.01 MiB | 42.2% |
| ACB 2019, compile on miss | 137.21 MiB | 83.47 MiB | 39.2% |
| ACB 2015, persistent-scene hit | 65.80 MiB | 14.60 MiB | 77.8% |
| ACB 2019, persistent-scene hit | 71.12 MiB | 28.31 MiB | 60.2% |

The benefit comes from avoiding interpreter/module startup and intermediate
Python buffers, and from forwarding a compatible cache hit without opening the
PDF. The compiler policy and rendered density are unchanged. Scene misses show
an improvement without reusing a previously compiled scene. This does not imply
that the GPU drawing itself became 29–36% faster.

## Verification

- Native versus Python-control compiled scenes are equal for both posters in
  every benchmark sample.
- `tests/audit_scene_cache_gpu.py --native-worker` compares completed GPU frames
  for both posters at fit and 800%, in addition to exact scene equality.
- Native tests cover gradients, masks, blend/knockout nesting, Unicode paths,
  rotated/cropped pages, clipped 800% viewports, encrypted input rejection,
  authenticated snapshots after document close, timeout, cache corruption,
  interoperability in both directions, cache eviction and disabled caching.
- An isolated copy of the installed native/MuPDF folder layout compiles a PDF
  with only the Windows system directory on PATH and no Python import path.
- The existing reader lifecycle tests continue to cover stale results, page
  generation, cancellation, prefetch and CPU fallback.

ACB 2015 and 2019 produced **zero changed channels and maximum difference 0** at
both fit and 800%. The packet comparisons include every byte. The full regression
modules plus the added packaging cases passed (783 distinct tests); the native
worker group has ten tests. A too-small cache test budget was corrected to leave
room for SQLite's own pages, then that group and all remaining modules were run.

Raw measurements and GPU audit output are kept locally under `tmp/rust-audit/`;
private PDFs and generated executables are excluded from source changes.
