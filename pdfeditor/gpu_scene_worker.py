"""Out-of-process GPU extraction from an immutable, privately owned PDF."""

import argparse
import os
import pickle
import time

import pymupdf

from .gpu_raster import vector_page_from_pymupdf, refine_page_images, VectorPage


def main(argv=None):
    parser = argparse.ArgumentParser(prog="Leaflet GPU scene worker")
    parser.add_argument("snapshot")
    parser.add_argument("result")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--aggressive-band-merge", action="store_true")
    parser.add_argument("--base-scene")
    parser.add_argument("--disk-cache-key")
    args = parser.parse_args(argv)

    document = pymupdf.open(args.snapshot, filetype="pdf")
    try:
        page = document[args.page]
        started = time.monotonic()
        scene = None
        if args.disk_cache_key:
            from .scene_disk_cache import load
            scene = load(args.disk_cache_key, page)
        cache_hit = scene is not None
        if scene is None and args.base_scene:
            # This file is written by our parent into the private worker job.
            with open(args.base_scene, "rb") as stream:
                base = pickle.load(stream)
            if isinstance(base, VectorPage):
                scene = refine_page_images(page, base, args.scale, args.timeout)
        if scene is None:
            scene = vector_page_from_pymupdf(
                page, args.scale,
                timeout_seconds=max(0.0, args.timeout - (time.monotonic() - started)),
                aggressive_band_merge=args.aggressive_band_merge)
        if args.disk_cache_key and scene.supported and not cache_hit:
            from .scene_disk_cache import save
            save(args.disk_cache_key, scene)
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
