"""PDF save cleanup independent of the GUI."""


def strip_save_information(pdf, *, remove_metadata=False, remove_editing_data=False):
    """Remove only document metadata and Leaflet's known object records."""
    if remove_metadata:
        pdf.set_metadata({})
        pdf.xref_set_key(-1, "Info", "null")
        pdf.xref_set_key(pdf.pdf_catalog(), "Metadata", "null")
    if remove_editing_data:
        for page in pdf:
            pdf.xref_set_key(page.xref, "SPDFObjects", "null")
