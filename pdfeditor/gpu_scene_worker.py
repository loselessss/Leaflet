"""Out-of-process GPU extraction from an immutable, privately owned PDF."""

import argparse
import os
import pickle
import time

import pymupdf

from .rust_scene_compiler import compile_vector_page


def main(argv=None):
    parser = argparse.ArgumentParser(prog="Leaflet GPU scene worker")
    parser.add_argument("snapshot")
    parser.add_argument("result")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--aggressive-band-merge", action="store_true")
    parser.add_argument("--viewport", type=float, nargs=4)
    parser.add_argument("--base-scene")  # Older callers may send a reference-extractor recipe; Rust rebuilds from PDF.
    parser.add_argument("--disk-cache-key")
    parser.add_argument("--transfer-workers", type=int, choices=(0, 1, 2, 4), default=2)
    args = parser.parse_args(argv)

    document = pymupdf.open(args.snapshot, filetype="pdf")
    try:
        page = document[args.page]
        started = time.monotonic()
        scene = None
        if args.disk_cache_key and not args.viewport:
            from .scene_disk_cache import load
            scene = load(args.disk_cache_key, page)
        cache_hit = scene is not None
        if scene is None:
            scene = compile_vector_page(
                page, args.scale,
                timeout_seconds=max(0.0, args.timeout - (time.monotonic() - started)),
                aggressive_band_merge=args.aggressive_band_merge, viewport=args.viewport)
        if args.disk_cache_key and not args.viewport and scene.supported and not cache_hit:
            from .scene_disk_cache import save
            save(args.disk_cache_key, scene)
    finally:
        document.close()
    if scene.supported:
        # Count the immutable scene in the worker, not on the GUI event loop
        # when a potentially large prefetched result arrives.
        from .core import _gpu_scene_cost
        _gpu_scene_cost(scene)
    temporary = args.result + ".tmp"
    try:
        with open(temporary, "wb") as stream:
            from .scene_transfer import dump
            dump(scene, stream, parallel_workers=args.transfer_workers)
        os.replace(temporary, args.result)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
