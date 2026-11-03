# Development runtime


Built with Python, PyQt5, PyMuPDF, Direct2D, and RapidOCR.

`run.py` and `run.pyw` select the repository's `.venv` interpreter, when present,
before importing GUI/native modules. This prevents Windows' default Python from
loading a different MuPDF version than the native bridge was built against.
Without a local `.venv`, build native modules against the explicitly selected Python's SDK.
Packaged and embedded launches retain their own runtimes.

`run.pyw` opens a fresh development process without a console or tray forwarding/residency.
Closing its last window exits; saved tray preferences stay unchanged. Use
`run.py --no-resident` for the same behavior with a console.

See [source and build instructions](../../SOURCE_CODE.md),
[reader integration](../architecture/READER_INTEGRATION.md),
[Windows rendering](../architecture/WINDOWS_RENDERING_BACKEND.md), and
[MSIX packaging](MSIX.md).
