"""Manual fresh scene transport + GPU preparation comparison; private PDF inputs."""
import os, gc, ctypes, pickle, time, json, statistics
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
import pymupdf
from PyQt5.QtWidgets import QApplication
from pdfeditor.gpu_raster import vector_page_from_pymupdf
from pdfeditor import scene_transfer as wire
from pdfeditor.d2d_backend import D2DSurface, _path_array
from pdfeditor.reader_view import ReaderPageView
from tests.benchmark_geometry_compiler import render_signatures
app=QApplication([])
u=ctypes.WinDLL('user32');u.CreateWindowExW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)];u.CreateWindowExW.restype=ctypes.c_void_p;u.DestroyWindow.argtypes=[ctypes.c_void_p]
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("pdf", nargs="+", type=Path)
parser.add_argument("--output", required=True, type=Path)
args=parser.parse_args()
records=[]
for filename in args.pdf:
 pattern=filename.name
 with pymupdf.open(filename) as doc:
  page=doc[0];size=(page.rect.width,page.rect.height);scene=vector_page_from_pymupdf(page)
 hwnd=u.CreateWindowExW(0,'STATIC','benchmark',0,0,0,1200,900,None,None,None,None)
 surface=D2DSurface(hwnd,1200,900);view=ReaderPageView(use_opengl=False);view._d2d_surface=surface;view._page_sizes={0:size}
 samples={x:[] for x in ('pickle','packed')}
 for n in range(8):
  for mode in (('pickle','packed') if n%2==0 else ('packed','pickle')):
   gc.collect();start=time.perf_counter()
   payload=pickle.dumps(scene,protocol=5) if mode=='pickle' else wire.dumps(scene)
   t1=time.perf_counter();restored=pickle.loads(payload);t2=time.perf_counter()
   view._native_vector_draws(0,restored);end=time.perf_counter()
   if n:samples[mode].append([(t1-start)*1000,(t2-t1)*1000,(end-t2)*1000,(end-start)*1000])
   view._discard_native_vector_page(0)
   if n==0:
    assert restored==scene
    for a,b in zip(scene.drawables,restored.drawables):
     if hasattr(a,'commands'):assert bytes(_path_array(a.commands))==bytes(_path_array(b.commands))
    hashes=render_signatures(restored,size)
    if mode=='pickle':expected=hashes
    else:assert hashes==expected
 view._d2d_surface=None;surface.close();view.close();u.DestroyWindow(hwnd)
 record=dict(document=pattern,samples=samples,median={k:[statistics.median(x[i] for x in v) for i in range(4)] for k,v in samples.items()},pixels_equal=True)
 print(json.dumps(record),flush=True);records.append(record)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(records,indent=2),encoding="utf-8")
os._exit(0)
