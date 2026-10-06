"""Safe PDF size reduction independent from Qt."""

import os
import tempfile

import pymupdf as fitz


COMPRESSION_PRESETS = {
    "lossless": None,
    "balanced": {"dpi_threshold": 180, "dpi_target": 150, "quality": 75},
    "strong": {"dpi_threshold": 120, "dpi_target": 96, "quality": 55},
}


def compress_pdf_bytes(data, output_path, preset="balanced"):
    """Compress PDF bytes to a temporary file, then atomically replace output."""
    if preset not in COMPRESSION_PRESETS:
        raise ValueError("Unknown PDF compression preset: %s" % preset)
    output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(output_path)
    os.makedirs(output_dir, exist_ok=True)
    document = fitz.open("pdf", data)
    fd, temporary = tempfile.mkstemp(
        prefix=".%s." % os.path.basename(output_path),
        suffix=".tmp", dir=output_dir)
    os.close(fd)
    os.unlink(temporary)
    try:
        image_options = COMPRESSION_PRESETS[preset]
        if image_options is not None:
            rewrite = getattr(document, "rewrite_images", None)
            if rewrite is None:
                raise RuntimeError(
                    "This PyMuPDF version does not support image compression.")
            rewrite(**image_options)
        options = {
            "garbage": 4,
            "deflate": True,
            "deflate_images": True,
            "deflate_fonts": True,
            "use_objstms": 1,
        }
        try:
            document.save(temporary, compression_effort=75, **options)
        except TypeError:
            # PyMuPDF before compression_effort was added still supports the
            # compatible lossless options above.
            if os.path.exists(temporary):
                os.remove(temporary)
            document.save(temporary, **options)
        os.replace(temporary, output_path)
        return os.path.getsize(output_path)
    finally:
        document.close()
        if os.path.exists(temporary):
            os.remove(temporary)
