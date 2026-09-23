# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.33.3 - 2026-09-23

### Improvements

- Use Leaflet consistently in the interface and installer, and explain the reader and editor roles on the start page.
- Make the top, bottom and corner resize targets easier to grab in reader and editor windows.
- Speed up image-mask conversion and reuse repeated gradient-opacity calculations without changing rendered output.
- Avoid rendering the first page twice while the initial window layout settles.
- Reduce repeated UI translation work and prepare thumbnails one at a time to keep document opening responsive.
