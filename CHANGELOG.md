# Changelog

English | [한국어](CHANGELOG.ko.md)

## 1.30.0 - 2026-09-05

### New features

- GPU scenes are cached on disk within a shared 100 MiB budget and reused when reopening unchanged documents at the same rendering scale.
- Least recently used scenes are removed automatically. Changed documents and renderer versions invalidate cached scenes; protected documents and edited content are excluded.
