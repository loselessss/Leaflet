"""Document file types accepted by sPDF."""

import os


SUPPORTED_DOCUMENT_EXTENSIONS = (".pdf", ".ai", ".eps")
DOCUMENT_OPEN_FILTER = (
    "PDF/Illustrator/EPS 파일 (*.pdf *.ai *.eps);;"
    "PDF 파일 (*.pdf);;Illustrator 파일 (*.ai);;EPS 파일 (*.eps)")


def is_supported_document(path):
    return os.path.splitext(str(path))[1].lower() in \
        SUPPORTED_DOCUMENT_EXTENSIONS


def is_illustrator_document(path):
    return os.path.splitext(str(path))[1].lower() == ".ai"


def is_eps_document(path):
    return os.path.splitext(str(path))[1].lower() == ".eps"


def suggested_pdf_path(path):
    """Return a PDF destination so an Illustrator source is never overwritten."""
    root, extension = os.path.splitext(str(path))
    if extension.lower() == ".pdf":
        return str(path)
    return (root or str(path)) + ".pdf"
