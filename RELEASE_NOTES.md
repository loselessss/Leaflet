# sPDF Release Notes

## 1.30.2 - 2026-09-09

- **Editor workspace:** A visible Back to reader button checks unsaved changes before switching modes. The lighter command bar groups essential tools and labels text editing and page organization.

- **GPU acceleration:** On supported systems, PDF text, shapes and images are drawn on the GPU for improved zooming, panning and screen updates. CPU rendering keeps pages visible while the GPU prepares or handles unsupported content.
- **Faster reopening:** A new disk cache reuses prepared content. Choose its maximum size or turn it off in settings.
- **Display improvements:** Windows scaling, including 150%, is now supported correctly, and the zoom percentage display has been fixed.
- **Separate reader and editor:** The two modes run in separate processes and hand off your document when switching modes.
