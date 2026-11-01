"""Native PDF input → Rust policy/compiler → opaque GPU scene packet."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time


def compile_vector_page(page, raster_scale=1., timeout_seconds=None, *, viewport=None,
                        aggressive_band_merge=False):
    """Application compiler. Python owns only job control and the opaque packet."""
    from .gpu_raster import VectorPage
    from .mupdf_path import compile_page
    scale=max(1., float(raster_scale))
    started=time.monotonic()
    if viewport is not None:
        from .gpu_viewport import validate_viewport
        viewport=validate_viewport(viewport,page.rect)
    try:
        if timeout_seconds is not None and timeout_seconds<=0:
            raise TimeoutError
        compiled=compile_page(page,scale,viewport,timeout_seconds)
        packet=compiled.to_bytes()
        if timeout_seconds is not None and time.monotonic()-started>timeout_seconds:
            raise TimeoutError
        features=list(compiled.features)
        if viewport is not None:
            features.append('viewport-images')
        return VectorPage(True,features=tuple(features),raster_scale=scale,
                          viewport=viewport,compiled_packet=packet,
                          command_count=compiled.command_count)
    except TimeoutError:
        return VectorPage(False,reason='GPU scene time budget exceeded',raster_scale=scale)
    except (ImportError,OSError,RuntimeError,ValueError,MemoryError) as error:
        if 'GPU scene time budget exceeded' in str(error) or (timeout_seconds is not None and time.monotonic()-started>=timeout_seconds):
            return VectorPage(False,reason='GPU scene time budget exceeded',raster_scale=scale)
        return VectorPage(False,reason='unsupported Rust GPU scene: '+str(error),raster_scale=scale)


def compile_document(path, *, page_index=0, scale=1.):
    import pymupdf
    from .mupdf_path import compile_page
    with pymupdf.open(path) as document:
        started=time.perf_counter()
        compiled=compile_page(document[page_index],scale)
        elapsed=(time.perf_counter()-started)*1000
    return compiled,elapsed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--page',type=int,default=0)
    parser.add_argument('--scale',type=float,default=1.)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    scene,elapsed=compile_document(args.pdf,page_index=args.page,scale=args.scale)
    data=scene.to_bytes()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=args.output.parent,delete=False) as stream:
            temporary=stream.name
            stream.write(data)
        os.replace(temporary,args.output)
        temporary=None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    print(json.dumps(dict(commands=scene.command_count,resources=scene.resource_count,
        resource_bytes=scene.resource_bytes,image_bytes=scene.image_bytes,
        packet_bytes=len(data),compile_ms=elapsed,rendered=False,
        input_adapter='native_mupdf')))


if __name__=='__main__':
    main()
