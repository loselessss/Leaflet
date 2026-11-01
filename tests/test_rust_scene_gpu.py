"""Experimental Rust IR -> native adapter checks, opt-in DLL during development."""
import ctypes
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.name=='nt','Windows GPU adapter')
class RustSceneGpuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5.QtWidgets import QApplication
        from pdfeditor.d2d_backend import _load_library
        cls.library=Path(os.environ.get('LEAFLET_RUST_RENDERER','native/bin/spdf_d2d_renderer.dll')).resolve()
        if not cls.library.is_file():raise unittest.SkipTest('Renderer not built')
        if not hasattr(_load_library(cls.library),'spdf_d2d_import_rust_scene'):
            raise unittest.SkipTest('Rust upload adapter not built')
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        cls.app=QApplication.instance() or QApplication([])
        cls.user32=ctypes.WinDLL('user32')
        cls.user32.CreateWindowExW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p,ctypes.c_wchar_p,
            ctypes.c_uint32,*([ctypes.c_int]*4),*([ctypes.c_void_p]*4)]
        cls.user32.CreateWindowExW.restype=ctypes.c_void_p
        cls.user32.DestroyWindow.argtypes=[ctypes.c_void_p]

    def setUp(self):
        from pdfeditor.d2d_backend import D2DSurface
        from pdfeditor.reader_view import ReaderPageView
        self.hwnd=self.user32.CreateWindowExW(0,'STATIC','Rust compiler test',0,0,0,256,256,None,None,None,None)
        self.assertTrue(self.hwnd)
        self.surface=D2DSurface(self.hwnd,256,256,path=self.library)
        self.view=ReaderPageView(use_opengl=False)
        self.view._d2d_surface=self.surface;self.view._page_sizes={0:(100.,100.)}

    def tearDown(self):
        self.view._discard_native_vector_page(0);self.view._d2d_surface=None
        self.surface.close();self.view.close();self.user32.DestroyWindow(self.hwnd)

    def test_all_rendered_operations_match_existing_backend(self):
        from pdfeditor import gpu_raster as g
        from pdfeditor._path_packer import compile_scene
        from tests.benchmark_gpu_pipeline import render_sample
        rect=g._rect_commands(5.,5.,80.,80.)
        triangle=(('move',10.,10.),('line',70.,15.),('line',45.,60.),('close',))
        source=g.VectorPage(True,items=(g.GroupPush(.8),g.ClipPush(rect),
            g.VectorPath(triangle,fill_argb=0xff1177aa),
            g.VectorPath(triangle,stroke_argb=0xff001122,stroke_width=2.,
                         stroke_style=(0,0,0,0,10.,0.,(2.,1.))),
            g.VectorLinearGradient(triangle,(10.,10.),(70.,60.),((0.,0xff000000),(1.,0xffeeeeee))),
            g.ClipStrokePush(rect,2.),g.VectorPath(triangle,fill_argb=0xff443322),g.ClipPop(),
            g.ClipPop(),g.GroupPop(),g.MaskBegin((0.,0.,100.,100.),False,0),
            g.VectorPath(rect,fill_argb=0xffffffff),g.MaskEnd(),
            g.VectorImage(b'\x20\x40\x80\xff',1,1,4,(30.,0.,0.,30.,15.,15.)),g.ClipPop(),
            g.VectorRadialGradient(triangle,(40.,40.),(0.,0.),(20.,20.),((0.,0xff000000),(1.,0xffffffff))),
            g.VectorPath(triangle,fill_argb=0xff123456,groupable=True,transform=(.2,0.,0.,.2,1.,1.)),
            g.VectorPath(triangle,fill_argb=0xff123456,groupable=True,transform=(.2,0.,0.,.2,21.,1.))))
        self.view._native_vector_draws(0,source)
        old=self.view._d2d_vector_paths[0][3]
        new=self.surface.create_rust_scene(compile_scene(source),100.,100.)
        try:
            for scale in (1.,2.):
                transform=(scale,0.,0.,scale,5.,5.)
                first=render_sample(self.surface,old,transform,256,256,'completed',.001)[3]
                second=render_sample(self.surface,new,transform,256,256,'completed',.001)[3]
                self.assertEqual(first,second)
        finally:new.close()

    def test_invalid_packets_fail_without_losing_surface(self):
        from pdfeditor import gpu_raster as g
        from pdfeditor._path_packer import compile_scene
        class Invalid:
            requires_luminosity=False
            def __init__(self,data):self.data=data
            def to_bytes(self):return self.data
        for packet in (b'',b'bad header',b'LFSC\x01\0\0\0'+b'\xff'*8):
            with self.subTest(packet=packet),self.assertRaises(OSError):
                self.surface.create_rust_scene(Invalid(packet),100.,100.)
        valid=compile_scene(g.VectorPage(True,items=(g.VectorPath(g._rect_commands(0.,0.,50.,50.),fill_argb=0xff112233),)))
        scene=self.surface.create_rust_scene(valid,100.,100.);scene.close()
