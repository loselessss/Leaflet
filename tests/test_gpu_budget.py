"""Real PDFs that previously exhausted GPU capacity or rejected valid input."""
import ctypes
import gc
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import pymupdf

from tests.test_gpu_raster import linear_gradient_pdf_bytes
from tests.test_type3_gpu import type3_pdf


def heavy_type3_pdf():
    with pymupdf.open(stream=type3_pdf(opacity=.4), filetype='pdf') as document:
        for xref in range(1, document.xref_length()):
            if document.xref_is_stream(xref):
                data = document.xref_stream(xref)
                if b' d1' in data and b' re ' in data:
                    dots = ''.join(f'{(i%100)*6} {(i//100)*14} 3 7 re f\n'
                                   for i in range(5000)).encode()
                    document.update_stream(xref, b'600 0 0 0 600 700 d1\n' + dots)
                    break
        return document.tobytes()


def zero_axis_pdf():
    with pymupdf.open(stream=linear_gradient_pdf_bytes(), filetype='pdf') as document:
        document.xref_set_key(5, 'Coords', '[50 50 50 50]')
        document[0].draw_rect((40, 40, 160, 120), fill=(.1, .4, .8), color=None)
        return document.tobytes()


def image_pdf(*, wide=False):
    width, height, count = (20000, 2, 1) if wide else (2048, 3072, 3)
    with pymupdf.open() as document:
        page = document.new_page(width=width*count, height=height)
        resources, commands = [], []
        for index, color in enumerate(((25, 120, 220), (180, 70, 30), (40, 180, 90))[:count]):
            xref = document.get_new_xref()
            document.update_object(xref, f'<< /Type /XObject /Subtype /Image /Width {width} '
                f'/Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 >>')
            document.update_stream(xref, bytes(color) * (width*height))
            resources.append(f'/Im{index} {xref} 0 R')
            commands.append(f'q {width} 0 0 {height} {index*width} 0 cm /Im{index} Do Q\n')
        resource = int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])
        document.update_object(resource, '<< /XObject << '+' '.join(resources)+' >> >>')
        content = document.get_new_xref()
        document.update_object(content, '<< >>')
        document.update_stream(content, ''.join(commands).encode())
        page.set_contents(content)
        return document.tobytes()


def deep_pattern_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=100, height=100)
        child = None
        for _ in range(10):
            xref = document.get_new_xref()
            resources = f'<< /Pattern << /Child {child} 0 R >> >>' if child else '<< >>'
            document.update_object(xref, '<< /Type /Pattern /PatternType 1 /PaintType 1 '
                '/TilingType 1 /BBox [0 0 100 100] /XStep 100 /YStep 100 '
                f'/Resources {resources} >>')
            content = (b'/Pattern cs /Child scn 0 0 100 100 re f' if child
                       else b'.1 .4 .8 rg 0 0 100 100 re f')
            document.update_stream(xref, content)
            child = xref
        resource = int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])
        document.update_object(resource, f'<< /Pattern << /Child {child} 0 R >> >>')
        content = document.get_new_xref()
        document.update_object(content, '<< >>')
        document.update_stream(content, b'/Pattern cs /Child scn 0 0 100 100 re f')
        page.set_contents(content)
        return document.tobytes()


def zero_objects_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=200, height=200)
        image = document.get_new_xref()
        document.update_object(image, '<< /Type /XObject /Subtype /Image /Width 1 '
            '/Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 >>')
        document.update_stream(image, bytes((255, 0, 0)))
        resource = int(document.xref_get_key(page.xref, 'Resources')[1].split()[0])
        document.update_object(resource, f'<< /XObject << /Im {image} 0 R >> >>')
        content = document.get_new_xref()
        document.update_object(content, '<< >>')
        document.update_stream(content,
            b'.1 .4 .8 rg 10 10 40 30 re f\n'
            b'q 0 0 0 20 80 50 cm /Im Do Q\n'
            b'q 20 0 0 0 80 50 cm /Im Do Q\n'
            b'1 0 0 rg 60 60 0 30 re f 60 60 30 0 re f\n'
            b'q 80 80 0 60 re W n 0 0 200 200 re f Q\n'
            b'0 G 0 w 30 150 m 170 150 l S\n')
        page.set_contents(content)
        return document.tobytes()


class GpuBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt5.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_declared_image_above_128_mib_is_rejected_before_pixel_copy(self):
        import struct
        from pdfeditor._path_packer import compile_native_scene
        payload = struct.pack('<6d4I', 1., 0., 0., 1., 0., 0., 8192, 4097, 8192*4, 1)
        with self.assertRaisesRegex(ValueError, 'invalid native image'):
            compile_native_scene(struct.pack('<IQ', 9, len(payload)) + payload)

    def test_large_worker_packet_roundtrips_and_uploads_above_old_64_mib_limit(self):
        from tests.test_native_scene_worker import native_command
        from pdfeditor.scene_worker_result import load
        from pdfeditor.scene_cache_packet import encode, decode
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'large.pdf', Path(directory)/'large.scene'
            source.write_bytes(image_pdf())
            run = subprocess.run(native_command()+[str(source), str(output), '--timeout', '20'],
                capture_output=True, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(run.returncode, 0, run.stderr[-1000:])
            with output.open('rb') as stream:
                scene = load(stream)
            self.assertTrue(scene.supported, scene.reason)
            self.assertGreater(len(scene.compiled_packet), 64*1024*1024)
            self.assertLess(len(scene.compiled_packet), 128*1024*1024)
            restored = decode(encode(scene))
            self.assertEqual(restored, scene)
            del restored
            gc.collect()
            self._render_matches(scene, source)

    def test_valid_edge_cases_do_not_fall_back_as_entire_pages(self):
        from pdfeditor.rust_scene_compiler import compile_vector_page
        for name, data in (('zero axis', zero_axis_pdf()),
                           ('zero objects', zero_objects_pdf()),
                           ('heavy Type3', heavy_type3_pdf()),
                           ('deep pattern', deep_pattern_pdf()),
                           ('wide image', image_pdf(wide=True))):
            with self.subTest(name=name), pymupdf.open(stream=data, filetype='pdf') as document:
                page = document[0]
                scene = compile_vector_page(page)
                self.assertTrue(scene.supported, scene.reason)
                if name == 'heavy Type3':
                    self.assertIn('text-raster-fallback', scene.features)
                self._render_matches(scene, document)
                if name == 'heavy Type3':
                    from pdfeditor.mupdf_path import compile_page
                    high = compile_page(page, 32.)
                    self.assertLessEqual(high.image_bytes, 128*1024*1024)
                if name == 'wide image':
                    from pdfeditor.mupdf_path import compile_page
                    cropped = compile_page(page, 32., (1000., 0., 1020., 2.))
                    self.assertGreaterEqual(cropped.image_bytes, 20*2*4)
                    self.assertLessEqual(cropped.image_bytes, 256)

    def _render_matches(self, scene, source):
        from pdfeditor.d2d_backend import D2DSurface
        from tests.benchmark_gpu_pipeline import render_sample
        user32 = ctypes.WinDLL('user32')
        user32.CreateWindowExW.restype = ctypes.c_void_p
        user32.CreateWindowExW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p,
            ctypes.c_wchar_p, ctypes.c_uint32, *([ctypes.c_int]*4), *([ctypes.c_void_p]*4)]
        user32.DestroyWindow.argtypes = [ctypes.c_void_p]
        own = not isinstance(source, pymupdf.Document)
        document = pymupdf.open(source) if own else source
        page = document[0]
        scale = min(600/page.rect.width, 480/page.rect.height)
        handle = user32.CreateWindowExW(0, 'STATIC', 'GPU capacity test', 0,
                                      0, 0, 600, 480, None, None, None, None)
        surface = D2DSurface(handle, 600, 480)
        try:
            retained = surface.create_rust_scene(scene, page.rect.width, page.rect.height)
            try:
                frame = render_sample(surface, retained, (scale, 0., 0., scale, 0., 0.),
                                      600, 480, 'completed', .001)[3]
            finally:
                retained.close()
            actual = np.frombuffer(frame, np.uint8).reshape(480, 600, 4)[:, :, :3][:, :, ::-1]
            from PIL import Image
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            reference = Image.new('RGB', (600, 480), 'white')
            reference.paste(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
            self.assertLess(float(np.abs(actual.astype(int)-np.array(reference).astype(int)).mean()), 2.)
        finally:
            surface.close()
            user32.DestroyWindow(handle)
            if own:
                document.close()
