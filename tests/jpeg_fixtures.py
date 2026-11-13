"""Small, deterministic encoded-image PDFs for native JPEG coverage."""
import io
import pymupdf
from PIL import Image, ImageDraw


def jpeg_bytes(size=(192, 160), *, subsampling=2, progressive=False, mode='RGB'):
    image = Image.new('RGB', size)
    width, height = size
    image.putdata([(x * 255 // max(1, width - 1), y * 255 // max(1, height - 1),
                    (x * 7 + y * 3) % 256) for y in range(height) for x in range(width)])
    draw = ImageDraw.Draw(image)
    draw.rectangle((width // 8, height // 8, width // 2, height // 2), fill='#e83422')
    draw.ellipse((width // 3, height // 3, width * 7 // 8, height * 7 // 8), fill='#247cdd')
    if mode != 'RGB':
        image = image.convert(mode)
    output = io.BytesIO()
    image.save(output, 'JPEG', quality=90, subsampling=subsampling, progressive=progressive)
    return output.getvalue()


def jpeg_pdf(data=None, *, rotation=0, decode=False, color_transform=None, alpha=False, device_rgb=True):
    data = data or jpeg_bytes()
    with pymupdf.open() as doc:
        page = doc.new_page(width=256, height=256)
        xref = page.insert_image((20, 30, 236, 210), stream=data, rotate=rotation)
        # PyMuPDF 2 inserts an explicit sRGB ICC profile; ordinary PDF
        # DeviceRGB images are the eligible fast path under test here.
        if device_rgb and Image.open(io.BytesIO(data)).mode == 'RGB':
            doc.xref_set_key(xref, 'ColorSpace', '/DeviceRGB')
        if decode:
            doc.xref_set_key(xref, 'Decode', '[1 0 0 1 0 1]')
        if color_transform is not None:
            doc.xref_set_key(xref, 'DecodeParms', f'<< /ColorTransform {color_transform} >>')
        if alpha:
            mask = doc.get_new_xref()
            doc.update_object(mask, '<< /Type /XObject /Subtype /Image /Width 192 /Height 160 '
                                   '/ColorSpace /DeviceGray /BitsPerComponent 8 >>')
            doc.update_stream(mask, bytes([128]) * (192 * 160))
            doc.xref_set_key(xref, 'SMask', f'{mask} 0 R')
        return doc.tobytes()
