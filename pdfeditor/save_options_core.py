"""PDF save cleanup independent of the GUI."""

from itertools import chain


def _illustrator_entries(pdf):
    """Locate Illustrator's private round-trip data without touching other apps.

    PieceInfo and its Illustrator entry may be direct or indirect dictionaries.
    Only detach the Illustrator entry; PDF layers and drawing resources remain.
    """
    owners = chain((pdf.pdf_catalog(),), (pdf.page_xref(index) for index in range(pdf.page_count)))
    for owner in owners:
        kind, value = pdf.xref_get_key(owner, "PieceInfo")
        if kind == "xref":
            dictionary = int(value.split()[0])
            key = "Illustrator"
        elif kind == "dict":
            dictionary = owner
            key = "PieceInfo/Illustrator"
        else:
            continue
        if pdf.xref_get_key(dictionary, key)[0] != "null":
            yield dictionary, key


def has_illustrator_editing_data(pdf):
    return next(_illustrator_entries(pdf), None) is not None


def strip_illustrator_editing_data(pdf):
    """Detach stale Illustrator data so reopening uses the edited PDF content."""
    for dictionary, key in _illustrator_entries(pdf):
        pdf.xref_set_key(dictionary, key, "null")


def strip_save_information(pdf, *, remove_metadata=False, remove_editing_data=False,
                           remove_illustrator_data=False):
    """Remove requested metadata and known application editing records."""
    if remove_metadata:
        pdf.set_metadata({})
        pdf.xref_set_key(-1, "Info", "null")
        pdf.xref_set_key(pdf.pdf_catalog(), "Metadata", "null")
    if remove_editing_data:
        for page in pdf:
            pdf.xref_set_key(page.xref, "SPDFObjects", "null")
    if remove_illustrator_data:
        strip_illustrator_editing_data(pdf)
