"""Small synthetic PDFs for extended native GPU coverage."""
import pymupdf
from tests import test_gpu_raster as original
from tests.test_type3_gpu import type3_pdf


def stream(document, data, dictionary="<< >>"):
    xref = document.get_new_xref()
    document.update_object(xref, dictionary)
    document.update_stream(xref, data)
    return xref


def dashed_hairline_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=180)
        page.set_contents(stream(document,
            b"0 w [6 4] 0 d 15 30 m 220 30 l S\n"
            b"q 0.8 0.2 0.1 RG 1 .25 0 1 0 0 cm 20 70 m 180 70 l S Q"))
        return document.tobytes()


def background_blend_pdf(mode="Multiply"):
    with pymupdf.open(stream=original.nonisolated_masked_image_pdf_bytes(mode), filetype="pdf") as document:
        form = document[0].get_xobjects()[0][0]
        data = document.xref_stream(form)
        document.xref_set_key(form, 'Resources/ExtGState',
                             '<< /InnerBlend << /BM /Difference >> >>')
        document.update_stream(form, b"\n".join([data, b'q /InnerBlend gs', data, b'Q']) + b"\n")
        return document.tobytes()


def mesh_pdf(*, kind=4, transformed=False, opacity=1., nonlinear=False, custom_domain=False):
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=180)
        if kind == 4:
            payload = bytes([0, 20, 20, 255, 0, 0, 0, 230, 20, 0, 255, 0,
                             0, 100, 230, 0, 0, 255])
            if nonlinear:
                payload = bytes([0, 20, 20, 0, 0, 230, 20, 255, 0, 100, 230, 0])
        elif kind == 5:
            payload = bytes([20, 20, 255, 0, 0, 230, 20, 0, 255, 0,
                             20, 230, 0, 0, 255, 230, 230, 255, 255, 0])
        else:
            points = [(20, 20), (80, 10), (160, 10), (230, 20),
                      (240, 80), (240, 160), (230, 230), (160, 240),
                      (80, 240), (20, 230), (10, 160), (10, 80)]
            if kind == 7:
                points += [(80, 80), (160, 80), (160, 160), (80, 160)]
            payload = bytes([0, *[value for point in points for value in point],
                             255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 0])
        function = "<< /FunctionType 2 /Domain [0 1] /Range [0 1 0 1 0 1] /C0 [0 1 0] /C1 [1 0 1] /N 4 >>"
        domain = "0 1"
        if custom_domain:
            xref = stream(document, b"{ 2 sub 2 div dup mul dup mul dup 1 exch sub 1 index }",
                          "<< /FunctionType 4 /Domain [2 4] /Range [0 1 0 1 0 1] >>")
            function, domain = f"{xref} 0 R", "2 4"
        dictionary = (f"<< /ShadingType {kind} /ColorSpace /DeviceRGB /BitsPerCoordinate 8 "
                      + (f"/BitsPerComponent 8 /Decode [0 240 0 180 {domain}] /Function {function} "
                         if nonlinear else "/BitsPerComponent 8 /Decode [0 240 0 180 0 1 0 1 0 1] ")
                      + ("/VerticesPerRow 2 " if kind == 5 else "/BitsPerFlag 8 ") + ">>")
        shading = stream(document, payload, dictionary)
        resources = int(document.xref_get_key(page.xref, "Resources")[1].split()[0])
        document.update_object(resources, f"<< /Shading << /S1 {shading} 0 R >> "
            f"/ExtGState << /GS << /ca {opacity} >> >> >>")
        content = b"q /GS gs " + (b".8 .15 -.1 .8 25 5 cm " if transformed else b"") + b"/S1 sh Q"
        page.set_contents(stream(document, content))
        return document.tobytes()


def gradient_opacity_pdf(isolated=True):
    with pymupdf.open(stream=original.linear_gradient_pdf_bytes(), filetype='pdf') as document:
        page = document[0]
        resources = document.xref_get_key(page.xref, 'Resources')[1]
        form = stream(document, page.read_contents(),
            f'<< /Type /XObject /Subtype /Form /BBox [0 0 {page.rect.width} {page.rect.height}] '
            f'/Resources {resources} /Group << /S /Transparency /I {str(isolated).lower()} >> >>')
        document.xref_set_key(page.xref, 'Resources',
            f'<< /XObject << /F {form} 0 R >> /ExtGState << /GS << /ca .375 /CA .375 >> >> >>')
        page.set_contents(stream(document, b'q /GS gs /F Do Q'))
        return document.tobytes()


def cases():
    return {
        "Gradient opacity": gradient_opacity_pdf(),
        "Nonisolated gradient opacity": gradient_opacity_pdf(False),
        "CMYK opacity": original.cmyk_group_pdf_bytes(alpha=.5),
        "Backdrop blend": background_blend_pdf(),
        **{"Backdrop " + mode: background_blend_pdf(mode)
           for mode in ("Screen", "Overlay", "Color", "Luminosity")},
        **{"CMYK " + mode: original.cmyk_group_pdf_bytes(alpha=.5, blend_mode=mode)
           for mode in ("Multiply", "Screen", "Overlay")},
        "Hairline dash": dashed_hairline_pdf(),
        **{"Type3 " + name: type3_pdf(variant=name)
           for name in ("vector", "colored", "multiple", "clip", "bitmap")},
        "Type3 translucent": type3_pdf(variant="multiple", opacity=.4, rotated=True),
        **{"Mesh " + str(kind): mesh_pdf(kind=kind) for kind in (4, 5, 6, 7)},
        "Mesh transformed": mesh_pdf(transformed=True, opacity=.65),
        "Mesh nonlinear": mesh_pdf(nonlinear=True),
        "Mesh nonlinear domain": mesh_pdf(nonlinear=True, custom_domain=True),
        "Pattern": original.tiling_pattern_pdf_bytes(),
        "Soft mask": original.soft_mask_pdf_bytes(),
        "Blend mask": original.blended_mask_pdf_bytes(),
        "Image mask": original.nonisolated_masked_image_pdf_bytes(),
    }
