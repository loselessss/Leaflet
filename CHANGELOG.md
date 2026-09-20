# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.33.0 - 2026-09-20

### 새 기능 / New features

- Edit nearby text fragments together and drag several lines into a paragraph editing box.
- Adjust box dimensions, alignment and line spacing, with a PDF output preview and overflow checks.
- Ask before unifying mixed formatting; support undo, redo and saving paragraph edits.
- Keep the Leaflet name visible at the far left of the custom title bar.

### Bug fixes

- Keep PDF-generator move-only fill operations from forcing an otherwise supported page to CPU rendering.

## 1.32.2 - 2026-09-14

### Improvements

- Remove the offset tab baseline so the title-bar divider stays level beneath the window controls in both workspaces.
- Align update dialog buttons and show download percentages without clipping; format release-note headings.
- Fix unnecessary CPU fallback and duplicate glyphs when PDF text maps one glyph to multiple characters.
