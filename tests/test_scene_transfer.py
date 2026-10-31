import pickle
import unittest
from unittest.mock import patch
from pdfeditor import scene_transfer as wire
from pdfeditor import gpu_raster as g
from pdfeditor.d2d_backend import _path_array


class SceneTransferTests(unittest.TestCase):
    def test_roundtrip_retains_shared_paths_and_exact_native_input(self):
        try:
            from pdfeditor._path_packer import encode_commands
        except ImportError:
            self.skipTest('Rust transport not built')
        commands = (('move', -0., 1e-310), ('cubic', 1., 2., 3., 4., 5., 6.), ('close',))
        scene = g.VectorPage(True, items=(g.VectorPath(commands, fill_argb=0xff112233),
                                         g.ClipPush(commands)))
        restored = pickle.loads(wire.dumps(scene))
        self.assertEqual(restored, scene)
        first = restored.items[0].commands
        self.assertIsInstance(first, wire.PackedCommands)
        self.assertIs(first, restored.items[1].commands)
        self.assertEqual(bytes(_path_array(commands)), bytes(_path_array(first)))
        with patch.object(wire.PackedCommands, '__iter__', side_effect=AssertionError('expanded')):
            self.assertEqual(bytes(_path_array(commands)), bytes(_path_array(first)))
        self.assertEqual(pickle.loads(wire.dumps(restored)), scene)

    def test_disk_encoding_and_budget_do_not_expand_for_cost(self):
        from pdfeditor.core import _gpu_scene_cost
        from pdfeditor.scene_disk_cache import _encode, _decode, _types
        try:
            from pdfeditor._path_packer import encode_commands
        except ImportError:
            self.skipTest('Rust transport not built')
        path = wire.PackedCommands(encode_commands((('move', 1., 2.),)), 1)
        scene = g.VectorPage(True, items=(g.VectorPath(path),))
        with patch.object(wire.PackedCommands, '__iter__', side_effect=AssertionError('expanded')):
            self.assertGreater(_gpu_scene_cost(scene), len(path.data))
        self.assertEqual(_decode(_encode(scene), _types()), scene)

    def test_malformed_wire_rejected_before_native_call(self):
        try:
            from pdfeditor._path_packer import pack_wire_path
        except ImportError:
            self.skipTest('Rust transport not built')
        for data, count in ((b'', 1), (b'\x03', 1), (b'\xff', 1), (b'\x04', 2)):
            with self.subTest(data=data), self.assertRaises(ValueError):
                _path_array(wire.PackedCommands(data, count))
