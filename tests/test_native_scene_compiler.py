"""Production compiler: native PDF input, Rust policy, opaque worker/GPU output."""
import gc
import pickle
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from pdfeditor import gpu_raster as reference
from pdfeditor.rust_scene_compiler import compile_vector_page
from tests import test_gpu_raster as fixtures


class NativeSceneCompilerTests(unittest.TestCase):
    def test_preparation_provenance_changes_features_without_changing_gpu_packet(self):
        from pdfeditor._path_packer import compile_native_scene
        expected_packet = None
        for provenance, expected_feature in ((0, None), (0x100, 'raster-shading'),
                (0x200, 'cpu-island'), (0x4000, 'raster-pattern'),
                (0x1000, 'text-raster-fallback'), (0xc00, 'alpha-image-fusion')):
            payload = struct.pack('<6d4I', 20., 0., 0., 20., 0., 0., 1, 1, 4, 1 | provenance)
            payload += bytes((10, 20, 30, 255))
            compiled = compile_native_scene(struct.pack('<IQ', 9, len(payload)) + payload)
            if expected_packet is None:
                expected_packet = compiled.to_bytes()
            self.assertEqual(compiled.to_bytes(), expected_packet)
            if expected_feature is not None:
                self.assertIn(expected_feature, compiled.features)
            self.assertEqual('raster-shading' in compiled.features, bool(provenance & 0x100))

    def test_actual_cpu_composite_capture_keeps_mixed_rendering_feature(self):
        with pymupdf.open(stream=fixtures.nonisolated_single_path_pdf_bytes(alpha=1., knockout=True),
                          filetype='pdf') as doc:
            page = doc[0]
            page.set_mediabox(pymupdf.Rect(0, 0, 5000, 5000))
            form = page.get_xobjects()[0][0]
            doc.update_stream(form, doc.xref_stream(form) * 130)
            scene = compile_vector_page(page)
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn('cpu-island', scene.features)
            self.assertNotIn('raster-shading', scene.features)

    def test_cpu_function_shading_bitmap_is_reported_as_cpu_preparation(self):
        with pymupdf.open() as doc:
            page = doc.new_page(width=100, height=100)
            function = doc.get_new_xref()
            doc.update_object(function, '<< /FunctionType 4 /Domain [0 1 0 1] /Range [0 1 0 1 0 1] >>')
            doc.update_stream(function, b'{ pop dup 0 exch }')
            shading = doc.get_new_xref()
            doc.update_object(shading, f'<< /ShadingType 1 /ColorSpace /DeviceRGB /Domain [0 1 0 1] '
                                      f'/Matrix [100 0 0 100 0 0] /Function {function} 0 R >>')
            resources = int(doc.xref_get_key(page.xref, 'Resources')[1].split()[0])
            doc.update_object(resources, f'<< /Shading << /Sh1 {shading} 0 R >> >>')
            contents = doc.get_new_xref()
            doc.update_object(contents, '<< >>')
            doc.update_stream(contents, b'/Sh1 sh')
            page.set_contents(contents)
            scene = compile_vector_page(page)
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn('raster-shading', scene.features)
            self.assertNotIn('vector-shading', scene.features)

    def test_native_features_distinguish_images_gpu_gradients_and_cpu_pattern_capture(self):
        for name in ('repeated_image_pdf_bytes', 'linear_gradient_pdf_bytes',
                     'radial_gradient_pdf_bytes', 'image_mask_pdf_bytes', 'tiling_pattern_pdf_bytes'):
            with self.subTest(name=name), pymupdf.open(stream=getattr(fixtures, name)(), filetype='pdf') as doc:
                scene = compile_vector_page(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertNotIn('raster-shading', scene.features)
                self.assertNotIn('cpu-island', scene.features)
                if name == 'tiling_pattern_pdf_bytes':
                    self.assertIn('raster-pattern', scene.features)
                else:
                    self.assertNotIn('raster-pattern', scene.features)
                if 'gradient' in name:
                    self.assertIn('vector-shading', scene.features)
                elif name == 'repeated_image_pdf_bytes':
                    self.assertIn('image', scene.features)

    def test_all_pdf_primitive_fixtures_compile_without_python_extractor(self):
        from pdfeditor.mupdf_path import compile_page
        with patch.object(reference,'_vector_page_from_pymupdf',side_effect=AssertionError), \
                patch.object(reference,'_path_commands',side_effect=AssertionError), \
                patch.object(reference._DisplayListDevice,'__init__',side_effect=AssertionError):
            for name in dir(fixtures):
                if not name.endswith('pdf_bytes') or not callable(getattr(fixtures,name)):
                    continue
                with self.subTest(name=name),pymupdf.open(stream=getattr(fixtures,name)(),filetype='pdf') as doc:
                    compiled=compile_page(doc[0])
                    packet=compiled.to_bytes()
                    self.assertTrue(packet.startswith(b'LFSC\x02\0\0\0'))
                    self.assertLessEqual(compiled.image_bytes,64*1024*1024)
                    self.assertGreater(compiled.command_count,0)
                gc.collect()
                self.assertEqual(packet,compiled.to_bytes())

    def test_stroked_and_clipping_text_remain_vector(self):
        from pdfeditor.mupdf_path import compile_page
        for mode in (1,2,4,5,6,7):
            with self.subTest(mode=mode),pymupdf.open() as doc:
                page=doc.new_page(width=300,height=240)
                page.insert_text((20,80),'OUTLINE TEXT',fontsize=35,render_mode=mode)
                compiled=compile_page(page,8.)
                self.assertEqual(compiled.image_bytes,0)
                self.assertGreater(compiled.resource_count,0)

    def test_linear_and_radial_gradients_compile_as_vector_resources(self):
        from pdfeditor.mupdf_path import compile_page
        for name in ('linear_gradient_pdf_bytes','radial_gradient_pdf_bytes'):
            with self.subTest(name=name),pymupdf.open(stream=getattr(fixtures,name)(),filetype='pdf') as doc:
                compiled=compile_page(doc[0],8.)
                self.assertEqual(compiled.image_bytes,0)
                self.assertGreater(compiled.resource_count,0)

    def test_high_zoom_viewport_bounds_memory_and_preserves_vector_text(self):
        from pdfeditor.mupdf_path import compile_page
        with pymupdf.open(stream=fixtures.soft_mask_pdf_bytes(),filetype='pdf') as doc:
            doc[0].insert_text((20,40),'VECTOR',fontsize=20)
            full=compile_page(doc[0],16.)
            cropped=compile_page(doc[0],16.,(40.,40.,60.,60.))
            self.assertLess(cropped.image_bytes,full.image_bytes)
            self.assertGreater(cropped.resource_count,1)
            self.assertLessEqual(full.image_bytes,64*1024*1024)

    def test_worker_and_document_use_packet_and_rebuild_without_old_recipe(self):
        from pdfeditor.gpu_scene_worker import main
        from pdfeditor.core import Document,_gpu_scene_cost
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'page.pdf';result=root/'scene'
            source.write_bytes(fixtures.soft_mask_pdf_bytes())
            with patch.object(reference,'_vector_page_from_pymupdf',side_effect=AssertionError):
                self.assertEqual(main([str(source),str(result),'--base-scene',str(root/'absent')]),0)
                scene=pickle.loads(result.read_bytes())
                self.assertTrue(scene.supported,scene.reason)
                self.assertFalse(scene.drawables)
                self.assertTrue(scene.compiled_packet)
                self.assertGreater(_gpu_scene_cost(scene),len(scene.compiled_packet))
                doc=Document(str(source),read_only=True)
                try:
                    installed=doc.gpu_vector_page(0)
                    self.assertTrue(installed.compiled_packet)
                finally:doc.close()
            source.unlink()
            self.assertEqual(scene.to_bytes(),pickle.loads(result.read_bytes()).to_bytes())

    def test_unavailable_native_adapter_returns_cpu_fallback_and_timeout_is_distinct(self):
        with pymupdf.open(stream=fixtures.linear_gradient_pdf_bytes(),filetype='pdf') as doc:
            with patch('pdfeditor.mupdf_path._library',return_value=None):
                scene=compile_vector_page(doc[0])
                self.assertFalse(scene.supported)
                self.assertTrue(scene.reason.startswith('unsupported Rust GPU scene'))
            scene=compile_vector_page(doc[0],timeout_seconds=0)
            self.assertEqual(scene.reason,'GPU scene time budget exceeded')
            scene=compile_vector_page(doc[0],timeout_seconds=.000001)
            self.assertEqual(scene.reason,'GPU scene time budget exceeded')

    def test_rust_rejects_crossed_scopes_and_nonfinite_metadata(self):
        from pdfeditor._path_packer import plan_native_scene,compile_native_scene
        row=lambda kind:struct.pack('<II5d',kind,0,0.,0.,10.,10.,1.)
        for data in (b'bad',row(12),row(13)+row(16),row(15),struct.pack('<II5d',0,0,0.,0.,float('nan'),10.,1.)):
            with self.subTest(data=data),self.assertRaises(ValueError):
                plan_native_scene(data,(0.,0.,100.,100.))
        with self.assertRaises(ValueError):compile_native_scene(b'bad')

    def test_cmyk_transparency_keeps_cpu_reference_fallback(self):
        with pymupdf.open(stream=fixtures.cmyk_group_pdf_bytes(alpha=.5),filetype='pdf') as doc:
            scene=compile_vector_page(doc[0])
            self.assertFalse(scene.supported)
            self.assertIn('CMYK transparency group',scene.reason)

    def test_opaque_packet_parallel_transfer_is_lossless(self):
        from pdfeditor.scene_transfer import dumps
        from dataclasses import replace
        with pymupdf.open(stream=fixtures.linear_gradient_pdf_bytes(),filetype='pdf') as doc:
            scene=compile_vector_page(doc[0])
        # Exercise the large-packet branch without allocating a giant PDF scene.
        scene=replace(scene,compiled_packet=scene.compiled_packet+b'\0'*(9*1024*1024))
        data=dumps(scene,parallel_workers=2)
        restored=pickle.loads(data)
        self.assertEqual(restored,scene)
        self.assertLess(len(data),len(scene.compiled_packet)//2)


from tests import test_rust_scene_gpu as gpu_helpers


class NativeSceneGpuTests(unittest.TestCase):
    setUpClass=classmethod(gpu_helpers.RustSceneGpuTests.setUpClass.__func__)
    setUp=gpu_helpers.RustSceneGpuTests.setUp
    tearDown=gpu_helpers.RustSceneGpuTests.tearDown

    def _compare_page(self,page):
        from tests.benchmark_gpu_pipeline import render_sample
        old=reference.vector_page_from_pymupdf(page)
        self.assertTrue(old.supported,old.reason)
        new=compile_vector_page(page)
        self.assertTrue(new.supported,new.reason)
        self.view._page_sizes[0]=(page.rect.width,page.rect.height)
        frames=[]
        for scene in (old,new):
            self.view._native_vector_draws(0,scene)
            frames.append(render_sample(self.surface,self.view._d2d_vector_paths[0][3],(1.,0.,0.,1.,0.,0.),256,256,'completed',.001)[3])
        self.view._discard_native_vector_page(0)
        return sum(abs(a-b) for a,b in zip(*frames))/len(frames[0])

    def test_native_pdf_output_and_reader_upload_match_reference(self):
        names=('linear_gradient_pdf_bytes','radial_gradient_pdf_bytes','soft_mask_pdf_bytes',
               'tiling_pattern_pdf_bytes','blended_mask_pdf_bytes','image_mask_pdf_bytes',
               'cmyk_image_pdf_bytes','nonisolated_masked_image_pdf_bytes',
               'nonisolated_nested_blend_pdf_bytes','nested_knockout_clip_pdf_bytes')
        for name in names:
            with self.subTest(name=name),pymupdf.open(stream=getattr(fixtures,name)(),filetype='pdf') as doc:
                error=self._compare_page(doc[0])
                self.assertLess(error,2.,f'{name}: mean channel error {error:.4f}/255')

    def test_stroked_text_width_and_text_clip_rendering_match_reference(self):
        for mode in (1,2,4,5,6,7):
            with self.subTest(mode=mode),pymupdf.open() as doc:
                page=doc.new_page(width=240,height=240)
                page.insert_text((20,80),'OUTLINE',fontsize=35,render_mode=mode,
                                 color=(1,0,0),fill=(0,0,1))
                self.assertLess(self._compare_page(page),2.)

    def test_binary_restored_scene_renders_identical_pixels(self):
        from pdfeditor.scene_cache_packet import encode, decode
        from tests.benchmark_gpu_pipeline import render_sample
        with pymupdf.open(stream=fixtures.blended_mask_pdf_bytes(), filetype='pdf') as doc:
            page = doc[0]
            original = compile_vector_page(page)
            self.assertTrue(original.supported, original.reason)
            self.view._page_sizes[0] = (page.rect.width, page.rect.height)
        restored = decode(encode(original))
        self.assertEqual(original, restored)
        for scale in (1., 8.):
            frames = []
            for scene in (original, restored):
                self.view._native_vector_draws(0, scene)
                frames.append(render_sample(self.surface, self.view._d2d_vector_paths[0][3],
                    (scale, 0., 0., scale, 0., 0.), 256, 256, 'completed', .001)[3])
            self.assertEqual(*frames)
