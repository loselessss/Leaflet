"""Out-of-process GPU scene extraction from an isolated one-page snapshot."""

import argparse
import os
import pickle
import time

import pymupdf

from .gpu_raster import vector_page_from_pymupdf, refine_page_images, VectorPage


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sPDF GPU scene worker")
    parser.add_argument("snapshot")
    parser.add_argument("result")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--aggressive-band-merge", action="store_true")
    parser.add_argument("--base-scene")
    args = parser.parse_args(argv)

    with open(args.snapshot, "rb") as stream:
        data = stream.read()
    document = pymupdf.open("pdf", data)
    try:
        started = time.monotonic()
        scene = None
        if args.base_scene:
            # This file is written by our parent into the private worker job.
            with open(args.base_scene, "rb") as stream:
                base = pickle.load(stream)
            if isinstance(base, VectorPage):
                scene = refine_page_images(document[0], base, args.scale, args.timeout)
        if scene is None:
            scene = vector_page_from_pymupdf(
                document[0], args.scale,
                timeout_seconds=max(0.0, args.timeout - (time.monotonic() - started)),
                aggressive_band_merge=args.aggressive_band_merge)
    finally:
        document.close()
    temporary = args.result + ".tmp"
    try:
        with open(temporary, "wb") as stream:
            pickle.dump(scene, stream, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temporary, args.result)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
