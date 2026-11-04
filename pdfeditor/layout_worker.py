"""One-shot, headless layout analysis. Exit releases all model memory."""
import json
import os
from pathlib import Path
import sys


def configure_runtime():
    if "PyQt5.QtCore" in sys.modules:
        raise RuntimeError("Layout analysis must run without Qt")
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).parent
        for directory in (executable / "ocr" / "_internal",
                          executable.parent / "Leaflet-ocr" / "_internal"):
            if (directory / "onnxruntime" / "__init__.py").is_file():
                # Reuse the separately packaged runtime, without importing Qt.
                sys.path.append(str(directory))
                break
        else:
            raise RuntimeError("The OCR runtime directory is missing")
    os.environ["OMP_NUM_THREADS"] = "2"
    os.environ["OPENBLAS_NUM_THREADS"] = "2"
    import onnxruntime as ort
    original = ort.SessionOptions

    def options():
        value = original()
        value.intra_op_num_threads = 2
        value.inter_op_num_threads = 1
        value.add_session_config_entry("session.intra_op.allow_spinning", "0")
        value.add_session_config_entry("session.inter_op.allow_spinning", "0")
        return value

    ort.SessionOptions = options


def analyze(request):
    configure_runtime()
    import pymupdf
    from .layout_text import text_in_layout_order
    with pymupdf.open(request["pdf"]) as document:
        if not document.permissions & pymupdf.PDF_PERM_COPY:
            raise PermissionError("Copying text is not allowed by this PDF")
        page = document[int(request["page"])]
        # Word coordinates use the unrotated page coordinate system.
        page.set_rotation(0)
        words = request.get("words")
        if words is None:
            words = page.get_text("words")
        if not words:
            return {"text": ""}
        # Keep this lazy import out of the GUI's frozen dependency analysis too:
        # PyInstaller otherwise imports Qt and ORT in the same inspection process.
        import importlib
        importlib.import_module("pymupdf.layout")
        page.get_layout()
        return {"text": text_in_layout_order(words, page.layout_information)}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("result", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.request.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Layout request is too large")
        result = analyze(json.loads(args.request.read_text(encoding="utf-8")))
        code = 0
    except Exception as error:
        import traceback
        traceback.print_exc(file=sys.stderr)
        result, code = {"error": str(error)}, 1
    args.result.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return code
