"""RAM-only packed scene recovery, bounds and invalidation."""
from collections import OrderedDict
from concurrent.futures import Future
import unittest
from unittest.mock import patch

from pdfeditor.gpu_raster import VectorPage
from pdfeditor.render_memory import MIB, RenderMemory
from pdfeditor.scene_memory_cache import SceneMemoryCache


class SceneMemoryCacheTests(unittest.TestCase):
    def scene(self, **kwargs):
        return VectorPage(True, compiled_packet=b'LFSC\x02\0\0\0' + bytes(range(256))*512,
                          command_count=300, **kwargs)

    def test_ram_round_trip_is_lossless_and_reduces_memory(self):
        archive = SceneMemoryCache()
        archive.trim(MIB)
        scene = self.scene()
        self.assertTrue(archive.store((1, 1., False), scene))
        self.assertEqual(archive.bytes, len(scene.compiled_packet))
        archive.poll(wait=True)
        self.assertLess(archive.bytes, len(scene.compiled_packet)//2)
        self.assertTrue(archive.contains(1, 8., False))
        restored = archive.take(1, 8., False)
        self.assertEqual(restored.compiled_packet, scene.compiled_packet)
        self.assertEqual(restored.command_count, scene.command_count)
        self.assertEqual(archive.bytes, 0)
        self.assertEqual(archive.hits, 1)

    def test_inflight_page_can_be_reused_without_waiting_for_compression(self):
        archive = SceneMemoryCache()
        archive.trim(MIB)
        future = Future()
        scene = self.scene()
        with patch('pdfeditor.scene_memory_cache._packer.submit', return_value=future):
            archive.store((1, 1., False), scene)
        self.assertIs(archive.take(1, 1., False), scene)
        self.assertTrue(future.cancelled())
        self.assertEqual(archive.bytes, 0)

    def test_packed_ram_retains_more_than_128_pages_when_bytes_fit(self):
        archive = SceneMemoryCache()
        archive.trim(MIB)
        for page in range(140):
            self.assertTrue(archive.store((page, 1., False), self.scene()))
            archive.poll(wait=True)
        self.assertEqual(len(archive.entries), 140)
        self.assertLess(archive.bytes, archive.limit)
        archive.trim(0)
        self.assertEqual(len(archive.entries), 0)

    def test_pressure_and_clear_discard_pending_results_and_density_is_respected(self):
        archive = SceneMemoryCache()
        archive.trim(MIB)
        future = Future()
        future.set_running_or_notify_cancel()
        scene = self.scene(features=('image-downsample',))
        with patch('pdfeditor.scene_memory_cache._packer.submit', return_value=future):
            archive.store((1, 1., False), scene)
        self.assertFalse(archive.contains(1, 2., False))
        self.assertFalse(archive.contains(1, 1., True))
        archive.trim(0)
        future.set_result(b'late result')
        archive.poll()
        self.assertIsNone(archive.take(1, 1., False))
        self.assertEqual(archive.bytes, 0)
        self.assertFalse(archive.store((2, 1., False), scene))

    def test_document_recovers_from_ram_without_disk_or_pdf_compilation(self):
        from pdfeditor.core import Document
        doc = Document.__new__(Document)
        doc._gpu_vector_cache = OrderedDict()
        doc._gpu_vector_cache_bytes = 0
        doc._display_cache = {}
        doc._gpu_scene_probe_cache = {}
        doc._render_generation = 0
        scene = self.scene()
        with patch.object(doc, 'gpu_scene_memory_budget', return_value=2*MIB), \
                patch('pdfeditor.core.render_memory', return_value=RenderMemory(3*MIB, 2)):
            doc.install_gpu_vector_page(0, scene, persist=False)
            doc.install_gpu_vector_page(1, scene, persist=False)
            doc.reserve_gpu_scene_memory(2*MIB, protected=(0,))
            doc._gpu_packed_cache.poll(wait=True)
            self.assertIn((0, 1., False), doc._gpu_vector_cache)
            self.assertTrue(doc.has_packed_gpu_scene(1))
            self.assertIsNone(doc.cached_gpu_vector_page(1, memory_only=True, restore_compressed=False))
            with patch.object(doc, '_load_disk_gpu_scene', side_effect=AssertionError('disk access')), \
                    patch('pdfeditor.core.compile_vector_page', side_effect=AssertionError('PDF compile')):
                restored = doc.gpu_vector_page(1, raster_scale=2.)
            self.assertEqual(restored.compiled_packet, scene.compiled_packet)
            doc.reserve_gpu_scene_memory(2*MIB, protected=(0,))
            doc._gpu_packed_cache.poll(wait=True)
            doc.invalidate_render(1)
            self.assertFalse(doc.has_packed_gpu_scene(1))
            self.assertEqual(doc._gpu_packed_cache.bytes, 0)
