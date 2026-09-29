import unittest
from unittest.mock import patch
from collections import OrderedDict

from pdfeditor.render_memory import MIB, policy
from pdfeditor.core import Document, _gpu_scene_cost
from pdfeditor.gpu_raster import VectorPage, VectorPath


class RenderMemoryTests(unittest.TestCase):
    def test_more_memory_allows_more_scenes_but_pressure_stops_prefetch(self):
        low = policy(8 * 1024 * MIB, 2 * 1024 * MIB)
        high = policy(32 * 1024 * MIB, 16 * 1024 * MIB)
        self.assertGreater(high.scene_bytes, low.scene_bytes)
        self.assertGreater(high.prefetch_pages, low.prefetch_pages)
        self.assertLessEqual(high.scene_bytes, 1024 * MIB)
        self.assertEqual(policy(32 * 1024 * MIB, 256 * MIB).prefetch_pages, 0)

    def test_speculative_result_cannot_evict_current_scene(self):
        doc = Document.__new__(Document)
        doc._gpu_vector_cache = OrderedDict()
        doc._gpu_vector_cache_bytes = 0
        scene = VectorPage(True, items=(VectorPath((("move", 0., 0.),)),))
        cost = _gpu_scene_cost(scene)
        with patch.object(doc, "gpu_scene_memory_budget", return_value=cost + 1):
            doc.install_gpu_vector_page(0, scene, persist=False)
            self.assertIsNone(doc.install_gpu_vector_page(
                1, scene, persist=False, speculative=True))
        self.assertEqual([key[0] for key in doc._gpu_vector_cache], [0])

    def test_pressure_discards_speculative_pages_before_visible_page(self):
        doc = Document.__new__(Document)
        doc._gpu_vector_cache = OrderedDict()
        doc._gpu_vector_cache_bytes = 0
        scene = VectorPage(True, items=(VectorPath((("move", 0., 0.),)),))
        cost = _gpu_scene_cost(scene)
        for page in range(3):
            doc.install_gpu_vector_page(page, scene, persist=False)
        with patch.object(doc, "gpu_scene_memory_budget", return_value=cost + 1):
            doc.trim_gpu_scene_memory((0,))
        self.assertEqual([key[0] for key in doc._gpu_vector_cache], [0])
