# Leaflet Repository Guide

## Project overview

- sPDF is a Windows desktop PDF editor built with Python, PyQt5, and PyMuPDF.
- The user interface is Korean-first. Preserve the existing Korean UI unless localization is explicitly requested.
- `run.py` is the console development entry point; `run.pyw` launches without a console.
- Application code lives in `pdfeditor/`. Keep `app.py` focused on `MainWindow` composition and place feature behavior in the existing mixin/module that owns it.
- OCR runs out of process. Preserve the separation between the GUI process, `ocr_worker_main.py`, and `pdfeditor/ocr_subprocess.py`.
- sPDF is an independent project. Keep its feature plans, documentation and implementation focused on its own reader and editor; do not describe other applications as companion components of sPDF.
- External applications may reuse the sPDF reader API. Document only the sPDF-side API contract; their features, settings, release plans and source changes are outside this repository's task scope. Do not import external application modules into the sPDF entry point or mix their settings with `~/.spdf.json`.

## Embedded-module integration

- When another program imports sPDF as an internal module, create its window with `pdfeditor.app.new_window(path)` or `AppWindow()` and leave `updates_enabled` at its default. Embedded mode must not create the GitHub update service, schedule automatic update checks, or expose the update menu.
- Only the standalone sPDF entry point (`pdfeditor.__main__`, including the installed executable, `run.py`, and `run.pyw`) may pass `updates_enabled=True`.
- New windows created from an existing window must inherit that window's update mode. Do not re-enable sPDF self-updates from a host application's embedded window.
- Keep the embedded-mode behavior covered by `tests/test_embedded_mode.py` whenever startup, menus, window creation, or update handling changes.

## Design constraints

- PDF text editing replaces content within the original line or box; it is not a full reflow editor. Preserve this limitation and avoid promising layout-perfect font reproduction.
- Scanned-document editing depends on OCR coordinates and background cleanup. Keep searchable text-layer behavior intact when changing OCR or editing code.
- Keep the default RapidOCR path usable offline. Treat PaddleOCR-VL as an optional, heavier engine and do not make it a mandatory startup dependency.
- Keep expensive OCR/model imports out of the Qt GUI process when possible so startup and failure isolation remain predictable.
- Preserve undo/redo as replayable document operations based on the original document state. New editing and page operations must participate in the existing undo/redo model.
- Save through a temporary/new file and replace the destination only after a successful write. Do not introduce direct writes that can corrupt the original PDF on failure.
- Respect encrypted-PDF restrictions and existing password handling; do not bypass edit limitations silently.
- Keep rendering memory bounded for large PDFs. Avoid eager rendering or caching every page; follow the nearby-page/thumbnail caching approach.
- File-type registration must remain per-user and must not silently force sPDF as the Windows default PDF application.

## Versioning

- The application version is defined by `APP_VERSION` in `pdfeditor/meta.py`.
- The installer version is defined by `MyAppVersion` in `installer.iss`.
- Follow semantic versioning without waiting for a separate request: use a patch release for fixes and improvements to an existing feature, a minor release for a distinct backward-compatible feature, and a major release only for an intentional compatibility break.
- For every user-visible change, update `CHANGELOG.md` in the same change. Keep the newest release first and use Korean section labels such as `새 기능`, `개선`, `성능 개선`, `버그 수정`, and `기타`, omitting empty sections.
- Whenever the release version changes, update `pdfeditor/meta.py` (`APP_VERSION` and `RELEASE_DATE`), `installer.iss` (`MyAppVersion`), the README release/status entry, and `CHANGELOG.md` together. Search the repository for the previous version before committing and verify that every release reference is intentional.
- Verify that the application and installer versions match exactly.
- Installer output names use `Leaflet_Setup_{#MyAppVersion}`. Publish a matching `sPDF_Setup_VERSION.exe` compatibility alias so older installed versions can update.

## Development and verification

- Prefer focused changes that follow the current module boundaries.
- Treat `README.md` as the current feature/status reference and `PLAN.md` as design history plus enduring constraints. When they conflict, verify against the current code and favor the newer implemented behavior.
- Run syntax/import checks or the most relevant available tests for changed Python modules.
- For a version-only change, verify both version constants and run `git diff --check`.
- Launch the development build with `python run.py` when GUI verification is needed and dependencies are installed.
- Do not treat generated files under `build/`, `dist/`, or `Output/` as source changes.

## Windows builds

- Run `build_exe.bat` first. It generates icons and builds the application with PyInstaller.
- Run `build_installer.bat` only after the executable and OCR worker outputs exist.
- Installer generation requires Inno Setup 6 at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.
- Do not delete or overwrite existing build outputs unless the requested build workflow requires it.

## Git hygiene

- Preserve unrelated local changes.
- Stage only files that belong to the requested change.
- Do not commit or push unless the user asks for it explicitly.
- Before committing, inspect the staged diff and run the relevant verification commands.
