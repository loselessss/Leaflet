"""Compare rebuilt native/reference scenes at each requested zoom and viewport."""
import argparse,ctypes,json,os,time
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
import pymupdf
from PyQt5.QtWidgets import QApplication
from pdfeditor.reader_view import ReaderPageView
from pdfeditor.d2d_backend import D2DSurface
from pdfeditor.gpu_raster import vector_page_from_pymupdf
from pdfeditor.rust_scene_compiler import compile_vector_page
from tests.benchmark_gpu_pipeline import render_sample


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('pdf',type=Path,nargs='+');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();app=QApplication([])
    u=ctypes.WinDLL('user32');u.CreateWindowExW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)];u.CreateWindowExW.restype=ctypes.c_void_p;u.DestroyWindow.argtypes=[ctypes.c_void_p]
    rows=[];args.output.parent.mkdir(parents=True,exist_ok=True)
    for filename in args.pdf:
        with pymupdf.open(filename) as doc:
            p=doc[0];size=(p.rect.width,p.rect.height)
            h=u.CreateWindowExW(0,'STATIC','Native zoom audit',0,0,0,1200,900,None,None,None,None)
            surface=D2DSurface(h,1200,900);view=ReaderPageView(use_opengl=False);view._d2d_surface=surface;view._page_sizes[0]=size
            for scale in (min(1200/size[0],900/size[1]),1.,2.,8.):
                viewport=None
                if scale>=1.:
                    viewport=(max(0.,size[0]/2-1800/scale),max(0.,size[1]/2-1350/scale),min(size[0],size[0]/2+1800/scale),min(size[1],size[1]/2+1350/scale))
                transform=(scale,0.,0.,scale,(1200-size[0]*scale)/2,(900-size[1]*scale)/2)
                frames=[];metrics=[]
                for kind in ('reference','rust'):
                    started=time.perf_counter()
                    if kind=='reference':scene=vector_page_from_pymupdf(p,max(1.,scale),viewport=viewport,packed_paths=True,native_paths=True,native_text=True)
                    else:scene=compile_vector_page(p,max(1.,scale),viewport=viewport)
                    assert scene.supported,scene.reason
                    view._native_vector_draws(0,scene)
                    prepare_ms=(time.perf_counter()-started)*1000
                    frame=render_sample(surface,view._d2d_vector_paths[0][3],transform,1200,900,'completed',.001)[3]
                    frames.append(frame);metrics.append(dict(mode=kind,prepare_ms=prepare_ms,packet_bytes=len(scene.compiled_packet)))
                    from PIL import Image
                    Image.frombytes('RGBA',(1200,900),frame,'raw','BGRA').save(args.output.parent/(('2015' if '2015' in filename.name else '2019')+f'-{scale}-{kind}.png'))
                    view._discard_native_vector_page(0)
                diffs=[abs(a-b) for a,b in zip(*frames)]
                row=dict(document=filename.name,scale=scale,viewport=viewport,mean_channel_difference=sum(diffs)/len(diffs),maximum_channel_difference=max(diffs),changed_channels=sum(d!=0 for d in diffs),metrics=metrics)
                rows.append(row);print(json.dumps(row),flush=True)
            view._d2d_surface=None;surface.close();view.close();u.DestroyWindow(h)
    args.output.write_text(json.dumps(rows,indent=2),encoding='utf-8');os._exit(0)


if __name__=='__main__':main()
