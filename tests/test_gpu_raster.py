import tempfile
from pathlib import Path
import pickle
import unittest
from unittest.mock import patch

import fitz

from pdfeditor.core import Document


def image_mask_pdf_bytes():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 44 >>\nstream\n"
        b"q 0 0 1 rg 100 0 0 100 20 20 cm /Im1 Do Q\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 "
        b"/ImageMask true /BitsPerComponent 1 /Decode [0 1] /Length 8 >>\n"
        b"stream\n\xf0\x90\x90\xf0\x90\x90\x90\x00\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def cmyk_image_pdf_bytes():
    pixels = bytes((0, 255, 255, 0, 255, 0, 255, 0,
                    255, 255, 0, 0, 0, 0, 0, 128))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 44 >>\nstream\n"
        b"q 0 0 1 rg 120 0 0 120 30 30 cm /Im1 Do Q\nendstream",
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
        b"/ColorSpace /DeviceCMYK /BitsPerComponent 8 /Length " +
        str(len(pixels)).encode() + b" >>\nstream\n" + pixels + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def repeated_image_pdf_bytes():
    pixels = bytes((
        255, 0, 0, 0, 255, 0,
        0, 0, 255, 255, 255, 0))
    content = (
        b"q 20 0 0 20 20 20 cm /Im1 Do Q\n"
        b"q 20 0 0 20 60 20 cm /Im1 Do Q\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 120 80] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" +
        content + b"endstream",
        b"<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length " +
        str(len(pixels)).encode() + b" >>\nstream\n" + pixels + b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def downsampled_image_pdf_bytes():
    width = 64
    height = 64
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend((x * 4, y * 4, 128))
    content = b"q 8 0 0 8 20 20 cm /Im1 Do Q\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 120 80] "
        b"/Resources << /XObject << /Im1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" +
        content + b"endstream",
        b"<< /Type /XObject /Subtype /Image /Width 64 /Height 64 "
        b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Length " +
        str(len(pixels)).encode() + b" >>\nstream\n" + bytes(pixels) +
        b"\nendstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def linear_gradient_pdf_bytes():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /Shading << /Sh1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 38 >>\nstream\n"
        b"q 20 20 260 200 re W n /Sh1 sh Q\nendstream",
        b"<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [20 20 280 20] "
        b"/Function << /FunctionType 2 /Domain [0 1] /C0 [1 0 0] "
        b"/C1 [0 0 1] /N 1 >> /Extend [true true] >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def radial_gradient_pdf_bytes():
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /Shading << /Sh1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 38 >>\nstream\n"
        b"q 20 20 260 200 re W n /Sh1 sh Q\nendstream",
        b"<< /ShadingType 3 /ColorSpace /DeviceRGB "
        b"/Coords [150 120 0 150 120 130] "
        b"/Function << /FunctionType 2 /Domain [0 1] /C0 [1 1 0] "
        b"/C1 [0 0 1] /N 1 >> /Extend [false false] >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def isolated_group_pdf_bytes(blend_mode="Normal", background=False, clip=False):
    page_content = b"q /GS1 gs /Fm1 Do Q\n"
    if clip:
        # Nested clips, including an even-odd hole, before the blended group.
        # A preceding mark exercises backdrop preservation.
        page_content = (b"q 35 35 230 180 re W n "
                        b"q 40 40 220 170 re 110 95 50 50 re W* n "
                        b"0.8 0.6 0.2 rg 40 40 80 160 re f\n" +
                        page_content + b"Q Q\n")
    if background:
        page_content = b"0.2 0.4 0.6 rg 0 0 300 240 re f\n" + page_content
    form_content = (
        b"1 0 0 rg 20 20 180 140 re f "
        b"0 0 1 rg 100 80 180 140 re f\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Fm1 5 0 R >> "
        b"/ExtGState << /GS1 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
        b"/Resources << >> /Group << /S /Transparency /I true "
        b"/CS /DeviceRGB >> /Length " + str(len(form_content)).encode() +
        b" >>\nstream\n" + form_content + b"endstream",
        b"<< /Type /ExtGState /ca 0.5 /CA 0.5 /BM /" +
        blend_mode.encode("ascii") + b" >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def blended_mask_pdf_bytes(blend_mode="SoftLight", luminosity=True,
                           mask_blend=False, color=(.5, .5, .5), image=False):
    """A real PDF with a mask applied to a blended, isolated form."""
    with fitz.open(stream=isolated_group_pdf_bytes(blend_mode, background=True),
                   filetype="pdf") as pdf:
        mask = pdf.get_new_xref()
        resources = "/ExtGState << /Mix << /BM /Multiply >> >>"
        content = ("%s %s %s rg 50 50 200 140 re f\n" % color).encode("ascii")
        if mask_blend:
            inner = pdf.get_new_xref()
            pdf.update_object(inner,
                "<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
                "/Group << /S /Transparency /I true /CS /DeviceRGB >> /Resources << >> >>")
            pdf.update_stream(inner, b"0.75 g 60 60 180 120 re f\n")
            resources += " /XObject << /Inner %s 0 R >>" % inner
            content += b"q 60 60 170 110 re W n /Mix gs /Inner Do Q\n"
        if image:
            bitmap = pdf.get_new_xref()
            pdf.update_object(bitmap,
                "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 "
                "/ColorSpace /DeviceGray /BitsPerComponent 8 >>")
            pdf.update_stream(bitmap, bytes((255, 128, 64, 0)))
            resources += " /XObject << /Im %s 0 R >>" % bitmap
            content = b"q 200 0 0 140 50 50 cm /Im Do Q\n"
        pdf.update_object(mask,
            "<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
            "/Group << /S /Transparency /I true /CS /DeviceRGB >> "
            "/Resources << " + resources + " >> >>")
        pdf.update_stream(mask, content)
        pdf.xref_set_key(6, "SMask", "<< /S /%s /G %s 0 R /BC [0 0 0] >>" %
                         ("Luminosity" if luminosity else "Alpha", mask))
        return pdf.tobytes()


def soft_mask_pdf_bytes(transfer_function=None):
    page_content = b"q /GS1 gs 1 0 0 rg 20 20 260 200 re f Q\n"
    mask_content = b"0.5 g 50 50 200 140 re f\n"
    transfer = (b" /TR " + transfer_function
                if transfer_function is not None else b"")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /ExtGState << /GS1 6 0 R >> >> "
        b"/Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
        b"/Resources << >> /Group << /S /Transparency /I true "
        b"/CS /DeviceGray >> /Length " + str(len(mask_content)).encode() +
        b" >>\nstream\n" + mask_content + b"endstream",
        b"<< /Type /ExtGState /SMask << /S /Luminosity /G 5 0 R "
        b"/BC [0]" + transfer + b" >> >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def tiling_pattern_pdf_bytes():
    page_content = b"/P1 scn 0 0 32 32 re f\n"
    pattern_content = (
        b"1 0 0 rg 0 0 4 4 re f\n"
        b"0 0 1 rg 4 4 4 4 re f\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 32 32] "
        b"/Resources << /ColorSpace << /PatternCS [/Pattern /DeviceRGB] >> "
        b"/Pattern << /P1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 "
        b"/BBox [0 0 8 8] /XStep 8 /YStep 8 /Resources << >> "
        b"/Matrix [1 0 0 1 0 0] /Length " +
        str(len(pattern_content)).encode() +
        b" >>\nstream\n" + pattern_content + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def baked_gradient_band_pdf_bytes():
    bands = []
    for index in range(12):
        bands.append(
            f"q 1 0 0 1 {index * 2} 0 cm "
            "0.3 0.4 0.7 rg 0 0 1.8 20 re f Q\n".encode())
    bands.append(b"0.8 0.2 0.1 rg 30 0 5 20 re f\n")
    page_content = b"".join(bands)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 20] "
        b"/Resources << >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def similar_color_band_pdf_bytes():
    bands = []
    for index in range(12):
        red = 0.30 + index * 0.002
        bands.append(
            f"{red:.3f} 0.4 0.7 rg {index * 2} 0 1.8 20 re f\n".encode())
    page_content = b"".join(bands)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 40 20] "
        b"/Resources << >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def cmyk_group_pdf_bytes(alpha=1.0, blend_mode="Normal"):
    page_content = b"q /GS1 gs /Fm1 Do Q\n"
    form_content = b"0 1 1 0 k 20 20 180 140 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Fm1 5 0 R >> "
        b"/ExtGState << /GS1 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
        b"/Resources << >> /Group << /S /Transparency /I true "
        b"/CS /DeviceCMYK >> /Length " + str(len(form_content)).encode() +
        b" >>\nstream\n" + form_content + b"endstream",
        b"<< /Type /ExtGState /ca " + str(alpha).encode("ascii") +
        b" /CA " + str(alpha).encode("ascii") + b" /BM /" +
        blend_mode.encode("ascii") + b" >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def nonisolated_single_path_pdf_bytes(alpha=0.4, knockout=False):
    page_content = b"0.2 0.4 0.6 rg 0 0 300 240 re f\nq /GS1 gs /Fm1 Do Q\n"
    form_content = b"1 0 0 rg 20 20 180 140 re f\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Fm1 5 0 R >> "
        b"/ExtGState << /GS1 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
        b"/Resources << >> /Group << /S /Transparency /I false "
        b"/K " + (b"true" if knockout else b"false") +
        b" /CS /DeviceRGB >> /Length " + str(len(form_content)).encode() +
        b" >>\nstream\n" + form_content + b"endstream",
        b"<< /Type /ExtGState /ca " + str(alpha).encode("ascii") +
        b" /CA " + str(alpha).encode("ascii") + b" /BM /Normal >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def small_overlapping_nonisolated_group_pdf_bytes():
    page_content = (
        b"0.2 0.4 0.6 rg 0 0 300 240 re f\n"
        b"q /GS1 gs /Fm1 Do Q\n"
        b"0 1 0 rg 90 90 8 8 re f\n")
    form_content = (
        b"/Half gs 1 0 0 rg 80 80 25 25 re f\n"
        b"/Half gs 0 0 1 rg 92 92 25 25 re f\n")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 240] "
        b"/Resources << /XObject << /Fm1 5 0 R >> "
        b"/ExtGState << /GS1 6 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(page_content)} >>\nstream\n".encode() +
        page_content + b"endstream",
        b"<< /Type /XObject /Subtype /Form /BBox [0 0 300 240] "
        b"/Resources << /ExtGState << /Half 7 0 R >> >> "
        b"/Group << /S /Transparency /I false "
        b"/K true /CS /DeviceRGB >> /Length " +
        str(len(form_content)).encode() +
        b" >>\nstream\n" + form_content + b"endstream",
        b"<< /Type /ExtGState /ca 0.5 /CA 0.5 /BM /Normal >>",
        b"<< /Type /ExtGState /ca 0.5 /CA 0.5 /BM /Normal >>",
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode())
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


class GpuRasterSceneTests(unittest.TestCase):
    def test_move_only_fill_is_ignored_without_falling_back(self):
        from pdfeditor import gpu_raster as g
        with fitz.open() as pdf:
            page = pdf.new_page(width=100, height=100)
            page.draw_rect((10, 10, 40, 40), fill=(1, 0, 0))
            content = page.get_contents()[0]
            pdf.update_stream(content, b"0 0 m f\n" + pdf.xref_stream(content))
            scene = g.vector_page_from_pymupdf(page)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(len(scene.items), 2)

    def test_mask_derived_clip_is_not_absorbed_by_gradient_compaction(self):
        from pdfeditor import gpu_raster as g
        commands = g._rect_commands(0, 0, 20, 20)
        items = (g.ClipPush(commands, refresh_key=("mask", 0)),
                 g.VectorLinearGradient(commands, (0, 0), (20, 0),
                                        ((0, 0xff000000), (1, 0xffffffff))), g.ClipPop())
        self.assertEqual(g._compact_gradient_clip_triplets(items), (items, False))

    def test_refinement_worker_reads_pixel_free_recipe(self):
        from pdfeditor import gpu_raster as g, gpu_scene_worker as worker
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, recipe_path, result_path = (root / "page.pdf", root / "base.pickle", root / "out.pickle")
            with fitz.open(stream=downsampled_image_pdf_bytes(), filetype="pdf") as pdf:
                pdf.save(snapshot)
                base = g.vector_page_from_pymupdf(pdf[0], 1)
                expected = g.vector_page_from_pymupdf(pdf[0], 2)
            recipe = replace(base, items=tuple(replace(x, pixels=b"")
                             if isinstance(x, g.VectorImage) else x for x in base.items))
            recipe_path.write_bytes(pickle.dumps(recipe))
            with patch.object(worker, "vector_page_from_pymupdf", side_effect=AssertionError):
                self.assertEqual(worker.main([str(snapshot), str(result_path), "--scale", "2",
                                              "--base-scene", str(recipe_path)]), 0)
            self.assertEqual(pickle.loads(result_path.read_bytes()), expected)
            self.assertFalse(Path(str(result_path) + ".tmp").exists())

    def test_image_refinement_reuses_vectors_and_matches_full_extraction(self):
        from pdfeditor import gpu_raster as g
        from dataclasses import replace
        with fitz.open(stream=downsampled_image_pdf_bytes(), filetype="pdf") as pdf:
            pdf[0].insert_text((10, 20), "Vector text")
            base = g.vector_page_from_pymupdf(pdf[0], 1)
            full = g.vector_page_from_pymupdf(pdf[0], 2)
            with patch.object(g, "_path_commands", side_effect=AssertionError), \
                    patch.object(g, "_gradient_stops", side_effect=AssertionError):
                result = g.refine_page_images(pdf[0], base, 2)
            self.assertEqual(result, full)
            for first, second in zip(base.items, result.items):
                if not isinstance(first, g.VectorImage):
                    self.assertIs(first, second)
            recipe = replace(base, items=tuple(replace(x, pixels=b"")
                             if isinstance(x, g.VectorImage) else x for x in base.items))
            self.assertEqual(g.refine_page_images(pdf[0], recipe, 2), full)
            self.assertIsNone(g.refine_page_images(pdf[0], base, 2, timeout_seconds=0))
            self.assertIsNone(g.refine_page_images(pdf[0], replace(base, features=("tile-pattern",)), 2))

    def test_mask_and_island_refinement_match_full_extraction(self):
        from pdfeditor import gpu_raster as g
        samples = [image_mask_pdf_bytes(), isolated_group_pdf_bytes("Multiply")]
        for data in samples:
            with fitz.open(stream=data, filetype="pdf") as pdf:
                if data == samples[1]:
                    pdf.xref_set_key(5, "Group/I", "false")
                base = g.vector_page_from_pymupdf(pdf[0], 1)
                full = g.vector_page_from_pymupdf(pdf[0], 2)
                self.assertTrue(base.supported, base.reason)
                self.assertEqual(g.refine_page_images(pdf[0], base, 2), full)

    def test_early_image_reduction_preserves_source_and_high_zoom(self):
        from pdfeditor import gpu_raster as g
        for colorspace in (fitz.csGRAY, fitz.csCMYK):
            with self.subTest(channels=colorspace.n), fitz.open() as pdf:
                page = pdf.new_page(width=200, height=200)
                pix = fitz.Pixmap(colorspace, fitz.IRect(0, 0, 512, 256), False)
                pix.clear_with(70)
                xref = page.insert_image((10, 10, 74, 42), pixmap=pix)
                original = fitz.Pixmap(pdf, xref).samples
                low = g.vector_page_from_pymupdf(page, 1)
                self.assertTrue(low.supported, low.reason)
                self.assertIn("image-early-downsample", low.features)
                low_image = next(x for x in low.items if isinstance(x, g.VectorImage))
                self.assertEqual((low_image.width, low_image.height), (64, 32))
                self.assertEqual(fitz.Pixmap(pdf, xref).samples, original)
                high = g.vector_page_from_pymupdf(page, 8)
                self.assertTrue(high.supported, high.reason)
                self.assertNotIn("image-early-downsample", high.features)
                high_image = next(x for x in high.items if isinstance(x, g.VectorImage))
                self.assertEqual((high_image.width, high_image.height), (512, 256))

    def test_extraction_work_is_released_after_success_and_failure(self):
        from pdfeditor import gpu_raster as g
        with fitz.open(stream=linear_gradient_pdf_bytes(), filetype="pdf") as pdf:
            self.assertTrue(g.vector_page_from_pymupdf(pdf[0]).supported)
            self.assertIsNone(g._extraction_work.get())
            with patch.object(g, "_vector_page_from_pymupdf", side_effect=ValueError("test")):
                with self.assertRaises(ValueError):
                    g.vector_page_from_pymupdf(pdf[0])
            self.assertIsNone(g._extraction_work.get())

    def test_mask_lut_matches_integer_reference_for_all_alpha_values(self):
        from pdfeditor import gpu_raster as g
        samples = bytes(range(256))
        for color in (0xffffffff, 0xff123456, 0xff000000, 0xff01fe7f):
            expected = bytes(value for alpha in samples for value in (
                ((color & 255) * alpha + 127) // 255,
                (((color >> 8) & 255) * alpha + 127) // 255,
                (((color >> 16) & 255) * alpha + 127) // 255, alpha))
            self.assertEqual(g._alpha_to_premul_bgra(samples, color), expected)
        self.assertEqual(g._alpha_to_premul_bgra(b""), b"")

    def test_gradient_opacity_reuses_only_same_item_and_opacity_within_job(self):
        from pdfeditor import gpu_raster as g
        item = g.VectorLinearGradient((), (0, 0), (1, 0),
                                      ((0, 0xff123456), (1, 0x80765432)))
        token = g._extraction_work.set(({}, {}, {}))
        try:
            first = g._with_group_opacity(item, 0.5)
            self.assertIs(first, g._with_group_opacity(item, 0.5))
            self.assertEqual(first, g._uncached_with_group_opacity(item, 0.5))
            self.assertNotEqual(first, g._with_group_opacity(item, 0.25))
            self.assertIs(item, g._with_group_opacity(item, 1.0))
        finally:
            g._extraction_work.reset(token)
        self.assertIsNone(g._extraction_work.get())

    def test_repeated_gradient_conversion_is_reused_without_scene_change(self):
        from pdfeditor import gpu_raster as g
        with fitz.open(stream=linear_gradient_pdf_bytes(), filetype="pdf") as pdf:
            pdf.update_stream(4, b"q /Sh1 sh Q\n" * 4)
            with patch.object(g, "_device_color_values", wraps=g._device_color_values) as convert:
                reference = g._vector_page_from_pymupdf(pdf[0])
                original_calls = convert.call_count
            with patch.object(g, "_device_color_values", wraps=g._device_color_values) as convert:
                scene = g.vector_page_from_pymupdf(pdf[0])
                self.assertEqual(scene, reference)
                self.assertLess(convert.call_count, original_calls)

    def test_bbox_work_reuses_identity_not_equal_looking_objects(self):
        from pdfeditor import gpu_raster as g
        first = g.VectorPath((("move", 0, 0), ("line", 10, 10)))
        second = g.VectorPath((("move", 0, 0), ("line", 20, 20)))
        token = g._extraction_work.set(({}, {}))
        try:
            with patch.object(g, "_uncached_item_bbox", wraps=g._uncached_item_bbox) as compute:
                self.assertEqual(g._item_bbox(first), g._item_bbox(first))
                self.assertNotEqual(g._item_bbox(first), g._item_bbox(second))
                self.assertEqual(compute.call_count, 2)
        finally:
            g._extraction_work.reset(token)

    def test_image_mask_area_uses_transformed_unit_bounds_and_page_clip(self):
        from pdfeditor.gpu_raster import _image_mask_area

        self.assertEqual(
            _image_mask_area((80, 20, -10, 40, 25, 30), (0, 0, 100, 100)),
            (15, 30, 100, 90))
        self.assertIsNone(
            _image_mask_area((10, 0, 0, 10, 120, 120), (0, 0, 100, 100)))

    def test_all_standard_pdf_blends_remain_gpu_scenes(self):
        from pdfeditor.gpu_raster import GroupPush, vector_page_from_pymupdf
        modes = ("Multiply", "Screen", "Overlay", "Darken", "Lighten",
                 "ColorDodge", "ColorBurn", "HardLight", "SoftLight",
                 "Difference", "Exclusion", "Hue", "Saturation", "Color",
                 "Luminosity")
        for mode, name in enumerate(modes, 1):
            with self.subTest(mode=name), fitz.open(
                    stream=isolated_group_pdf_bytes(name), filetype="pdf") as pdf:
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn("blend-mode", scene.features)
                self.assertTrue(any(isinstance(item, GroupPush) and
                    item.blend_mode == mode for item in scene.drawables))

    def test_nonseparable_blend_inside_clip_stays_on_gpu(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        with fitz.open(stream=isolated_group_pdf_bytes("Hue"), filetype="pdf") as pdf:
            page = pdf[0]
            xref = page.get_contents()[0]
            pdf.update_stream(xref, b"q 30 30 180 180 re W n\n" +
                              pdf.xref_stream(xref) + b"\nQ")
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)

    def test_blended_scene_supports_groups_inside_active_clips(self):
        from pdfeditor.gpu_raster import (ClipPush, ClipPop, GroupPush,
                                         GroupPop, _validate_composite_context)
        clip = ClipPush((("move", 0, 0), ("line", 1, 1)))
        self.assertEqual("", _validate_composite_context(
            (clip, GroupPush(.5, 9), GroupPop(), ClipPop())))
        self.assertEqual("", _validate_composite_context(
            (GroupPush(.5, 9), clip, ClipPop(), GroupPop())))

    def test_blended_scene_supports_groups_and_clips_in_soft_masks(self):
        from pdfeditor.gpu_raster import (ClipPush, ClipPop, GroupPush, GroupPop,
                                         MaskBegin, MaskEnd, _validate_composite_context)
        mask = MaskBegin((0, 0, 100, 100), True, 0xff000000)
        clip = ClipPush((("move", 0, 0), ("line", 1, 1)))
        for items in ((mask, GroupPush(1), GroupPop(), MaskEnd(), ClipPop()),
                      (mask, MaskEnd(), GroupPush(1, 9), GroupPop(), ClipPop()),
                      (mask, MaskEnd(), clip, ClipPop(), ClipPop())):
            with self.subTest(items=items):
                self.assertEqual("", _validate_composite_context(items))

    def test_blended_scene_rejects_crossed_mask_and_group_scopes(self):
        from pdfeditor.gpu_raster import (ClipPop, GroupPush, GroupPop,
                                         MaskBegin, MaskEnd, _validate_composite_context)
        mask = MaskBegin((0, 0, 100, 100), True, 0xff000000)
        for items in ((mask, GroupPush(1), MaskEnd(), GroupPop(), ClipPop()),
                      (GroupPush(1), mask, MaskEnd(), GroupPop(), ClipPop()),
                      (mask,)):
            with self.subTest(items=items):
                self.assertIn("unbalanced", _validate_composite_context(items))

    def test_actual_blends_in_mask_build_and_apply_scopes_stay_on_gpu(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        for luminosity in (False, True):
            for mask_blend in (False, True):
                with self.subTest(luminosity=luminosity, mask_blend=mask_blend), fitz.open(
                        stream=blended_mask_pdf_bytes(luminosity=luminosity,
                            mask_blend=mask_blend), filetype="pdf") as pdf:
                    scene = vector_page_from_pymupdf(pdf[0])
                    self.assertTrue(scene.supported, scene.reason)
                    self.assertIn("soft-mask", scene.features)
                    self.assertIn("blend-mode", scene.features)

    def test_colored_luminosity_masks_stay_on_gpu(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        for color in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            with self.subTest(color=color), fitz.open(
                    stream=blended_mask_pdf_bytes(color=color), filetype="pdf") as pdf:
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertTrue(scene.supported, scene.reason)

    def test_grayscale_mask_image_preserves_pdf_interpolation(self):
        from pdfeditor.gpu_raster import VectorImage, vector_page_from_pymupdf
        with fitz.open(stream=blended_mask_pdf_bytes(image=True), filetype="pdf") as pdf:
            for interpolate in (False, True):
                for xref in range(1, pdf.xref_length()):
                    if pdf.xref_get_key(xref, "Subtype")[1] == "/Image":
                        pdf.xref_set_key(xref, "Interpolate", str(interpolate).lower())
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertTrue(scene.supported, scene.reason)
                image = next(item for item in scene.drawables if isinstance(item, VectorImage))
                self.assertEqual(image.interpolate, interpolate)
                self.assertEqual(image.pixels[:8], bytes((255, 255, 255, 255, 128, 128, 128, 255)))

    def test_cmyk_image_is_converted_to_gpu_bgra_bitmap(self):
        from pdfeditor.gpu_raster import VectorImage, vector_page_from_pymupdf
        with fitz.open(stream=cmyk_image_pdf_bytes(), filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("image", scene.features)
        image = scene.drawables[0]
        self.assertIsInstance(image, VectorImage)
        self.assertEqual((image.width, image.height, image.stride), (2, 2, 8))
        self.assertEqual(len(image.pixels), 16)

    def test_identity_soft_mask_transfer_function_stays_on_gpu(self):
        from pdfeditor.gpu_raster import MaskEnd, vector_page_from_pymupdf
        identity = (b"<< /FunctionType 2 /Domain [0 1] /C0 [0] "
                    b"/C1 [1] /N 1 >>")
        with fitz.open(stream=soft_mask_pdf_bytes(identity),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("soft-mask", scene.features)
        self.assertTrue(any(isinstance(item, MaskEnd)
                            for item in scene.drawables))

    def test_nonidentity_soft_mask_transfer_function_stays_on_gpu(self):
        from pdfeditor.gpu_raster import MaskEnd, vector_page_from_pymupdf
        inverse = (b"<< /FunctionType 2 /Domain [0 1] /C0 [1] "
                   b"/C1 [0] /N 1 >>")
        with fitz.open(stream=soft_mask_pdf_bytes(inverse),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("soft-mask-transfer-function", scene.features)
        mask_end = next(item for item in scene.drawables
                        if isinstance(item, MaskEnd))
        self.assertEqual(len(mask_end.transfer), 256)
        self.assertAlmostEqual(mask_end.transfer[0], 1.0)
        self.assertAlmostEqual(mask_end.transfer[-1], 0.0)

    def test_colored_tiling_pattern_expands_to_gpu_scene(self):
        from pdfeditor.gpu_raster import (ClipPop, ClipPush, VectorPath,
                                          vector_page_from_pymupdf)
        with fitz.open(stream=tiling_pattern_pdf_bytes(),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("tile-pattern", scene.features)
        self.assertIn("vector-tile-pattern", scene.features)
        self.assertIsInstance(scene.drawables[0], ClipPush)
        self.assertIsInstance(scene.drawables[-1], ClipPop)
        paths = [item for item in scene.drawables
                 if isinstance(item, VectorPath)]
        self.assertGreaterEqual(len(paths), 8)
        self.assertTrue(any(item.fill_argb == 0xffff0000 for item in paths))
        self.assertTrue(any(item.fill_argb == 0xff0000ff for item in paths))

    def test_baked_gradient_bands_merge_same_color_fill_paths(self):
        from pdfeditor.gpu_raster import VectorPath, vector_page_from_pymupdf
        with fitz.open(stream=baked_gradient_band_pdf_bytes(),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("baked-gradient-band-merge", scene.features)
        paths = [item for item in scene.drawables
                 if isinstance(item, VectorPath)]
        self.assertEqual(len(paths), 2)
        self.assertIsNone(paths[0].transform)
        self.assertEqual(paths[0].fill_argb, 0xff4d66b2)
        self.assertEqual(paths[1].fill_argb, 0xffcc331a)
        self.assertGreater(len(paths[0].commands), len(paths[1].commands))

    def test_aggressive_band_merge_compacts_similar_color_fill_paths(self):
        from pdfeditor.gpu_raster import VectorPath, vector_page_from_pymupdf
        with fitz.open(stream=similar_color_band_pdf_bytes(),
                       filetype="pdf") as pdf:
            conservative = vector_page_from_pymupdf(pdf[0])
            aggressive = vector_page_from_pymupdf(
                pdf[0], aggressive_band_merge=True)
        self.assertTrue(conservative.supported, conservative.reason)
        self.assertTrue(aggressive.supported, aggressive.reason)
        self.assertNotIn("aggressive-band-merge", conservative.features)
        self.assertIn("aggressive-band-merge", aggressive.features)
        conservative_paths = [item for item in conservative.drawables
                              if isinstance(item, VectorPath)]
        aggressive_paths = [item for item in aggressive.drawables
                            if isinstance(item, VectorPath)]
        self.assertGreater(len(conservative_paths), 1)
        self.assertEqual(len(aggressive_paths), 1)
        self.assertNotEqual(
            aggressive_paths[0].fill_argb, conservative_paths[0].fill_argb)

    def test_aggressive_band_merge_does_not_chain_beyond_tolerance(self):
        from pdfeditor.gpu_raster import (
            VectorPath, _compact_consecutive_fill_paths)
        paths = tuple(VectorPath(
            (("move", index * 2.0, 0.0),
             ("line", index * 2.0 + 1.0, 0.0),
             ("line", index * 2.0 + 1.0, 1.0),
             ("line", index * 2.0, 1.0), ("close",)),
            fill_argb=color)
            for index, color in enumerate(
                (0xff000000, 0xff0a0a0a, 0xff141414)))
        compacted, _fill, _text, aggressive = \
            _compact_consecutive_fill_paths(
                paths, aggressive_band_merge=True)
        self.assertTrue(aggressive)
        self.assertEqual(len(compacted), 2)

    def test_overlapping_text_outlines_are_not_merged(self):
        from pdfeditor.gpu_raster import (
            VectorPath, _compact_consecutive_fill_paths)
        commands = (("move", 0.0, 0.0), ("line", 2.0, 0.0),
                    ("line", 2.0, 2.0), ("line", 0.0, 2.0),
                    ("close",))
        paths = (
            VectorPath(commands, fill_argb=0x803366cc,
                       transform=(1, 0, 0, 1, 0, 0), groupable=True),
            VectorPath(commands, fill_argb=0x803366cc,
                       transform=(1, 0, 0, 1, 1, 0), groupable=True))
        compacted, _fill, text, _aggressive = \
            _compact_consecutive_fill_paths(paths)
        self.assertFalse(text)
        self.assertEqual(compacted, paths)

    def test_redundant_rect_clip_is_removed_from_radial_gradient(self):
        from pdfeditor.gpu_raster import (
            ClipPop, ClipPush, VectorRadialGradient,
            _compact_gradient_clip_triplets, _ellipse_commands,
            _rect_commands)
        gradient = VectorRadialGradient(
            _ellipse_commands((1, 0, 0, 1, 0, 0), 5, 5, 5),
            (5, 5), (5, 5), (5, 5), ((0.0, 0xff000000),
                                           (1.0, 0xffffffff)))
        compacted, merged = _compact_gradient_clip_triplets((
            ClipPush(_rect_commands(0, 0, 10, 10)), gradient, ClipPop()))
        self.assertTrue(merged)
        self.assertEqual(compacted, (gradient,))

    def test_radial_gradient_keeps_clip_when_rect_corners_leave_ellipse(self):
        from pdfeditor.gpu_raster import (
            ClipPop, ClipPush, VectorRadialGradient,
            _compact_gradient_clip_triplets, _ellipse_commands,
            _rect_commands)
        gradient = VectorRadialGradient(
            _ellipse_commands((1, 0, 0, 1, 0, 0), 0, 0, 5),
            (0, 0), (0, 0), (5, 5), ((0.0, 0xff000000),
                                           (1.0, 0xffffffff)))
        items = (ClipPush(_rect_commands(-4, -4, 4, 4)),
                 gradient, ClipPop())
        compacted, merged = _compact_gradient_clip_triplets(items)
        self.assertFalse(merged)
        self.assertEqual(compacted, items)

    def test_opaque_normal_cmyk_transparency_wrapper_stays_on_gpu(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        with fitz.open(stream=cmyk_group_pdf_bytes(),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("transparency-group", scene.features)
        self.assertIn("vector", scene.features)

    def test_cmyk_transparency_group_with_opacity_still_falls_back(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        with fitz.open(stream=cmyk_group_pdf_bytes(alpha=0.5),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertFalse(scene.supported)
        self.assertIn("transparency group colorspace", scene.reason)

    def test_nested_geometry_clips_with_all_blends_stay_on_gpu(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        for name in ("Multiply", "Screen", "Overlay", "Darken", "Lighten",
                     "ColorDodge", "ColorBurn", "HardLight", "SoftLight",
                     "Difference", "Exclusion", "Hue", "Saturation", "Color",
                     "Luminosity"):
            with self.subTest(mode=name), fitz.open(stream=isolated_group_pdf_bytes(
                    name, background=True, clip=True), filetype="pdf") as pdf:
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertTrue(scene.supported, scene.reason)

    def test_color_component_blends_use_cpu_islands_when_self_contained(self):
        from pdfeditor.gpu_raster import VectorImage, vector_page_from_pymupdf
        for name in ("Hue", "Saturation", "Color", "Luminosity"):
            with self.subTest(mode=name), fitz.open(
                    stream=isolated_group_pdf_bytes(name), filetype="pdf") as pdf:
                pdf.xref_set_key(5, "Group/I", "false")
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn("cpu-island", scene.features)
                self.assertTrue(any(isinstance(item, VectorImage)
                                    for item in scene.drawables))

    def test_color_component_blends_reject_overlapping_nonisolated_groups(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        for name in ("Hue", "Saturation", "Color", "Luminosity"):
            with self.subTest(mode=name), fitz.open(
                    stream=isolated_group_pdf_bytes(name, background=True),
                    filetype="pdf") as pdf:
                pdf.xref_set_key(5, "Group/I", "false")
                scene = vector_page_from_pymupdf(pdf[0])
                self.assertFalse(scene.supported)
                self.assertIn("non-isolated", scene.reason)

    def test_opaque_normal_nonisolated_group_is_passthrough(self):
        from pdfeditor.gpu_raster import GroupPush, vector_page_from_pymupdf
        with fitz.open(stream=isolated_group_pdf_bytes(background=True),
                       filetype="pdf") as pdf:
            pdf.xref_set_key(5, "Group/I", "false")
            pdf.xref_set_key(6, "ca", "1")
            pdf.xref_set_key(6, "CA", "1")
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("transparency-group", scene.features)
        self.assertFalse(any(isinstance(item, GroupPush) and
                             not item.isolated
                             for item in scene.drawables))

    def test_nonisolated_group_opacity_still_falls_back(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf
        with fitz.open(stream=isolated_group_pdf_bytes(background=True),
                       filetype="pdf") as pdf:
            pdf.xref_set_key(5, "Group/I", "false")
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertFalse(scene.supported)
        self.assertIn("non-isolated", scene.reason)

    def test_self_contained_nonisolated_group_becomes_cpu_island(self):
        from pdfeditor.gpu_raster import GroupPush, VectorImage, vector_page_from_pymupdf
        with fitz.open(stream=isolated_group_pdf_bytes(),
                       filetype="pdf") as pdf:
            pdf.xref_set_key(5, "Group/I", "false")
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("cpu-island", scene.features)
        self.assertTrue(any(isinstance(item, VectorImage)
                            for item in scene.drawables))
        self.assertFalse(any(isinstance(item, GroupPush) and
                             not item.isolated
                             for item in scene.drawables))

    def test_small_overlapping_knockout_group_becomes_approximate_cpu_island(self):
        from pdfeditor.gpu_raster import (VectorImage, VectorPath,
                                          vector_page_from_pymupdf)
        with fitz.open(stream=small_overlapping_nonisolated_group_pdf_bytes(),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("cpu-island", scene.features)
        self.assertIn("cpu-island-approximate", scene.features)
        self.assertTrue(any(isinstance(item, VectorImage)
                            for item in scene.drawables))
        self.assertFalse(any(isinstance(item, VectorPath) and
                             item.fill_argb == 0xff00ff00
                             for item in scene.drawables))

    def test_single_draw_nonisolated_opacity_group_is_flattened(self):
        from pdfeditor.gpu_raster import GroupPush, VectorPath, vector_page_from_pymupdf
        with fitz.open(stream=nonisolated_single_path_pdf_bytes(0.4),
                       filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("transparency-group", scene.features)
        self.assertFalse(any(isinstance(item, GroupPush) and
                             not item.isolated
                             for item in scene.drawables))
        translucent = [
            item for item in scene.drawables
            if isinstance(item, VectorPath) and item.fill_argb == 0x66ff0000]
        self.assertEqual(len(translucent), 1)

    def test_single_draw_knockout_group_is_flattened(self):
        from pdfeditor.gpu_raster import GroupPush, VectorPath, vector_page_from_pymupdf
        with fitz.open(stream=nonisolated_single_path_pdf_bytes(
                1.0, knockout=True), filetype="pdf") as pdf:
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("transparency-group", scene.features)
        self.assertFalse(any(isinstance(item, GroupPush) and item.knockout
                             for item in scene.drawables))
        self.assertTrue(any(isinstance(item, VectorPath) and
                            item.fill_argb == 0xffff0000
                            for item in scene.drawables))

    def test_disjoint_knockout_group_is_flattened(self):
        from pdfeditor.gpu_raster import (GroupPop, GroupPush, VectorPath,
                                          _flatten_nonisolated_groups)

        first = VectorPath(
            (("move", 0, 0), ("line", 10, 0), ("line", 10, 10), ("close",)),
            fill_argb=0x80ff0000)
        second = VectorPath(
            (("move", 20, 0), ("line", 30, 0), ("line", 30, 10), ("close",)),
            fill_argb=0x800000ff)
        items = _flatten_nonisolated_groups((
            GroupPush(0.5, 0, False, True), first, second, GroupPop()))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].fill_argb, 0x40ff0000)
        self.assertEqual(items[1].fill_argb, 0x400000ff)

    def test_overlapping_knockout_group_stays_on_gpu_scene(self):
        from pdfeditor.gpu_raster import GroupPush, vector_page_from_pymupdf

        with fitz.open(stream=isolated_group_pdf_bytes(),
                       filetype="pdf") as pdf:
            pdf.xref_set_key(5, "Group/K", "true")
            scene = vector_page_from_pymupdf(pdf[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertTrue(any(isinstance(item, GroupPush) and item.knockout
                            for item in scene.drawables))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "gpu-scene.pdf"
        with fitz.open() as pdf:
            vector = pdf.new_page(width=300, height=240)
            shape = vector.new_shape()
            shape.draw_rect((20, 30, 150, 170))
            shape.draw_bezier((40, 50), (80, 10), (120, 210), (180, 90))
            shape.finish(color=(1, 0, 0), fill=(0, 0.5, 1), width=2)
            shape.commit()
            text = pdf.new_page(width=300, height=240)
            text.insert_text((30, 60), "GPU text", color=(0.2, 0.4, 0.8))
            image = pdf.new_page(width=300, height=240)
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2, 2), 0)
            pixmap.clear_with(0x4080c0)
            image.insert_image((20, 20, 120, 120), pixmap=pixmap)
            clipped = pdf.new_page(width=300, height=240)
            clipped.insert_text((30, 90), "CLIPPED TEXT", fontsize=24)
            xref = clipped.get_contents()[0]
            stream = pdf.xref_stream(xref)
            pdf.update_stream(
                xref, b"q 40 130 100 50 re W n\n" + stream + b"\nQ")
            nested = pdf.new_page(width=300, height=240)
            nested.insert_text((30, 90), "NESTED CLIP", fontsize=24)
            xref = nested.get_contents()[0]
            stream = pdf.xref_stream(xref)
            pdf.update_stream(
                xref,
                b"q 20 120 200 100 re W n q 40 130 100 50 re W n\n" +
                stream + b"\nQ Q")
            with fitz.open(stream=image_mask_pdf_bytes(), filetype="pdf") as mask:
                pdf.insert_pdf(mask)
            text_clip = pdf.new_page(width=300, height=240)
            text_clip.insert_text((30, 90), "MASK", fontsize=48)
            xref = text_clip.get_contents()[0]
            stream = pdf.xref_stream(xref)
            stream = stream.replace(b"BT", b"BT\n7 Tr", 1)
            head, tail = stream.rsplit(b"Q", 1)
            pdf.update_stream(
                xref,
                head + b"0 0 1 rg 0 0 300 240 re f\nQ" + tail)
            with fitz.open(
                    stream=linear_gradient_pdf_bytes(),
                    filetype="pdf") as gradient:
                pdf.insert_pdf(gradient)
            with fitz.open(
                    stream=radial_gradient_pdf_bytes(),
                    filetype="pdf") as radial:
                pdf.insert_pdf(radial)
            with fitz.open(
                    stream=isolated_group_pdf_bytes(),
                    filetype="pdf") as group:
                pdf.insert_pdf(group)
            with fitz.open(
                    stream=soft_mask_pdf_bytes(),
                    filetype="pdf") as masked:
                pdf.insert_pdf(masked)
            stroked = pdf.new_page(width=300, height=240)
            stroked.insert_text((20, 20), "stroke source")
            pdf.update_stream(
                stroked.get_contents()[0],
                b"q 4 w 1 J 2 j [6 3] 2 d 1 0 0 RG "
                b"20 40 m 140 40 l 180 120 l S Q\n")
            stroked_text = pdf.new_page(width=300, height=240)
            stroked_text.insert_text(
                (30, 90), "OUTLINE", fontsize=36, render_mode=1,
                color=(0.8, 0.1, 0.1), border_width=1)
            clipped_stroke_text = pdf.new_page(width=300, height=240)
            clipped_stroke_text.insert_text(
                (30, 90), "CLIP", fontsize=42, render_mode=5,
                color=(0.1, 0.1, 0.8), border_width=1)
            with fitz.open(
                    stream=repeated_image_pdf_bytes(),
                    filetype="pdf") as repeated:
                pdf.insert_pdf(repeated)
            with fitz.open(
                    stream=downsampled_image_pdf_bytes(),
                    filetype="pdf") as downsampled:
                pdf.insert_pdf(downsampled)
            with fitz.open(
                    stream=similar_color_band_pdf_bytes(),
                    filetype="pdf") as similar:
                pdf.insert_pdf(similar)
            pdf.save(self.path)
        self.document = Document(str(self.path), read_only=True)

    def tearDown(self):
        self.document.close()
        self.directory.cleanup()

    def test_simple_vector_page_becomes_direct2d_commands(self):
        scene = self.document.gpu_vector_page(0)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(len(scene.paths), 1)
        path = scene.paths[0]
        self.assertEqual(path.fill_argb, 0xff0080ff)
        self.assertEqual(path.stroke_argb, 0xffff0000)
        self.assertEqual(path.stroke_width, 2)
        kinds = [command[0] for command in path.commands]
        self.assertIn("move", kinds)
        self.assertIn("line", kinds)
        self.assertIn("cubic", kinds)
        self.assertIn("close", kinds)

    def test_gpu_scene_conversion_obeys_time_budget(self):
        from pdfeditor.gpu_raster import vector_page_from_pymupdf

        scene = vector_page_from_pymupdf(
            self.document._doc[0], timeout_seconds=0)
        self.assertFalse(scene.supported)
        self.assertEqual(scene.reason, "GPU scene time budget exceeded")

    def test_scene_complexity_probe_is_cached_and_invalidated(self):
        score, operations = self.document.gpu_scene_complexity(0)
        self.assertGreaterEqual(score, operations)
        self.assertGreater(operations, 0)
        with patch(
                "pdfeditor.gpu_raster.probe_gpu_scene_complexity") as probe:
            self.assertEqual(
                self.document.gpu_scene_complexity(0), (score, operations))
            probe.assert_not_called()
            self.document.invalidate_render(0)
            probe.return_value = (123, 45)
            self.assertEqual(self.document.gpu_scene_complexity(0), (123, 45))

    def test_gpu_scene_worker_builds_pickled_snapshot_scene(self):
        from pdfeditor.gpu_scene_worker import main as worker_main

        snapshot = self.document.gpu_page_snapshot(0)
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "page.pdf"
            result_path = Path(directory) / "scene.pickle"
            snapshot_path.write_bytes(snapshot)
            self.assertEqual(worker_main([
                str(snapshot_path), str(result_path), "--timeout", "2",
            ]), 0)
            with result_path.open("rb") as stream:
                scene = pickle.load(stream)
        self.assertTrue(scene.supported, scene.reason)
        self.assertGreater(len(scene.drawables), 0)

    def test_original_font_cmap_can_recover_missing_glyph_id(self):
        from pdfeditor.gpu_raster import _encoded_glyph_id

        class Font:
            def fz_encode_character(self, codepoint):
                self.codepoint = codepoint
                return 42

            def fz_encode_character_sc(self, _codepoint):
                return 0

        font = Font()

        self.assertEqual(_encoded_glyph_id(font, ord("f")), 42)
        self.assertEqual(font.codepoint, ord("f"))

    def test_ligature_unicode_continuation_does_not_add_ink(self):
        from pymupdf import mupdf as m
        from pdfeditor.gpu_raster import _DisplayListDevice

        font = m.fz_new_base14_font("Helvetica")
        text = m.FzText()
        matrix = m.FzMatrix(12, 0, 0, 12, 20, 30)
        m.fz_show_glyph(text, font, matrix, font.fz_encode_character(ord("f")),
                       ord("f"), 0, 0, 0, 0)
        device = _DisplayListDevice((0, 0, 200, 200))
        # Keep the native owner alive while its borrowed internal view is used.
        identity = m.FzMatrix(1, 0, 0, 1, 0, 0)
        ctm = identity.internal()
        expected = device._text_outlines(text.m_internal, ctm)
        self.assertTrue(expected)
        # Both encodable and unencodable continuation characters have no ink.
        for codepoint in (ord("i"), 0x10FFFF):
            m.fz_show_glyph(text, font, matrix, -1, codepoint, 0, 0, 0, 0)
        self.assertEqual(device._text_outlines(text.m_internal, ctm),
                         expected)

    def test_missing_cmap_glyph_keeps_cpu_fallback(self):
        from pdfeditor.gpu_raster import _encoded_glyph_id

        class Font:
            def fz_encode_character(self, _codepoint):
                return 0

            def fz_encode_character_sc(self, _codepoint):
                return -1

        self.assertEqual(_encoded_glyph_id(Font(), ord("f")), -1)

    def test_complex_stroke_style_stays_on_direct2d_path(self):
        scene = self.document.gpu_vector_page(11)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("stroke-style", scene.features)
        path = scene.paths[0]
        self.assertEqual(path.stroke_width, 4)
        self.assertEqual(path.stroke_style[:4], (1, 1, 1, 2))
        self.assertEqual(path.stroke_style[4], 10)
        self.assertAlmostEqual(path.stroke_style[5], 0.5)
        self.assertEqual(path.stroke_style[6], (1.5, 0.75))

    def test_stroked_text_uses_page_space_gpu_outlines(self):
        scene = self.document.gpu_vector_page(12)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("stroked-text", scene.features)
        self.assertTrue(scene.paths)
        self.assertTrue(all(path.stroke_argb is not None
                            for path in scene.paths))
        self.assertTrue(all(path.transform is None for path in scene.paths))

    def test_stroke_and_clip_text_mode_stays_on_gpu_path(self):
        from pdfeditor.gpu_raster import ClipPop, ClipPush

        scene = self.document.gpu_vector_page(13)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("stroked-text", scene.features)
        self.assertIn("text-clip", scene.features)
        self.assertTrue(any(isinstance(item, ClipPush)
                            for item in scene.drawables))
        self.assertIsInstance(scene.drawables[-1], ClipPop)

    def test_text_page_uses_exact_glyph_outlines(self):
        scene = self.document.gpu_vector_page(1)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("text-outline-merge", scene.features)
        self.assertEqual(len(scene.paths), 1)
        self.assertTrue(all(path.fill_argb == 0xff3366cc
                            for path in scene.paths))
        self.assertTrue(all(path.transform is None for path in scene.paths))
        kinds = {command[0] for path in scene.paths
                 for command in path.commands}
        self.assertIn("move", kinds)
        self.assertIn("cubic", kinds)
        self.assertIn("close", kinds)

    def test_image_page_uses_decoded_bgra_bitmap_and_pdf_transform(self):
        from pdfeditor.gpu_raster import VectorImage

        scene = self.document.gpu_vector_page(2)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(len(scene.paths), 0)
        self.assertEqual(len(scene.drawables), 1)
        image = scene.drawables[0]
        self.assertIsInstance(image, VectorImage)
        self.assertEqual((image.width, image.height, image.stride), (2, 2, 8))
        self.assertEqual(image.pixels[:4], bytes((0xc0, 0xc0, 0xc0, 0xff)))
        self.assertEqual(image.transform, (100.0, 0.0, 0.0, 100.0, 20.0, 20.0))
        self.assertEqual(image.opacity, 1.0)

    def test_scene_is_cached_and_invalidated_with_render_data(self):
        first = self.document.gpu_vector_page(0)
        self.assertIs(first, self.document.gpu_vector_page(0))
        self.document.invalidate_render(0)
        self.assertIsNot(first, self.document.gpu_vector_page(0))

        image = self.document.gpu_vector_page(15)
        scaled = self.document.gpu_vector_page(15, 2.0)
        self.assertIsNot(image, scaled)
        self.assertIs(scaled, self.document.gpu_vector_page(15, 2.0))

    def test_aggressive_band_merge_uses_separate_scene_cache_key(self):
        self.document.invalidate_render(16)
        normal = self.document.gpu_vector_page(16)
        with patch.dict("os.environ", {"SPDF_GPU_AGGRESSIVE_BAND_MERGE": "1"}):
            aggressive = self.document.gpu_vector_page(16)
            self.assertIs(aggressive, self.document.gpu_vector_page(16))
        self.assertIsNot(normal, aggressive)
        self.assertNotIn("aggressive-band-merge", normal.features)
        self.assertIn("aggressive-band-merge", aggressive.features)
        self.assertIn((16, 1.0, False), self.document._gpu_vector_cache)
        self.assertIn((16, 1.0, True), self.document._gpu_vector_cache)

    def test_scaled_image_scene_cache_evicts_old_quality_levels(self):
        self.document.invalidate_render(15)
        with patch("pdfeditor.core.GPU_VECTOR_CACHE_BYTES", 1500):
            one = self.document.gpu_vector_page(15, 1.0)
            two = self.document.gpu_vector_page(15, 2.0)
            four = self.document.gpu_vector_page(15, 4.0)
        self.assertNotIn((15, 1.0, False), self.document._gpu_vector_cache)
        self.assertNotIn((15, 2.0, False), self.document._gpu_vector_cache)
        self.assertIn((15, 4.0, False), self.document._gpu_vector_cache)
        self.assertIs(four, self.document.gpu_vector_page(15, 4.0))
        from pdfeditor.core import _gpu_scene_cost
        self.assertEqual(self.document._gpu_vector_cache_bytes, _gpu_scene_cost(four))
        self.assertTrue(one.supported and two.supported and four.supported)

    def test_original_quality_image_scene_satisfies_higher_zoom_cache(self):
        self.document.invalidate_render(15)
        eight = self.document.gpu_vector_page(15, 8.0)
        sixteen = self.document.gpu_vector_page(15, 16.0)
        self.assertIs(eight, sixteen)
        self.assertEqual(
            list(self.document._gpu_vector_cache), [(15, 8.0, False)])

    def test_path_clip_is_recorded_in_display_order(self):
        from pdfeditor.gpu_raster import ClipPop, ClipPush, VectorPath

        scene = self.document.gpu_vector_page(3)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIsInstance(scene.drawables[0], ClipPush)
        self.assertTrue(all(isinstance(item, VectorPath)
                            for item in scene.drawables[1:-1]))
        self.assertIsInstance(scene.drawables[-1], ClipPop)
        clip = scene.drawables[0]
        self.assertEqual(clip.transform, (1.0, 0.0, 0.0, -1.0, 0.0, 240.0))
        self.assertIn("close", [command[0] for command in clip.commands])

    def test_nested_path_clips_are_balanced(self):
        from pdfeditor.gpu_raster import ClipPop, ClipPush

        scene = self.document.gpu_vector_page(4)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(sum(isinstance(item, ClipPush)
                             for item in scene.drawables), 2)
        self.assertEqual(sum(isinstance(item, ClipPop)
                             for item in scene.drawables), 2)
        self.assertIsInstance(scene.drawables[0], ClipPush)
        self.assertIsInstance(scene.drawables[1], ClipPush)
        self.assertIsInstance(scene.drawables[-2], ClipPop)
        self.assertIsInstance(scene.drawables[-1], ClipPop)

    def test_colored_image_mask_becomes_premultiplied_gpu_bitmap(self):
        from pdfeditor.gpu_raster import VectorImage

        scene = self.document.gpu_vector_page(5)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(len(scene.drawables), 1)
        image = scene.drawables[0]
        self.assertIsInstance(image, VectorImage)
        self.assertEqual((image.width, image.height, image.stride), (8, 8, 32))
        self.assertEqual(image.transform,
                         (100.0, 0.0, 0.0, 100.0, 20.0, 120.0))
        self.assertEqual(image.pixels[:4], bytes((0, 0, 0, 0)))
        self.assertEqual(image.pixels[4 * 4:4 * 5], bytes((255, 0, 0, 255)))

    def test_text_clip_uses_combined_exact_glyph_outlines(self):
        from pdfeditor.gpu_raster import ClipPop, ClipPush, VectorPath

        scene = self.document.gpu_vector_page(6)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIsInstance(scene.drawables[0], ClipPush)
        self.assertIsNone(scene.drawables[0].transform)
        self.assertTrue(any(command[0] == "cubic"
                            for command in scene.drawables[0].commands))
        self.assertTrue(any(isinstance(item, VectorPath)
                            for item in scene.drawables[1:-1]))
        self.assertIsInstance(scene.drawables[-1], ClipPop)

    def test_linear_gradient_keeps_gpu_scene_as_direct2d_primitive(self):
        from pdfeditor.gpu_raster import (ClipPop, ClipPush,
                                          VectorImage, VectorLinearGradient,
                                          VectorPath)

        scene = self.document.gpu_vector_page(7)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("shading", scene.features)
        self.assertIn("vector-shading", scene.features)
        self.assertIn("gradient-primitive", scene.features)
        self.assertIn("gradient-clip-merge", scene.features)
        self.assertNotIn("raster-shading", scene.features)
        self.assertIn("vector-clip", scene.features)
        self.assertEqual(sum(isinstance(item, ClipPush)
                             for item in scene.drawables), 1)
        self.assertEqual(sum(isinstance(item, ClipPop)
                             for item in scene.drawables), 1)
        gradients = [item for item in scene.drawables
                     if isinstance(item, VectorLinearGradient)]
        self.assertEqual(len(gradients), 1)
        gradient = gradients[0]
        self.assertEqual(len(gradient.stops), 65)
        self.assertEqual(gradient.stops[0][1], 0xffff0000)
        self.assertEqual(gradient.stops[-1][1], 0xff0000ff)
        bands = [item for item in scene.drawables
                 if isinstance(item, VectorPath)]
        self.assertEqual(bands, [])
        self.assertFalse(any(isinstance(item, VectorImage)
                             for item in scene.drawables))

    def test_linear_gradient_does_not_use_image_scene_limit(self):
        self.document.invalidate_render(7)
        with patch("pdfeditor.gpu_raster.MAX_GPU_IMAGE_BYTES", 1):
            scene = self.document.gpu_vector_page(7)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("vector-shading", scene.features)

    def test_radial_gradient_keeps_gpu_scene_as_direct2d_primitive(self):
        from pdfeditor.gpu_raster import (ClipPop, ClipPush,
                                          VectorImage, VectorPath,
                                          VectorRadialGradient)

        scene = self.document.gpu_vector_page(8)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("shading", scene.features)
        self.assertIn("vector-shading", scene.features)
        self.assertIn("gradient-primitive", scene.features)
        self.assertIn("vector-clip", scene.features)
        self.assertIsInstance(scene.drawables[0], ClipPush)
        gradients = [item for item in scene.drawables
                     if isinstance(item, VectorRadialGradient)]
        self.assertEqual(len(gradients), 1)
        gradient = gradients[0]
        self.assertEqual(len(gradient.stops), 65)
        self.assertEqual(gradient.stops[0][1], 0xffffff00)
        self.assertEqual(gradient.stops[-1][1], 0xff0000ff)
        bands = [item for item in scene.drawables
                 if isinstance(item, VectorPath)]
        self.assertEqual(bands, [])
        self.assertFalse(any(isinstance(item, VectorImage)
                             for item in scene.drawables))
        self.assertIsInstance(scene.drawables[-1], ClipPop)

    def test_isolated_normal_transparency_group_uses_opacity_layer(self):
        from pdfeditor.gpu_raster import (ClipPop, ClipPush, GroupPop,
                                          GroupPush, VectorPath)

        scene = self.document.gpu_vector_page(9)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("transparency-group", scene.features)
        self.assertIsInstance(scene.drawables[0], GroupPush)
        self.assertAlmostEqual(scene.drawables[0].opacity, 1.0)
        self.assertIsInstance(scene.drawables[1], GroupPush)
        self.assertAlmostEqual(scene.drawables[1].opacity, 0.5)
        self.assertIsInstance(scene.drawables[2], ClipPush)
        paths = [item for item in scene.drawables
                 if isinstance(item, VectorPath)]
        self.assertEqual(len(paths), 2)
        self.assertTrue(all((item.fill_argb >> 24) == 255 for item in paths))
        self.assertIsInstance(scene.drawables[-3], ClipPop)
        self.assertIsInstance(scene.drawables[-2], GroupPop)
        self.assertIsInstance(scene.drawables[-1], GroupPop)

    def test_luminosity_soft_mask_stays_in_gpu_scene(self):
        from pdfeditor.gpu_raster import (ClipPop, GroupPop, GroupPush,
                                          MaskBegin, MaskEnd, VectorPath)

        scene = self.document.gpu_vector_page(10)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("soft-mask", scene.features)
        self.assertIsInstance(scene.drawables[0], MaskBegin)
        self.assertTrue(scene.drawables[0].luminosity)
        self.assertEqual(scene.drawables[0].area, (20.0, 20.0, 280.0, 220.0))
        self.assertIsInstance(scene.drawables[1], GroupPush)
        self.assertTrue(any(isinstance(item, VectorPath)
                            for item in scene.drawables[2:]))
        mask_end = next(index for index, item in enumerate(scene.drawables)
                        if isinstance(item, MaskEnd))
        self.assertIsInstance(scene.drawables[mask_end - 1], GroupPop)
        self.assertIsInstance(scene.drawables[-1], ClipPop)

    def test_oversized_image_scene_uses_complete_cpu_fallback(self):
        self.document.invalidate_render(2)
        with patch("pdfeditor.gpu_raster.MAX_GPU_IMAGE_BYTES", 1):
            scene = self.document.gpu_vector_page(2)
        self.assertFalse(scene.supported)
        self.assertIn("GPU scene limit", scene.reason)

    def test_repeated_image_xobject_reuses_decoded_pixels(self):
        from pdfeditor.gpu_raster import VectorImage

        self.document.invalidate_render(14)
        with patch("pdfeditor.gpu_raster.MAX_GPU_IMAGE_BYTES", 20):
            scene = self.document.gpu_vector_page(14)
        self.assertTrue(scene.supported, scene.reason)
        images = [item for item in scene.drawables
                  if isinstance(item, VectorImage)]
        self.assertEqual(len(images), 2)
        self.assertIs(images[0].pixels, images[1].pixels)
        self.assertEqual(images[0].transform,
                         (20.0, 0.0, 0.0, 20.0, 20.0, 40.0))
        self.assertEqual(images[1].transform,
                         (20.0, 0.0, 0.0, 20.0, 60.0, 40.0))

    def test_downsampled_image_can_stay_within_scene_limit(self):
        from pdfeditor.gpu_raster import VectorImage

        self.document.invalidate_render(15)
        with patch("pdfeditor.gpu_raster.MAX_GPU_IMAGE_BYTES", 300):
            scene = self.document.gpu_vector_page(15)
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn("image-downsample", scene.features)
        image = next(item for item in scene.drawables
                     if isinstance(item, VectorImage))
        self.assertEqual((image.width, image.height, image.stride), (8, 8, 32))
        self.assertEqual(len(image.pixels), 256)
        self.assertEqual(image.transform, (8.0, 0.0, -0.0, 8.0, 20.0, 52.0))

    def test_downsampled_image_quality_tracks_requested_raster_scale(self):
        from pdfeditor.gpu_raster import VectorImage

        self.document.invalidate_render(15)
        scene = self.document.gpu_vector_page(15, 4.0)
        self.assertTrue(scene.supported, scene.reason)
        self.assertEqual(scene.raster_scale, 4.0)
        image = next(item for item in scene.drawables
                     if isinstance(item, VectorImage))
        self.assertEqual((image.width, image.height, image.stride), (32, 32, 128))


if __name__ == "__main__":
    unittest.main()
