# Dependency updates / 라이브러리 업데이트

The verified build versions are pinned in [`requirements-build.txt`](../../requirements-build.txt).
Run `python -m tools.ci.run_tests` with output redirected to a file; inspect failing
cases only. After library changes, verify a packaged GPU page and actual OCR,
and compare installation size. Preserve the independent OCR DLL directory.

2026-11-04 update: Pillow 13.0.0, NumPy 2.5.4, ONNX Runtime 1.31.1,
RapidOCR 3.10.0, PyInstaller 6.22.3, hooks 2026.9, PyQt5-sip 12.20.0,
certifi 2026.10.23 and setuptools 84.2.1. Local pip is updated to 26.3.

PyQt5 5.15.11 and OpenCV headless 5.0.0.93 are already current.
PyMuPDF is upgraded to 2.1 (MuPDF 1.28.6), with pymupdf_layout 2.1 and
pymupdf4llm 2.1. Rebuild `native/build_mupdf_path.py` whenever the MuPDF SDK
changes; do not reuse a bridge compiled for 1.28.2.

Reading-order copy invokes a one-shot headless layout process. Ordinary PDF
viewing does not import the AI model or ONNX Runtime. The worker reuses the
OCR package's ONNX Runtime, uses two inference threads with idle spinning
disabled, and exits after each request. Only the three default ONNX models
(about 13.6 MiB) and their configuration are packaged; unused model variants
are omitted. There is no network service or model download for layout.

RapidOCR 3.10.0 directly depends on headless OpenCV. Earlier releases requested
regular OpenCV, so build scripts still remove any leftover regular wheel and
restore the pinned headless wheel. Both distributions own `cv2`; do not retain
both in one environment. `pip check` passes with the updated versions.

Packaged validation passed with a cold Korean OCR model cache, actual Korean
recognition and the GPU worker. Before the PDF 2.1 migration, installation payload was about 358 MiB (about
5 MiB more than before dependency updates; about 54 MiB below the original
412 MiB). Preserve Python SSL trust-policy sidecar data when the build runtime
references it: missing data prevented SSLContext creation in local frozen builds.
`runtime_ssl_datas()` copies this file without changing certificate verification.


### Frozen layout worker

Copy `pymupdf/layout` Python sources and model data without importing the
package during GUI dependency analysis. Otherwise PyInstaller's inspection
process imports both Qt and ORT and can crash. Collect `pymupdf.features`
explicitly, including its `_features` extension.

`tools/build/rth_headless_workers.py` runs before the standard Qt runtime hook.
For headless PDF/OCR/GPU jobs it suppresses embedded qt.conf initialization,
which otherwise imports QtCore before the application's entry-point branches.
Normal GUI initialization keeps the standard hook. The layout worker rejects
an unexpectedly loaded QtCore rather than loading ORT into that process.

Final 1.38.0 validation: 844 tests; packaged ACB 2015/2019 GPU scenes at fit
and 800%; layout copy without dropped/duplicated words; mixed Korean/English/
digits OCR; ordinary GUI startup without ORT. Final uncompressed GUI + OCR
payload is 373.4 MiB. This is approximately 15.5 MiB above the pre-layout
updated package and 39 MiB below the original 412 MiB installation payload.
