"""Audit experimental Rust IR upload against the existing normalized-scene backend.

Preparation timings are single observations, not a benchmark.
"""
import os,ctypes,json,hashlib,time
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
import pymupdf
from PyQt5.QtWidgets import QApplication
from pdfeditor.gpu_raster import vector_page_from_pymupdf
from pdfeditor._path_packer import compile_scene
from pdfeditor.d2d_backend import D2DSurface
from pdfeditor.reader_view import ReaderPageView
from tests.benchmark_gpu_pipeline import render_sample
app=QApplication([])
u=ctypes.WinDLL('user32');u.CreateWindowExW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)];u.CreateWindowExW.restype=ctypes.c_void_p;u.DestroyWindow.argtypes=[ctypes.c_void_p]
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("pdf",nargs="+",type=Path)
parser.add_argument("--library",required=True,type=Path)
parser.add_argument("--output",required=True,type=Path)
parser.add_argument("--native-input",action="store_true")
args=parser.parse_args()
records=[]
for filename in args.pdf:
 pattern=filename.name
 with pymupdf.open(filename) as doc:
  page=doc[0];size=(page.rect.width,page.rect.height)
  source=vector_page_from_pymupdf(page,packed_paths=True,native_paths=True,native_text=True)
  direct=None
  if args.native_input:
   from pdfeditor.mupdf_path import compile_page
   direct=compile_page(page)
 h=u.CreateWindowExW(0,'STATIC','Rust renderer audit',0,0,0,1200,900,None,None,None,None)
 surface=D2DSurface(h,1200,900,path=args.library.resolve())
 view=ReaderPageView(use_opengl=False);view._d2d_surface=surface;view._page_sizes={0:size}
 start=time.perf_counter();view._native_vector_draws(0,source);legacy_time=(time.perf_counter()-start)*1000
 legacy=view._d2d_vector_paths[0][3]
 start=time.perf_counter();compiled=direct if direct is not None else compile_scene(source);retained=surface.create_rust_scene(compiled,*size);rust_time=(time.perf_counter()-start)*1000
 results=[]
 for scale in (min(1200/size[0],900/size[1]),1.,2.,8.):
  transform=(scale,0.,0.,scale,(1200-size[0]*scale)/2,(900-size[1]*scale)/2)
  a=render_sample(surface,legacy,transform,1200,900,'completed',.001)[3]
  b=render_sample(surface,retained,transform,1200,900,'completed',.001)[3]
  differences=[abs(x-y) for x,y in zip(a,b)]
  results.append(dict(scale=scale,changed_channels=sum(x!=0 for x in differences),max_difference=max(differences),mean_difference=sum(differences)/len(differences),old_sha256=hashlib.sha256(a).hexdigest(),new_sha256=hashlib.sha256(b).hexdigest()))
  if args.native_input:
   from PIL import Image
   args.output.parent.mkdir(parents=True,exist_ok=True)
   for label,data in [('old',a),('new',b)]:
    Image.frombytes('RGBA',(1200,900),data,'raw','BGRA').save(args.output.parent/(('2015' if '2015' in pattern else '2019')+'-'+str(scale)+'-'+label+'.png'))
 record=dict(document=pattern,legacy_prepare_ms=legacy_time,rust_prepare_ms=rust_time,cases=results)
 print(json.dumps(record),flush=True);records.append(record)
 retained.close();view._discard_native_vector_page(0);view._d2d_surface=None;surface.close();view.close();u.DestroyWindow(h)
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(records,indent=2),encoding="utf-8")
os._exit(0)
