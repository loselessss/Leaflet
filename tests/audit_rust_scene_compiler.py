"""Audit the experimental owned compiler, without claiming rendered coverage."""
import argparse
import json
import statistics
import time
from pathlib import Path


def main():
    import pymupdf
    from pdfeditor.gpu_raster import vector_page_from_pymupdf
    from pdfeditor._path_packer import compile_scene
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',nargs='+',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    records=[]
    for filename in args.pdf:
        with pymupdf.open(filename) as document:
            source=vector_page_from_pymupdf(document[0],packed_paths=True,
                native_paths=True,native_text=True)
        samples=[]
        golden=None
        for iteration in range(8):
            start=time.perf_counter();compiled=compile_scene(source)
            compiled_ms=(time.perf_counter()-start)*1000
            packet=compiled.to_bytes()
            if golden is None:golden=packet
            assert packet==golden
            assert compiled.source_command_count==len(source.drawables)
            assert compiled.viewport_plan((-1e12,-1e12,1e12,1e12),2.)==list(range(compiled.command_count))
            if iteration:samples.append(compiled_ms)
        row=dict(file=filename.name,commands=compiled.command_count,
                 resources=compiled.resource_count,resource_bytes=compiled.resource_bytes,
                 image_bytes=compiled.image_bytes,packet_bytes=len(packet),
                 compile_samples_ms=samples,compile_median_ms=statistics.median(samples),
                 deterministic=True,rendered=False)
        records.append(row);print(json.dumps(row),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(records,indent=2),encoding='utf-8')


if __name__=='__main__':main()
