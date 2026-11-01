"""Measure fresh-process reader jobs, including launch/import and private IPC."""
import argparse,ctypes,json,os,statistics,subprocess,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
import pymupdf
from pdfeditor.rust_scene_compiler import compile_vector_page
from pdfeditor.scene_worker_result import load
from pdfeditor import scene_disk_cache as cache


def peak_mib(handle):
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_uint32),('faults',ctypes.c_uint32)]+[(n,ctypes.c_size_t) for n in
            ('peak_rss','rss','peak_paged','paged','peak_nonpaged','nonpaged','commit','peak_commit','private')]
    data=Counters();data.cb=ctypes.sizeof(data)
    fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    fn.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_uint32]
    return data.peak_rss/1048576 if fn(ctypes.c_void_p(int(handle)),ctypes.byref(data),data.cb) else None


def command(mode):
    if mode=='python':
        # Self-report: sys.executable may be the small Windows venv redirector.
        program="""import os
from pdfeditor import settings
settings.PATH=os.environ['LEAFLET_BENCH_SETTINGS']
from pdfeditor.gpu_scene_worker import main
status=main()
import ctypes
class Counters(ctypes.Structure):
    _fields_=[('cb',ctypes.c_uint32),('faults',ctypes.c_uint32)]+[(n,ctypes.c_size_t) for n in
        ('peak_rss','rss','peak_paged','paged','peak_nonpaged','nonpaged','commit','peak_commit','private')]
data=Counters();data.cb=ctypes.sizeof(data)
ok=ctypes.WinDLL('psapi').GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(data),data.cb)
assert ok
with open(os.environ['LEAFLET_BENCH_MEMORY'],'w') as stream:stream.write(str(data.peak_rss/1048576))
raise SystemExit(status)
"""
        return [sys.executable,'-c',program]
    root=Path(__file__).resolve().parents[1]
    return [str(root/'native/bin/leaflet-gpu-scene-worker.exe'),
        '--bridge',str(root/'native/bin/leaflet_mupdf_path.dll'),
        '--mupdf',str(Path(pymupdf.__file__).parent/'mupdfcpp64.dll'),
        '--expected-mupdf',pymupdf.VersionFitz]


def measure(path,mode,cached,root,expected):
    output=root/'result.scene';output.unlink(missing_ok=True)
    env=dict(os.environ,LOCALAPPDATA=str(root),LEAFLET_BENCH_SETTINGS=str(root/'settings.json'),LEAFLET_BENCH_MEMORY=str(root/'peak.txt'))
    options=['--timeout','20']
    if cached:options+=['--disk-cache-key','benchmark']
    if mode=='rust':options+=['--cache-db',str(root/'sPDF/cache/gpu-scenes.sqlite3'),'--cache-limit',str(100*1024*1024)]
    with (root/'stderr.log').open('wb') as errors:
        started=time.perf_counter();process=subprocess.Popen(command(mode)+[str(path),str(output),*options],
            env=env,stdout=subprocess.DEVNULL,stderr=errors,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        peak=None
        while True:
            value=peak_mib(process._handle)
            if value is not None:peak=value if peak is None else max(peak,value)
            if process.poll() is not None:break
            if time.perf_counter()-started>30:process.kill();process.wait();raise TimeoutError('worker benchmark timeout')
            time.sleep(.005)
        elapsed=(time.perf_counter()-started)*1000
    if process.returncode:raise RuntimeError((root/'stderr.log').read_text(encoding='utf-8',errors='replace'))
    if mode=='python':peak=float((root/'peak.txt').read_text())
    started=time.perf_counter()
    with output.open('rb') as stream:actual=load(stream)
    restore_ms=(time.perf_counter()-started)*1000
    assert actual==expected,(mode,actual.reason)
    return dict(document=path.name,mode=mode,cached=cached,worker_ms=elapsed,
        restore_ms=restore_ms,total_ms=elapsed+restore_ms,peak_rss_mib=peak,result_bytes=output.stat().st_size,exact=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('pdf',type=Path,nargs='+')
    parser.add_argument('--runs',type=int,default=5);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();rows=[]
    for path in args.pdf:
        with pymupdf.open(path) as doc:expected=compile_vector_page(doc[0])
        assert expected.supported,expected.reason
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'settings.json').write_text('{"disk_cache_mb":100}',encoding='utf-8')
            with patch('pdfeditor.paths.user_data_dir',return_value=str(root/'sPDF')),patch.object(cache,'_limit',return_value=100*1024*1024):
                cache.save('benchmark',expected)
            for cached in (False,True):
                for run in range(args.runs):
                    for mode in (('python','rust') if run%2==0 else ('rust','python')):
                        row=measure(path,mode,cached,root,expected);row['run']=run;rows.append(row);print(json.dumps(row),flush=True)
    medians=[]
    for document in dict.fromkeys(r['document'] for r in rows):
        for cached in (False,True):
            for mode in ('python','rust'):
                samples=[r for r in rows if r['document']==document and r['cached']==cached and r['mode']==mode]
                medians.append(dict(document=document,cached=cached,mode=mode,**{
                    k:statistics.median(r[k] for r in samples if r[k] is not None)
                    for k in ('worker_ms','restore_ms','total_ms','peak_rss_mib','result_bytes')}))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(runs=rows,medians=medians),indent=2),encoding='utf-8')
    print(json.dumps(dict(medians=medians)),flush=True)


if __name__=='__main__':main()
