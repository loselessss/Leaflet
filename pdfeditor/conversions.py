"""Atomic image/PDF conversion helpers independent of Qt."""

import os
from pathlib import Path
import tempfile

import pymupdf as fitz


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")
IMAGE_OPEN_FILTER = (
    "이미지 파일 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
    "PNG (*.png);;JPEG (*.jpg *.jpeg);;TIFF (*.tif *.tiff);;BMP (*.bmp)")


def _atomic_pdf_save(document, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".%s." % output.name, suffix=".tmp", dir=output.parent)
    os.close(fd)
    os.unlink(temporary)
    try:
        document.save(temporary, garbage=3, deflate=True)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def images_to_pdf(image_paths, output_path):
    paths = [Path(path) for path in image_paths]
    if not paths:
        raise ValueError("변환할 이미지가 없습니다.")
    if any(path.suffix.casefold() not in IMAGE_EXTENSIONS for path in paths):
        raise ValueError("지원하지 않는 이미지 형식이 있습니다.")
    result = fitz.open()
    try:
        for path in paths:
            source = fitz.open(path)
            try:
                converted = fitz.open("pdf", source.convert_to_pdf())
                try:
                    result.insert_pdf(converted)
                finally:
                    converted.close()
            finally:
                source.close()
        if result.page_count < 1:
            raise ValueError("이미지에서 PDF 페이지를 만들지 못했습니다.")
        _atomic_pdf_save(result, output_path)
        return result.page_count
    finally:
        result.close()


def write_image_atomic(data, output_path):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".%s." % output.name, suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
