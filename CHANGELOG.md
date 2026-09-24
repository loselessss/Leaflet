# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.33.8 - 2026-09-24

### 성능 개선

- Reuse immutable document snapshots during GPU preparation to avoid copying and recompressing large pages.
- Open worker input directly from disk to reduce temporary memory use.
- Export current pages separately for edited or encrypted documents to preserve rendering and isolation.

## 1.33.7 - 2026-09-24

### 개선

- Use Leaflet names for installers, executables, MSIX packages, and source release files.
- Preserve automatic updates from older versions and existing user settings.

## 1.33.6 - 2026-09-23

### Bug fixes

- Reserve space for the initial vertical scrollbar before rendering so fit-width zoom is accurate without drawing the page twice.

## 1.33.5 - 2026-09-23

### Bug fixes

- Recalculate fit-width zoom after the first render if a vertical scrollbar narrows the document viewport.

## 1.33.4 - 2026-09-23

### Improvements

- Add a small app icon beside Leaflet in the reader and editor title bars.
