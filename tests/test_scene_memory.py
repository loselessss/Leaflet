import unittest
from unittest.mock import patch
from pdfeditor.core import Document, _gpu_scene_cost
from pdfeditor.gpu_raster import VectorPage, VectorPath, VectorImage, _rgba_to_premul_bgra
from collections import OrderedDict


class SceneMemoryTests(unittest.TestCase):
    def test_alpha_conversion_matches_integer_reference_exhaustively(self):
        samples = bytes(component for alpha in range(256) for value in range(256)
                        for component in (value, 255-value, value//2, alpha))
        expected = bytes(component for alpha in range(256) for value in range(256)
                         for component in ((value//2*alpha+127)//255,
                                           ((255-value)*alpha+127)//255,
                                           (value*alpha+127)//255, alpha))
        self.assertEqual(_rgba_to_premul_bgra(samples, 256, 256), expected)
        opaque = bytes((12, 34, 56, 255))*100
        self.assertEqual(_rgba_to_premul_bgra(opaque, 10, 10), bytes((56, 34, 12, 255))*100)

    def test_vector_only_scenes_are_counted_and_evicted(self):
        doc = Document.__new__(Document)
        doc._gpu_vector_cache = OrderedDict()
        doc._gpu_vector_cache_bytes = 0
        scenes = [VectorPage(True, items=(VectorPath(
            tuple(("line", float(i), float(i+page)) for i in range(1000))),))
                  for page in range(3)]
        budget = max(_gpu_scene_cost(scene) for scene in scenes) + 1
        self.assertGreater(budget, 10000)
        with patch("pdfeditor.core.GPU_VECTOR_CACHE_BYTES", budget):
            for page, scene in enumerate(scenes):
                doc.install_gpu_vector_page(page, scene, persist=False)
        self.assertEqual(len(doc._gpu_vector_cache), 1)
        self.assertLessEqual(doc._gpu_vector_cache_bytes, budget)

    def test_shared_pixels_are_counted_once(self):
        pixels = b"x"*100000
        first = VectorImage(pixels, 250, 100, 1000, (1, 0, 0, 1, 0, 0))
        second = VectorImage(pixels, 250, 100, 1000, (1, 0, 0, 1, 20, 0))
        cost = _gpu_scene_cost(VectorPage(True, items=(first, second)))
        self.assertGreater(cost, 100000)
        self.assertLess(cost, 110000)
