"""Numerical and ordering compatibility of native extraction helpers."""
import random
import struct
import unittest
from unittest.mock import patch

from pdfeditor import gpu_raster as raster


def exact(value):
    if isinstance(value, float):
        return struct.pack('<d', value)
    if isinstance(value, (tuple, list)):
        return tuple(exact(item) for item in value)
    return value


@unittest.skipIf(raster._rust_geometry is None, 'Rust geometry helpers not built')
class GeometryCompilerTests(unittest.TestCase):
    def test_transforms_and_bounds_match_float64_operation_order(self):
        rng = random.Random(924)
        matrices = [None, (1., 0., 0., 1., 0., 0.),
                    (0., -1., 1., 0., -17., 29.), (0., 0., 0., 0., 0., 0.)]
        matrices += [tuple(rng.uniform(-1e5, 1e5) for _ in range(6)) for _ in range(40)]
        paths = [(), (('close',),)]
        for _ in range(12):
            paths.append((('move', rng.uniform(-1e9, 1e9), rng.uniform(-1e9, 1e9)),
                          ('cubic', *(rng.uniform(-1e9, 1e9) for _ in range(6))),
                          ('line', -0.0, 1e-310), ('close',)))
        paths += [(('move', float('nan'), -0.), ('line', 5., float('inf'))),
                  (('move', 5., 0.), ('line', float('nan'), float('-inf'))),
                  (('move', -0., 0.), ('line', 0., -0.)),
                  (('move', 1e308, -1e308), ('line', 1e-310, -1e-310))]
        for matrix in matrices:
            for commands in paths:
                self.assertEqual(exact(raster._commands_bbox(commands, matrix)),
                                 exact(raster._python_commands_bbox(commands, matrix)))
                if matrix is not None:
                    self.assertEqual(exact(raster._transform_commands(commands, matrix)),
                                     exact(raster._python_transform_commands(commands, matrix)))

    def test_merge_preserves_order_style_and_approximate_color(self):
        items = [raster.VectorPath((('move', 0., 0.), ('line', 2., 3.), ('close',)),
                                   fill_argb=0xff123456, transform=(1., 0., 0., 1., 5., 6.)),
                 raster.VectorPath((('move', 7., 8.), ('line', 9., 10.)),
                                   fill_argb=0xff123457, shading=True)]
        for approximate in (False, True):
            result = raster._merged_fill_path(items, approximate_color=approximate)
            with patch.object(raster, '_rust_geometry', None):
                expected = raster._merged_fill_path(items, approximate_color=approximate)
            self.assertEqual(result, expected)

    def test_fallback_and_invalid_paths(self):
        commands = (('move', 1., 2.), ('line', 3., 4.))
        with patch.object(raster, '_rust_geometry', None):
            self.assertEqual(raster._commands_bbox(commands), (1., 2., 3., 4.))
        self.assertEqual(raster._commands_bbox((('move', '1.5', '2.5'),)), (1.5, 2.5, 1.5, 2.5))
        self.assertEqual(raster._commands_bbox([['move', 1., 2.]]), (1., 2., 1., 2.))
        with self.assertRaises(ValueError):
            raster._transform_commands((('invalid', 1., 2.),), (1., 0., 0., 1., 0., 0.))
        with self.assertRaises(IndexError):
            raster._commands_bbox((('move', 1.),))


if __name__ == '__main__':
    unittest.main()
