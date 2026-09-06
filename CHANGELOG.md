# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.30.1 - 2026-09-06

### Improvements

- Disk caches store ordinary images as references to the original PDF instead of decoded pixels; drawing commands and expensive composition bitmaps are retained.
- Choose Off, 50, 100, 250 or 500 MB under rendering settings. Reducing the limit removes old entries immediately.

- Faster image preparation preserves the exact color and alpha values. Repeated images share GPU uploads, and the scene memory budget now includes vector and glyph commands.
- In automatic mode, higher-resolution image scenes are prepared in a separate process while the current view stays visible.
