"""Headless PDF raster server; never imports Qt or OCR engines."""
import json
import sys

MAX_PAGE_BYTES = 256 * 1024 * 1024


def main():
    import pymupdf
    source = sys.stdin.buffer
    output = sys.stdout.buffer
    document = None
    try:
        job = json.loads(source.readline(65536))
        document = pymupdf.open(job["path"])
        if document.needs_pass and not document.authenticate(job.get("password") or ""):
            raise ValueError("PDF password is incorrect")
        for line in source:
            request = json.loads(line)
            page = document[request["page"]]
            longest = max(page.rect.width, page.rect.height)
            zoom = job.get("zoom") or max(1., min(6., job["target"] / longest))
            width, height = page.rect.width * zoom, page.rect.height * zoom
            if width * height * 3 > MAX_PAGE_BYTES:
                raise ValueError("OCR page exceeds the pixel memory limit")
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False,
                                  colorspace=pymupdf.csRGB)
            pixels = pix.samples
            if len(pixels) > MAX_PAGE_BYTES:
                raise ValueError("OCR page exceeds the pixel memory limit")
            header = dict(width=pix.width, height=pix.height, zoom=zoom, size=len(pixels))
            output.write(json.dumps(header).encode() + b"\n")
            output.write(pixels)
            output.flush()
            del pixels, pix
        return 0
    except BrokenPipeError:
        return 0
    except Exception as error:
        try:
            output.write(json.dumps(dict(error=str(error))).encode() + b"\n")
            output.flush()
        except BrokenPipeError:
            pass
        return 1
    finally:
        if document is not None:
            document.close()


if __name__ == "__main__":
    sys.exit(main())
