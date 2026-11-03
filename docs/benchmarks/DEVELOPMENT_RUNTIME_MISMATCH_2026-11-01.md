# Development launcher / native MuPDF mismatch

## Reproduced cause

ACB 2019 reported `unsupported Rust GPU scene: native MuPDF version mismatch`.
The test and user launch environments were different:

| Launch environment | Python | MuPDF |
| --- | --- | --- |
| Repository `.venv`, previously used by tests | 3.12 | 1.28.2 |
| Windows default Python | 3.14 | 1.29.0 |
| Compiled native MuPDF bridge | — | 1.28.2 |

Starting the independent worker with the default Python's SDK reproduced the
failure on the actual poster. It now reports the versions explicitly:
`native MuPDF version mismatch (bridge=1.28.2, runtime=1.29.0)`.
The mismatch guard remains strict; disabling it would allow incompatible SDK
layouts and must not be used as a fix.

Previous tests exercised PDF compilation and rendering with the repository
interpreter, so all participants used MuPDF 1.28.2. They did not exercise a source
entry point started from another Python. Passing those tests did not validate
the Windows file-association launch environment. Tray forwarding was a separate
possible source of stale processes, not an established cause of this mismatch.

## Fix

`run.py` and `run.pyw` call the standard-library-only
`pdfeditor.dev_startup.ensure_project_environment` before importing GUI/native
code. If the current interpreter is outside the local `.venv`, the launcher
starts that environment's Python/Pythonw with the original arguments, ignores
external Python environment variables and user-site packages, and exits the
bootstrap. Source checkouts without a local venv keep their explicitly selected
interpreter. Frozen executables and embedded API imports do not select a source
venv. Native binaries must still be rebuilt if that environment's SDK changes.

`run.pyw` continues to disable tray forwarding and residency. The bootstrap does
not change saved tray preferences or the user's Python installation.

## Regression evidence

- `tests/test_dev_startup.py` copies the actual source entry scripts into a
  fixture with its own real venv. An external interpreter launches those scripts
  in a Unicode/space-containing path. The child records its actual executable,
  prefix, original arguments, isolation flags and tray policy. Startup and
  interpreter selection are not mocked. The fake GUI ensures no GUI/native
  module was imported before environment selection.
- The same module checks already-selected environments, missing local venvs and
  frozen executables. It detects removal of the bootstrap from either entry.
- `test_native_scene_worker` passes a mismatched runtime version to the real
  executable and verifies both version values are returned before any PDF is
  opened. Existing real PDF and GPU tests retain the matching-version route.
- A local end-to-end probe started from the actual Windows Python 3.14,
  switched into the repository's Pythonw 3.12, ran the real GUI entry point and
  confirmed ACB 2019 reached a completed `GPU` frame with MuPDF 1.28.2.
- 163 focused startup, embedded-mode, reader, native-input, worker and release
  note tests passed. Private input PDFs and local probe outputs remain outside
  source control under `tmp/rust-audit/`.
