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
    def test_jpeg_original_survives_compilation_and_cache_roundtrip(self):
        from tests.jpeg_fixtures import jpeg_bytes, jpeg_pdf
        from pdfeditor.scene_cache_packet import encode, decode
        for subsampling, progressive in ((0, False), (1, False), (2, False), (2, True)):
            data = jpeg_bytes(subsampling=subsampling, progressive=progressive)
            with self.subTest(subsampling=subsampling, progressive=progressive), \
                    pymupdf.open(stream=jpeg_pdf(data), filetype='pdf') as doc:
                scene = compile_vector_page(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn('jpeg-ycbcr', scene.features)
                self.assertNotIn('image-downsample', scene.features)
                self.assertIn(data, scene.compiled_packet)
                self.assertLess(len(scene.compiled_packet), 192 * 160 * 4)
                self.assertEqual(decode(encode(scene)), scene)
                from pdfeditor.core import _gpu_scene_cost, _gpu_scene_upload_cost
                self.assertEqual(_gpu_scene_upload_cost(scene) - _gpu_scene_cost(scene), 192 * 160 * 4)

    def test_jpeg_pdf_color_and_mask_semantics_retain_existing_decoder(self):
        from tests.jpeg_fixtures import jpeg_bytes, jpeg_pdf
        cases = (jpeg_pdf(decode=True), jpeg_pdf(alpha=True), jpeg_pdf(color_transform=0),
                 jpeg_pdf(jpeg_bytes(mode='CMYK')), jpeg_pdf(jpeg_bytes(mode='L')))
        for data in cases:
            with self.subTest(case=cases.index(data)), pymupdf.open(stream=data, filetype='pdf') as doc:
                scene = compile_vector_page(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertNotIn('jpeg-ycbcr', scene.features)
                self.assertIn('image', scene.features)

    def test_jpeg_allows_exact_srgb_profile_but_retains_other_icc_conversion(self):
        from tests.jpeg_fixtures import jpeg_pdf
        from PIL import ImageCms
        with pymupdf.open(stream=jpeg_pdf(device_rgb=False), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0])
            self.assertIn('jpeg-ycbcr', scene.features)
            image = doc[0].get_images()[0][0]
            profile = doc.get_new_xref()
            doc.update_object(profile, '<< /N 3 >>')
            doc.update_stream(profile, ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
            doc.xref_set_key(image, 'ColorSpace', f'[/ICCBased {profile} 0 R]')
            scene = compile_vector_page(doc.reload_page(doc[0]))
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn('jpeg-ycbcr', scene.features)

    def test_tiny_display_of_large_jpeg_uses_gpu_source_and_keeps_refinement(self):
        from tests.jpeg_fixtures import jpeg_bytes, jpeg_pdf
        with pymupdf.open(stream=jpeg_pdf(jpeg_bytes((1600, 1200))), filetype='pdf') as doc:
            small = compile_vector_page(doc[0])
            large = compile_vector_page(doc[0], 4.)
            self.assertTrue(small.supported, small.reason)
            self.assertIn('jpeg-ycbcr', small.features)
            self.assertIn('image-downsample', small.features)
            self.assertIn('jpeg-ycbcr', large.features)
            self.assertIn('image-downsample', large.features)
            self.assertEqual(small.compiled_packet.count(jpeg_bytes((1600, 1200))), 1)

    def test_full_resolution_jpeg_reuses_scene_at_3200_percent(self):
        from tests.jpeg_fixtures import jpeg_pdf
        from pdfeditor.core import Document
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'jpeg.pdf'
            path.write_bytes(jpeg_pdf())
            document = Document(path)
            try:
                with patch.object(document, '_load_disk_gpu_scene', return_value=None), \
                        patch.object(document, '_save_disk_gpu_scene'):
                    first = document.gpu_vector_page(0)
                self.assertTrue(first.supported, first.reason)
                self.assertIn('jpeg-ycbcr', first.features)
                self.assertNotIn('image-downsample', first.features)
                with patch('pdfeditor.core.compile_vector_page', side_effect=AssertionError('unnecessary JPEG preparation')):
                    self.assertIs(document.gpu_vector_page(0, 32.), first)
                    self.assertIs(document.cached_gpu_vector_page(0, 32.), first)
            finally:
                document.close()

    def test_full_resolution_jpeg_with_raw_raster_still_refines(self):
        from tests.jpeg_fixtures import jpeg_pdf
        with pymupdf.open(stream=jpeg_pdf(), filetype='pdf') as doc:
            # A second, decoded image makes this a mixed-resolution scene.
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 8, 8), False)
            pixmap.clear_with(100)
            doc[0].insert_image((2, 2, 18, 18), pixmap=pixmap)
            scene = compile_vector_page(doc[0])
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn('jpeg-ycbcr', scene.features)
            self.assertIn('image-downsample', scene.features)

    def test_high_zoom_jpeg_crop_keeps_bounded_region_decoder(self):
        from tests.jpeg_fixtures import jpeg_pdf
        with pymupdf.open(stream=jpeg_pdf(), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0], 32., viewport=(90., 90., 110., 110.))
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn('jpeg-ycbcr', scene.features)
            self.assertLess(len(scene.compiled_packet), 192 * 160 * 4)

    def test_page_crop_does_not_upload_or_draw_hidden_jpeg_pixels(self):
        from tests.jpeg_fixtures import jpeg_pdf
        with pymupdf.open(stream=jpeg_pdf(), filetype='pdf') as doc:
            page = doc[0]
            page.set_cropbox((80, 80, 180, 180))
            scene = compile_vector_page(page, 4.)
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn('jpeg-ycbcr', scene.features)

    def test_oversize_jpeg_keeps_page_gpu_supported_with_bounded_decoder(self):
        import io
        from PIL import Image
        from tests.jpeg_fixtures import jpeg_pdf
        data = io.BytesIO()
        Image.new('RGB', (4097, 4097), '#3879ad').save(data, 'JPEG')
        with pymupdf.open(stream=jpeg_pdf(data.getvalue()), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0], 4.)
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn('jpeg-ycbcr', scene.features)

    def test_single_gradient_opacity_folds_but_protects_knockout_masks_and_overlap(self):
        from pdfeditor._path_packer import compile_scene
        from pdfeditor.gpu_raster import (VectorPage, VectorLinearGradient, VectorPath,
            GroupPush, GroupPop, ClipPush, ClipPop, MaskBegin, MaskEnd)
        rect = (("move", 0., 0.), ("line", 100., 0.), ("line", 100., 100.),
                ("line", 0., 100.), ("close",))
        gradient = VectorLinearGradient(rect, (0., 0.), (100., 0.),
                                       ((0., 0xff123456), (1., 0xffabcdef)))
        normal = GroupPush(.5, isolated=False)
        cases = (
            ((normal, ClipPush(rect), gradient, ClipPop(), GroupPop()), 3),
            ((GroupPush(1., knockout=True), normal, gradient, GroupPop(), GroupPop()), 5),
            ((GroupPush(1., knockout=True), ClipPush(rect), normal, gradient, GroupPop(), ClipPop(), GroupPop()), 5),
            ((normal, gradient, gradient, GroupPop()), 4),
            ((MaskBegin((0., 0., 100., 100.), False, 0), normal, gradient, GroupPop(),
              MaskEnd(), VectorPath(rect, fill_argb=0xff000000), ClipPop()), 7),
        )
        for items, expected in cases:
            with self.subTest(expected=expected, items=len(items)):
                compiled = compile_scene(VectorPage(True, items=items))
                self.assertEqual(compiled.command_count, expected)
                for end, capture, _depth in compiled.scope_plan():
                    if end is not None:
                        self.assertLess(end, expected)
                    if capture is not None:
                        self.assertLess(capture, expected)

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

    def test_small_knockout_group_stays_on_gpu(self):
        with pymupdf.open(stream=fixtures.nonisolated_single_path_pdf_bytes(alpha=1., knockout=True),
                          filetype='pdf') as doc:
            page = doc[0]
            page.set_mediabox(pymupdf.Rect(0, 0, 5000, 5000))
            form = page.get_xobjects()[0][0]
            doc.update_stream(form, doc.xref_stream(form) * 130)
            scene = compile_vector_page(page)
            self.assertTrue(scene.supported, scene.reason)
            self.assertNotIn('cpu-island', scene.features)
            self.assertNotIn('raster-shading', scene.features)

    def test_dense_knockout_group_retains_bounded_cpu_preparation(self):
        with pymupdf.open(stream=fixtures.nonisolated_single_path_pdf_bytes(alpha=1., knockout=True),
                          filetype='pdf') as doc:
            page = doc[0]
            page.set_mediabox(pymupdf.Rect(0, 0, 5000, 5000))
            form = page.get_xobjects()[0][0]
            doc.update_stream(form, doc.xref_stream(form) * 600)
            scene = compile_vector_page(page)
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn('cpu-island', scene.features)

    def test_function_shading_executes_as_gpu_mesh(self):
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
            self.assertIn('vector-mesh', scene.features)
            self.assertNotIn('raster-shading', scene.features)
            self.assertNotIn('image', scene.features)

    def test_native_features_distinguish_images_gradients_and_vector_patterns(self):
        for name in ('repeated_image_pdf_bytes', 'linear_gradient_pdf_bytes',
                     'radial_gradient_pdf_bytes', 'image_mask_pdf_bytes', 'tiling_pattern_pdf_bytes'):
            with self.subTest(name=name), pymupdf.open(stream=getattr(fixtures, name)(), filetype='pdf') as doc:
                scene = compile_vector_page(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertNotIn('raster-shading', scene.features)
                self.assertNotIn('cpu-island', scene.features)
                self.assertNotIn('raster-pattern', scene.features)
                if name == 'tiling_pattern_pdf_bytes':
                    self.assertNotIn('image', scene.features)
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
                    self.assertTrue(packet.startswith(b'LFSC\x03\0\0\0'))
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
            self.assertEqual(cropped.image_bytes,0)
            self.assertEqual(full.image_bytes,0)
            self.assertGreater(cropped.resource_count,1)
            self.assertLessEqual(full.image_bytes,64*1024*1024)

    def test_worker_and_document_use_packet_and_rebuild_without_old_recipe(self):
        from pdfeditor.gpu_scene_worker import main
        from pdfeditor.core import Document,_gpu_scene_cost
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'page.pdf';result=root/'scene'
            source.write_bytes(fixtures.soft_mask_pdf_bytes())
            with patch.object(reference,'_vector_page_from_pymupdf',side_effect=AssertionError), \
                    patch('pdfeditor.scene_disk_cache._limit',return_value=0):
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

    def test_cmyk_transparency_uses_gpu_rgb_approximation(self):
        with pymupdf.open(stream=fixtures.cmyk_group_pdf_bytes(alpha=.5),filetype='pdf') as doc:
            scene=compile_vector_page(doc[0])
            self.assertTrue(scene.supported,scene.reason)
            self.assertIn('rgb-transparency-approximation',scene.features)
            self.assertNotIn('cpu-island',scene.features)

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
