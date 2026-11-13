"""Independent reader worker: PDF input, binary IPC, cache interoperability."""
import io
import os
from pathlib import Path
import pickle
import sqlite3
import struct
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from pdfeditor import scene_worker_result as result,scene_disk_cache as cache
from pdfeditor.rust_scene_compiler import compile_vector_page
from tests import test_gpu_raster as fixtures

ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/'native/bin/leaflet-gpu-scene-worker.exe'


def native_command():
    return [str(WORKER),'--bridge',str(ROOT/'native/bin/leaflet_mupdf_path.dll'),
            '--mupdf',str(Path(pymupdf.__file__).parent/'mupdfcpp64.dll'),
            '--expected-mupdf',pymupdf.VersionFitz]


@unittest.skipUnless(WORKER.is_file(),'Native worker not built')
class NativeSceneWorkerTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.root=Path(self.directory.name)
        self.input=self.root/'한글 input.pdf'
        self.output=self.root/'한글 result.scene'
        self.redirect=patch('pdfeditor.paths.user_data_dir',return_value=str(self.root))
        self.redirect.start();self.addCleanup(self.redirect.stop)
        self.settings=patch('pdfeditor.settings.PATH',str(self.root/'settings.json'))
        self.settings.start();self.addCleanup(self.settings.stop)

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self,*options,command=None,env=None):
        subprocess.run([*(command or native_command()),str(self.input),str(self.output),*options],
            check=True,capture_output=True,timeout=20,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        with self.output.open('rb') as stream:return result.load(stream)

    def test_native_primitives_are_identical_to_python_control_path(self):
        for name in ('linear_gradient_pdf_bytes','radial_gradient_pdf_bytes','soft_mask_pdf_bytes',
                     'blended_mask_pdf_bytes','tiling_pattern_pdf_bytes','image_mask_pdf_bytes',
                     'nonisolated_nested_blend_pdf_bytes','nested_knockout_clip_pdf_bytes'):
            with self.subTest(name=name):
                self.input.write_bytes(getattr(fixtures,name)())
                with pymupdf.open(self.input) as doc:expected=compile_vector_page(doc[0])
                actual=self.invoke()
                self.assertTrue(actual.supported,actual.reason)
                self.assertEqual(actual,expected)

    def test_jpeg_packet_survives_native_worker_transfer_and_sqlite_cache(self):
        from tests.jpeg_fixtures import jpeg_pdf
        self.input.write_bytes(jpeg_pdf())
        with pymupdf.open(self.input) as doc:
            expected = compile_vector_page(doc[0])
        self.assertIn('jpeg-ycbcr', expected.features)
        options = ('--disk-cache-key', 'jpeg', '--cache-db', str(self.root / 'jpeg.db'),
                   '--cache-limit', str(100 * 1024 * 1024))
        self.assertEqual(self.invoke(*options), expected)
        self.assertEqual(self.invoke(*options), expected)

    def test_page_rotation_crop_and_high_zoom_viewport(self):
        with pymupdf.open() as doc:
            doc.new_page(width=240,height=300)
            page=doc.new_page(width=240,height=300)
            page.insert_text((40,80),'Rotated crop')
            page.set_cropbox((20,20,220,280));page.set_rotation(90)
            doc.save(self.input)
        with pymupdf.open(self.input) as doc:
            expected=compile_vector_page(doc[1],8.,viewport=(-10.,-10.,80.,90.))
        actual=self.invoke('--page','1','--scale','8','--viewport','-10','-10','80','90')
        self.assertTrue(actual.supported,actual.reason)
        self.assertEqual(actual,expected)

    def test_sdk_version_mismatch_returns_exact_versions_without_compilation(self):
        # A missing PDF proves the version guard runs before parsing its input.
        command=native_command()
        command[command.index('--expected-mupdf')+1]='0.0.0-test-mismatch'
        actual=self.invoke(command=command)
        self.assertFalse(actual.supported)
        self.assertEqual(actual.reason,
            'unsupported Rust GPU scene: native MuPDF version mismatch '
            f'(bridge={pymupdf.VersionFitz}, runtime=0.0.0-test-mismatch)')

    def test_python_cache_is_read_without_loading_sdk_and_native_cache_is_read_by_python(self):
        self.input.write_bytes(fixtures.soft_mask_pdf_bytes())
        with pymupdf.open(self.input) as doc:expected=compile_vector_page(doc[0])
        db=self.root/'cache/gpu-scenes.sqlite3'
        cache.save('from-python',expected)
        command=native_command();command[command.index('--mupdf')+1]=str(self.root/'missing.dll')
        actual=self.invoke('--disk-cache-key','from-python','--cache-db',str(db),'--cache-limit',str(100*1024*1024),command=command)
        self.assertEqual(actual,expected)
        actual=self.invoke('--disk-cache-key','from-native','--cache-db',str(db),'--cache-limit',str(100*1024*1024))
        self.assertEqual(cache.load('from-native'),actual)
        self.assertEqual(actual,expected)

    def test_corrupt_cache_and_disabled_cache_keep_native_compilation_usable(self):
        self.input.write_bytes(fixtures.linear_gradient_pdf_bytes())
        db=self.root/'cache/gpu-scenes.sqlite3'
        with pymupdf.open(self.input) as doc:
            cache.save('bad',compile_vector_page(doc[0]))
        with sqlite3.connect(db) as connection:connection.execute("UPDATE scenes SET data=?",(b'corrupt',))
        connection.close()
        actual=self.invoke('--disk-cache-key','bad','--cache-db',str(db),'--cache-limit',str(100*1024*1024))
        self.assertTrue(actual.supported,actual.reason)
        self.assertEqual(cache.load('bad'),actual)
        self.invoke('--disk-cache-key','disabled','--cache-db',str(db),'--cache-limit','0')
        self.assertIsNone(cache.load('disabled'))

    def test_timeout_and_protected_input_preserve_pdf_and_return_fallback(self):
        self.input.write_bytes(fixtures.linear_gradient_pdf_bytes())
        before=self.input.read_bytes()
        actual=self.invoke('--timeout','0')
        self.assertEqual(actual.reason,'GPU scene time budget exceeded')
        self.assertEqual(before,self.input.read_bytes())
        protected=self.root/'protected.pdf'
        with pymupdf.open(self.input) as doc:
            doc.save(protected,encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='reader')
        self.input=protected
        actual=self.invoke()
        self.assertFalse(actual.supported)
        self.assertIn('password required',actual.reason)

    def test_authenticated_private_input_outlives_document(self):
        from pdfeditor.core import Document
        protected=self.root/'protected.pdf'
        with pymupdf.open(stream=fixtures.soft_mask_pdf_bytes(),filetype='pdf') as doc:
            doc.save(protected,encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='reader')
        before=protected.read_bytes()
        doc=Document(str(protected),password='reader',read_only=True,isolated=True)
        try:
            index=doc.write_gpu_page_snapshot(0,self.input)
            expected=compile_vector_page(doc._doc[0])
        finally:doc.close()
        self.assertEqual(self.invoke('--page',str(index)),expected)
        self.assertEqual(protected.read_bytes(),before)

    def test_native_cache_evicts_old_entries_within_disk_budget(self):
        import random
        from contextlib import closing
        samples=random.Random(42).randbytes(120*120*3)
        with pymupdf.open() as doc:
            page=doc.new_page(width=120,height=120)
            pix=pymupdf.Pixmap(pymupdf.csRGB,120,120,samples,False)
            page.insert_image(page.rect,pixmap=pix);doc.save(self.input)
        db=self.root/'cache/gpu-scenes.sqlite3'
        for key in ('older','newer'):
            actual=self.invoke('--disk-cache-key',key,'--cache-db',str(db),'--cache-limit','100000')
            self.assertTrue(actual.supported,actual.reason)
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(connection.execute('SELECT key FROM scenes').fetchall(),[(key,)])
        self.assertLessEqual(db.stat().st_size,100000)

    def test_default_command_uses_executable_without_python_runtime_imports(self):
        from pdfeditor.paths import gpu_scene_worker_command
        import pefile
        with patch.dict(os.environ,{'SPDF_GPU_SCENE_WORKER':''}):
            self.assertEqual(Path(gpu_scene_worker_command()[0]),WORKER)
            with patch('pdfeditor.paths.is_frozen',return_value=True),patch('pdfeditor.paths.sys._MEIPASS',str(ROOT),create=True),patch('pdfeditor.paths.os.path.isfile',return_value=True):
                self.assertEqual(Path(gpu_scene_worker_command()[0]),ROOT/'native/leaflet-gpu-scene-worker.exe')
        executable=pefile.PE(str(WORKER))
        self.assertTrue(all('python' not in entry.dll.decode().lower() for entry in executable.DIRECTORY_ENTRY_IMPORT))
        executable.close()

    def test_bundled_worker_layout_with_no_python_on_path(self):
        from tools.build.build_payload import native_worker_runtime_binaries
        from PyQt5.QtCore import QLibraryInfo
        self.input.write_bytes(fixtures.soft_mask_pdf_bytes())
        command=native_command()
        bundle=self.root/'bundle'
        native=bundle/'native';native.mkdir(parents=True)
        sdk=bundle/'pymupdf';sdk.mkdir()
        modules=[Path(command[0]),Path(command[2]),Path(command[4])]
        runtimes=native_worker_runtime_binaries(*modules,search_paths=[
            QLibraryInfo.location(QLibraryInfo.BinariesPath)])
        self.assertTrue(runtimes)
        for source,_ in runtimes:shutil.copy2(source,native/Path(source).name)
        for source,target,index in ((modules[0],native,0),(modules[1],native,2),(modules[2],sdk,4)):
            destination=target/source.name;shutil.copy2(source,destination);command[index]=str(destination)
        env=dict(os.environ,PATH=str(Path(os.environ['SystemRoot'])/'System32'))
        env.pop('PYTHONPATH',None)
        with pymupdf.open(self.input) as doc:expected=compile_vector_page(doc[0])
        self.assertEqual(self.invoke(command=command,env=env),expected)

    def test_private_legacy_result_and_invalid_native_frames(self):
        from pdfeditor.gpu_raster import VectorPage
        expected=VectorPage(False,reason='example')
        self.assertEqual(result.load(io.BytesIO(pickle.dumps(expected))),expected)
        good=result.MAGIC+result.HEADER.pack(1,1.,0,0.,0.,0.,0.,4)+b'fail'
        self.assertEqual(result.load(io.BytesIO(good)).reason,'fail')
        for bad in (good[:-1],good+b'junk',result.MAGIC+b'x',
                    result.MAGIC+result.HEADER.pack(0,1.,0,0.,0.,0.,0.,result.MAX_BLOB+1)):
            with self.subTest(size=len(bad)),self.assertRaises(ValueError):result.load(io.BytesIO(bad))
