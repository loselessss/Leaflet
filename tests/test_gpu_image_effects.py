"""Native ICC/mask preparation and retained vector pattern regressions."""
import io
import pickle
import struct
import unittest
from unittest.mock import patch
import pymupdf
from PIL import ImageCms
from pdfeditor.rust_scene_compiler import compile_vector_page
from tests import test_gpu_raster as fixtures
from tests import test_rust_scene_gpu as gpu_helpers
from tests.jpeg_fixtures import jpeg_pdf


def cmyk_mask_pdf():
    with pymupdf.open(stream=fixtures.cmyk_image_pdf_bytes(), filetype='pdf') as doc:
        mask = doc.get_new_xref()
        doc.update_object(mask, '<< /Type /XObject /Subtype /Image /Width 2 /Height 2 '
                                '/ColorSpace /DeviceGray /BitsPerComponent 8 >>')
        doc.update_stream(mask, bytes((0, 64, 128, 255)))
        doc.xref_set_key(5, 'SMask', f'{mask} 0 R')
        return doc.tobytes()


def pattern_pdf(*, size=128, step=(8, 8), matrix=(1, 0, 0, 1, 0, 0)):
    with pymupdf.open(stream=fixtures.tiling_pattern_pdf_bytes(), filetype='pdf') as doc:
        doc[0].set_mediabox((0, 0, size, size))
        doc.update_stream(doc[0].get_contents()[0], f'/P1 scn 0 0 {size} {size} re f'.encode())
        doc.xref_set_key(5, 'XStep', str(step[0]))
        doc.xref_set_key(5, 'YStep', str(step[1]))
        doc.xref_set_key(5, 'Matrix', '[' + ' '.join(map(str, matrix)) + ']')
        return doc.tobytes()


class ImageEffectCompilerTests(unittest.TestCase):
    def test_masked_rgb_jpeg_keeps_original_stream_and_gpu_mask(self):
        from tests.jpeg_fixtures import jpeg_bytes
        encoded = jpeg_bytes()
        with pymupdf.open(stream=jpeg_pdf(encoded, alpha=True), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn('jpeg-ycbcr', scene.features)
        self.assertIn('gpu-image-mask', scene.features)
        self.assertIn(encoded, scene.compiled_packet)
    def test_color_profile_and_mask_survive_binary_and_worker_storage(self):
        from pdfeditor.scene_cache_packet import encode, decode
        with pymupdf.open(stream=cmyk_mask_pdf(), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn('gpu-color-management', scene.features)
        self.assertIn('gpu-image-mask', scene.features)
        self.assertEqual(decode(encode(scene)), scene)
        self.assertEqual(pickle.loads(pickle.dumps(scene)), scene)

    def test_nondefault_rgb_profile_uses_gpu_conversion(self):
        with pymupdf.open(stream=jpeg_pdf(), filetype='pdf') as doc:
            profile = doc.get_new_xref()
            doc.update_object(profile, '<< /N 3 >>')
            doc.update_stream(profile, ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
            doc.xref_set_key(doc[0].get_images()[0][0], 'ColorSpace', f'[/ICCBased {profile} 0 R]')
            scene = compile_vector_page(doc[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertIn('gpu-color-management', scene.features)

    def test_dense_pattern_is_bounded_independently_of_cell_count(self):
        for size in (128, 1024):
            with self.subTest(size=size), pymupdf.open(stream=pattern_pdf(size=size), filetype='pdf') as doc:
                scene = compile_vector_page(doc[0])
                self.assertTrue(scene.supported, scene.reason)
                self.assertIn('gpu-pattern', scene.features)
                self.assertNotIn('raster-pattern', scene.features)
                self.assertNotIn('image-downsample', scene.features)
                self.assertLess(scene.command_count, 10)
                self.assertLess(len(scene.compiled_packet), 4096)

    def test_overlapping_pattern_retains_existing_path(self):
        with pymupdf.open(stream=pattern_pdf(size=32, step=(4, 4)), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertNotIn('gpu-pattern', scene.features)

    def test_empty_pattern_does_not_fail_page_gpu_preparation(self):
        with pymupdf.open(stream=pattern_pdf(size=128), filetype='pdf') as doc:
            doc.update_stream(5, b'')
            scene = compile_vector_page(doc[0])
        self.assertTrue(scene.supported, scene.reason)
        self.assertNotIn('gpu-pattern', scene.features)

    def test_high_zoom_cmyk_mask_region_keeps_gpu_conversion_and_bounds_memory(self):
        from pdfeditor.mupdf_path import compile_page
        with pymupdf.open(stream=cmyk_mask_pdf(), filetype='pdf') as doc:
            compiled = compile_page(doc[0], 32., (50., 120., 100., 170.))
            self.assertIn('gpu-color-management', compiled.features)
            self.assertIn('gpu-image-mask', compiled.features)
            self.assertLess(compiled.image_bytes, 1024 * 1024)

    def test_bad_color_image_and_pattern_metadata_are_rejected(self):
        from pdfeditor._path_packer import compile_native_scene
        payload = struct.pack('<6dd7I', 1., 0., 0., 1., 0., 0., 1., 1, 0, 1, 4, 0, 0, 0)
        with self.assertRaises(ValueError):
            compile_native_scene(struct.pack('<IQ', 26, len(payload)) + payload)
        payload = struct.pack('<16dQ', 1., 0., 0., 1., 0., 0., 0., 0., 20., 20.,
                              0., 0., 8., 8., 4., 8., 0)
        with self.assertRaises(ValueError):
            compile_native_scene(struct.pack('<IQ', 25, len(payload)) + payload)


class ImageEffectGpuTests(unittest.TestCase):
    setUpClass = classmethod(gpu_helpers.RustSceneGpuTests.setUpClass.__func__)
    setUp = gpu_helpers.RustSceneGpuTests.setUp
    tearDown = gpu_helpers.RustSceneGpuTests.tearDown

    def compare(self, data, transform=(1., 0., 0., 1., 0., 0.), *, tolerance=2.):
        from pdfeditor import gpu_raster
        from tests.benchmark_gpu_pipeline import render_sample
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            page = doc[0]
            self.view._page_sizes = {0: (page.rect.width, page.rect.height)}
            previous = gpu_raster.vector_page_from_pymupdf(page)
            current = compile_vector_page(page)
            self.assertTrue(current.supported, current.reason)
            frames = []
            for scene in (previous, current):
                self.view._native_vector_draws(0, scene)
                retained = self.view._d2d_vector_paths[0][3]
                frames.append(render_sample(self.surface, retained, transform, 256, 256, 'completed', .001)[3])
            error = sum(abs(a - b) for a, b in zip(*frames)) / len(frames[0])
            self.assertLess(error, tolerance, f'mean BGRA error={error:.4f}/255')
            return current

    def test_cmyk_black_and_separate_alpha_match_existing_render(self):
        for data in (fixtures.cmyk_image_pdf_bytes(), cmyk_mask_pdf(), fixtures.nonisolated_masked_image_pdf_bytes()):
            with self.subTest(masked=data != fixtures.cmyk_image_pdf_bytes()):
                self.compare(data)

    def test_shared_icc_transform_keeps_each_images_own_pixels(self):
        with pymupdf.open(stream=fixtures.cmyk_image_pdf_bytes(), filetype='pdf') as doc:
            second = doc.get_new_xref()
            doc.update_object(second, '<< /Type /XObject /Subtype /Image /Width 2 /Height 2 '
                                      '/ColorSpace /DeviceCMYK /BitsPerComponent 8 >>')
            doc.update_stream(second, bytes((0, 0, 0, 230, 0, 255, 0, 0, 0, 0, 255, 0, 255, 0, 0, 0)))
            doc.xref_set_key(doc[0].xref, 'Resources', f'<< /XObject << /A 5 0 R /B {second} 0 R >> >>')
            doc.update_stream(doc[0].get_contents()[0], b'q 100 0 0 100 10 30 cm /A Do Q q 100 0 0 100 140 30 cm /B Do Q')
            self.compare(doc.tobytes())

    def test_high_zoom_color_and_mask_crop_matches_full_scene(self):
        from tests.jpeg_fixtures import jpeg_bytes
        from tests.benchmark_gpu_pipeline import render_sample
        with pymupdf.open(stream=jpeg_pdf(jpeg_bytes((200, 160), mode='CMYK'), alpha=True), filetype='pdf') as doc:
            full = compile_vector_page(doc[0], 4.)
            crop = compile_vector_page(doc[0], 4., viewport=(48., 88., 112., 152.))
            self.assertTrue(crop.supported, crop.reason)
            self.assertIn('gpu-color-management', crop.features)
            self.assertIn('gpu-image-mask', crop.features)
            frames = []
            for scene in (full, crop):
                native = self.surface.create_rust_scene(scene, 256, 256)
                try:
                    frames.append(render_sample(self.surface, native, (4., 0., 0., 4., -192., -352.), 256, 256, 'completed', .001)[3])
                finally:
                    native.close()
            self.assertLess(sum(abs(a-b) for a,b in zip(*frames)) / len(frames[0]), 2.)

    def test_pattern_gap_rotation_and_high_zoom_keep_vector_edges(self):
        for step, matrix, transform in (
                ((8, 8), (1, 0, 0, 1, 0, 0), (1., 0., 0., 1., 0., 0.)),
                ((12, 10), (.9, .2, -.2, .9, 5, 7), (1., 0., 0., 1., 0., 0.)),
                ((8, 8), (1, 0, 0, 1, 0, 0), (8., 0., 0., 8., -48., -48.))):
            with self.subTest(step=step, matrix=matrix, transform=transform):
                scene = self.compare(pattern_pdf(step=step, matrix=matrix), transform,
                                     tolerance=3. if matrix[1] != 0 else 2.)
                self.assertIn('gpu-pattern', scene.features)

    def test_curved_pattern_stays_vector_when_magnified(self):
        with pymupdf.open(stream=pattern_pdf(size=128), filetype='pdf') as doc:
            doc.update_stream(5, b'1 0 0 rg 4 1 m 5.6569 1 7 2.3431 7 4 c '
                                  b'7 5.6569 5.6569 7 4 7 c 2.3431 7 1 5.6569 1 4 c '
                                  b'1 2.3431 2.3431 1 4 1 c f')
            self.compare(doc.tobytes(), (8., 0., 0., 8., -48., -48.))

    def test_pattern_with_nonzero_cell_origin_keeps_pdf_phase(self):
        from PIL import Image, ImageChops, ImageStat
        from tests.benchmark_gpu_pipeline import render_sample
        with pymupdf.open(stream=pattern_pdf(step=(10, 12)), filetype='pdf') as doc:
            doc.xref_set_key(5, 'BBox', '[1 2 9 10]')
            scene = compile_vector_page(doc[0])
            self.assertIn('gpu-pattern', scene.features)
            native = self.surface.create_rust_scene(scene, 128, 128)
            try:
                pixels = render_sample(self.surface, native, (1., 0., 0., 1., 0., 0.), 256, 256, 'completed', .001)[3]
            finally:
                native.close()
            # The old Python comparison extractor loses part of this cell's
            # BBox clip. MuPDF CPU output is the reference for the PDF phase.
            pixmap = doc[0].get_pixmap(alpha=False)
            expected = Image.new('RGB', (256, 256), 'white')
            expected.paste(Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples), (0, 0))
            actual = Image.frombytes('RGBA', (256, 256), pixels, 'raw', 'BGRA').convert('RGB')
            error = sum(ImageStat.Stat(ImageChops.difference(actual, expected)).mean) / 3
            self.assertLess(error, .1)

    def test_pattern_in_placed_type3_glyph_matches_cpu(self):
        from PIL import Image, ImageChops, ImageStat
        from tests.benchmark_gpu_pipeline import render_sample
        with pymupdf.open(stream=pattern_pdf(), filetype='pdf') as doc:
            glyph = doc.get_new_xref()
            doc.update_object(glyph, '<< >>')
            doc.update_stream(glyph, b'32 0 d0 /Pattern cs /P1 scn 0 0 32 32 re f')
            font = doc.get_new_xref()
            doc.update_object(font, f'<< /Type /Font /Subtype /Type3 /FontBBox [0 0 32 32] '
                                    f'/FontMatrix [.01 0 0 .01 0 0] /CharProcs << /A {glyph} 0 R >> '
                                    f'/Encoding << /Type /Encoding /Differences [65 /A] >> '
                                    f'/FirstChar 65 /LastChar 65 /Widths [32] /Resources << /Pattern << /P1 5 0 R >> >> >>')
            doc.xref_set_key(doc[0].xref, 'Resources', f'<< /Font << /F {font} 0 R >> >>')
            doc.update_stream(doc[0].get_contents()[0], b'BT /F 200 Tf 30 30 Td (A) Tj ET')
            scene = compile_vector_page(doc[0])
            self.assertTrue(scene.supported, scene.reason)
            self.assertIn('gpu-pattern', scene.features)
            native = self.surface.create_rust_scene(scene, 128, 128)
            try:
                pixels = render_sample(self.surface, native, (1., 0., 0., 1., 0., 0.), 256, 256, 'completed', .001)[3]
            finally:
                native.close()
            pixmap = doc[0].get_pixmap(alpha=False)
            expected = Image.new('RGB', (256, 256), 'white')
            expected.paste(Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples), (0, 0))
            actual = Image.frombytes('RGBA', (256, 256), pixels, 'raw', 'BGRA').convert('RGB')
            self.assertLess(sum(ImageStat.Stat(ImageChops.difference(actual, expected)).mean) / 3, 1.)

    def test_color_upload_inside_existing_frame_clip_is_safe(self):
        with pymupdf.open(stream=cmyk_mask_pdf(), filetype='pdf') as doc:
            scene = compile_vector_page(doc[0])
        self.surface.begin_frame(0xffffffff)
        try:
            from pdfeditor.gpu_raster import _rect_commands
            clip = self.surface.create_path(_rect_commands(0, 0, 256, 256))
            self.surface.push_clip_path(clip)
            try:
                native = self.surface.create_rust_scene(scene, 300, 240)
            finally:
                self.surface.pop_clip()
                clip.close()
            try:
                self.surface.draw_scene(native, (1., 0., 0., 1., 0., 0.))
            finally:
                native.close()
        finally:
            self.surface.end_frame()
