"""Fresh-process reference vs complete native-input Rust compiler comparison."""
import argparse,json,os,pickle,statistics,subprocess,sys,time
from pathlib import Path


def child(mode,path):
    os.environ['QT_QPA_PLATFORM']='offscreen'
    import ctypes,pymupdf
    from PyQt5.QtWidgets import QApplication
    from pdfeditor.d2d_backend import D2DSurface
    from pdfeditor.reader_view import ReaderPageView
    from pdfeditor.gpu_raster import vector_page_from_pymupdf
    from pdfeditor.rust_scene_compiler import compile_vector_page
    from pdfeditor.scene_transfer import dumps
    from pdfeditor.core import _gpu_scene_cost
    from tests.benchmark_gpu_pipeline import render_sample,process_memory
    app=QApplication([])
    u=ctypes.WinDLL('user32');u.CreateWindowExW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)];u.CreateWindowExW.restype=ctypes.c_void_p;u.DestroyWindow.argtypes=[ctypes.c_void_p]
    h=u.CreateWindowExW(0,'STATIC','Compiler benchmark',0,0,0,1200,900,None,None,None,None)
    surface=D2DSurface(h,1200,900);view=ReaderPageView(use_opengl=False);view._d2d_surface=surface
    started=time.perf_counter()
    with pymupdf.open(path) as doc:
        page=doc[0];size=(page.rect.width,page.rect.height)
        if mode=='rust':scene=compile_vector_page(page)
        else:scene=vector_page_from_pymupdf(page,packed_paths=True,native_paths=True,native_text=True)
    if not scene.supported:raise ValueError(scene.reason)
    compile_ms=(time.perf_counter()-started)*1000
    cost=_gpu_scene_cost(scene)
    transfer_started=time.perf_counter();wire=dumps(scene,parallel_workers=2);scene=pickle.loads(wire)
    transfer_ms=(time.perf_counter()-transfer_started)*1000
    view._page_sizes[0]=size;prepare_started=time.perf_counter();view._native_vector_draws(0,scene)
    upload_ms=(time.perf_counter()-prepare_started)*1000;retained=view._d2d_vector_paths[0][3]
    scale=min(1200/size[0],900/size[1]);transform=(scale,0.,0.,scale,(1200-size[0]*scale)/2,(900-size[1]*scale)/2)
    draw_ms,first_ms,_,pixels=render_sample(surface,retained,transform,1200,900,'completed',.001)
    result=dict(mode=mode,document=Path(path).name,compile_ms=compile_ms,transfer_ms=transfer_ms,upload_ms=upload_ms,
                draw_ms=draw_ms,first_ms=first_ms,total_ms=(time.perf_counter()-started)*1000,
                scene_mib=cost/1048576,transfer_mib=len(wire)/1048576,**process_memory())
    print(json.dumps(result),flush=True)
    view._discard_native_vector_page(0);view._d2d_surface=None;surface.close();view.close();u.DestroyWindow(h)
    os._exit(0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',nargs='+',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--runs',type=int,default=5);parser.add_argument('--child',choices=('reference','rust'))
    args=parser.parse_args()
    if args.child:return child(args.child,args.pdf[0])
    if args.output is None:parser.error('--output required')
    rows=[]
    for path in args.pdf:
        for run in range(args.runs):
            for mode in (('reference','rust') if run%2==0 else ('rust','reference')):
                process=subprocess.run([sys.executable,'-m','tests.benchmark_rust_compiler',str(path),'--child',mode],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
                row=json.loads(process.stdout.strip().splitlines()[-1]);row['run']=run;rows.append(row)
                print(json.dumps(row),flush=True)
    summaries=[]
    for document in dict.fromkeys(row['document'] for row in rows):
        for mode in ('reference','rust'):
            samples=[r for r in rows if r['document']==document and r['mode']==mode]
            summaries.append(dict(document=document,mode=mode,**{k:statistics.median(r[k] for r in samples) for k in samples[0] if k.endswith('_ms') or k.endswith('_mib')}))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(runs=rows,medians=summaries),indent=2),encoding='utf-8')
    print(json.dumps(dict(medians=summaries)),flush=True)


if __name__=='__main__':main()
