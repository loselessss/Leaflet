"""Fresh-process comparison of JSON/zlib and direct Rust-packet scene storage."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import zlib
from unittest.mock import patch


def legacy_encode(scene):
    from pdfeditor import scene_disk_cache as cache
    raw = json.dumps(cache._encode(scene), separators=(',', ':'), allow_nan=False).encode()
    return zlib.compress(raw, 1)


def legacy_decode(data, page):
    from pdfeditor import scene_disk_cache as cache
    payload = json.loads(zlib.decompress(data))
    return cache._decode(payload, cache._types(), cache._source_pixels(page, payload))


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, (time.perf_counter() - start) * 1000


def child(path, mode):
    import pymupdf
    from pdfeditor.rust_scene_compiler import compile_vector_page
    from pdfeditor import scene_disk_cache as cache
    with pymupdf.open(path) as doc:
        scene = compile_vector_page(doc[0])
    assert scene.supported, scene.reason
    encode = legacy_encode if mode == 'json' else cache._serialize_scene
    decode = legacy_decode if mode == 'json' else cache._deserialize_scene
    with tempfile.TemporaryDirectory() as directory, \
            patch('pdfeditor.paths.user_data_dir', return_value=directory), \
            patch.object(cache, '_limit', return_value=100 * 1024 * 1024), \
            patch.object(cache, '_serialize_scene', encode), \
            patch.object(cache, '_deserialize_scene', decode):
        blob, encode_ms = timed(encode, scene)
        restored, decode_ms = timed(decode, blob, None)
        assert restored == scene
        _, save_ms = timed(cache.save, 'benchmark', scene)
        restored, load_ms = timed(cache.load, 'benchmark')
        assert restored == scene
        result = dict(document=path.name, mode=mode, encode_ms=encode_ms,
                      decode_ms=decode_ms, save_ms=save_ms, load_ms=load_ms,
                      stored_bytes=len(blob), packet_bytes=len(scene.compiled_packet),
                      exact_packet=restored.compiled_packet == scene.compiled_packet)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='+', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--child', choices=('json', 'binary'))
    args = parser.parse_args()
    if args.child:
        return child(args.pdf[0], args.child)
    if args.output is None or args.runs < 1:
        parser.error('--output and positive --runs required')
    rows = []
    for path in args.pdf:
        for run in range(args.runs):
            for mode in (('json', 'binary') if run % 2 == 0 else ('binary', 'json')):
                process = subprocess.run([sys.executable, '-m', 'tests.benchmark_scene_storage',
                    str(path), '--child', mode], check=True, capture_output=True,
                    text=True, encoding='utf-8', errors='replace')
                row = json.loads(process.stdout.strip().splitlines()[-1])
                row['run'] = run
                rows.append(row)
                print(json.dumps(row), flush=True)
    medians = []
    for document in dict.fromkeys(row['document'] for row in rows):
        for mode in ('json', 'binary'):
            samples = [r for r in rows if r['document'] == document and r['mode'] == mode]
            medians.append(dict(document=document, mode=mode,
                **{k: statistics.median(r[k] for r in samples) for k in samples[0]
                   if k.endswith('_ms') or k.endswith('_bytes')}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(runs=rows, medians=medians), indent=2), encoding='utf-8')
    print(json.dumps(dict(medians=medians)), flush=True)


if __name__ == '__main__':
    main()
