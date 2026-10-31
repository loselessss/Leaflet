"""The Rust fast path must preserve the existing Direct2D input bytes."""
import ctypes
import gc
import random
import unittest
from unittest.mock import patch

from pdfeditor import d2d_backend as backend


class PathPackerTests(unittest.TestCase):
    def test_fallback_and_buffer_lifetime(self):
        commands = (("move", 1, -2), ("cubic", 1, 2, 3, 4, 5, 6), ("close",))
        expected = bytes(backend._python_path_array(commands))
        packed = backend._path_array(commands)
        gc.collect()
        self.assertEqual(bytes(packed), expected)
        with patch.object(backend, "_rust_pack_path", None):
            self.assertEqual(bytes(backend._path_array(commands)), expected)

    def test_legacy_inputs_remain_supported(self):
        for commands in ([['move', 1, 2], ['close']],
                         (("move", "1.25", "-2.5"), ("close",))):
            self.assertEqual(bytes(backend._path_array(commands)),
                             bytes(backend._python_path_array(commands)))

    @unittest.skipIf(backend._rust_pack_path is None, "Rust extension not built")
    def test_float_rounding_and_zero_padding_match(self):
        self.assertEqual(ctypes.sizeof(backend._PathCommand), 28)
        randomizer = random.Random(641)
        values = [0.0, -0.0, 1e-45, -1e-45, 1e300, -1e300,
                  float('inf'), float('-inf'), float('nan')]
        values += [randomizer.uniform(-1e9, 1e9) for _ in range(1000)]
        commands = [("move", x, -x) for x in values]
        commands += [("cubic", *values[i:i+6]) for i in range(0, 990, 6)]
        commands += [("line", 1, 2), ("close",)]
        commands = tuple(commands)
        self.assertEqual(bytes(backend._rust_pack_path(commands)),
                         bytes(backend._python_path_array(commands)))

    @unittest.skipIf(backend._rust_pack_path is None, "Rust extension not built")
    def test_invalid_commands_raise_without_partial_output(self):
        for commands in ((), (("nope",),), (("move", 1),),
                         (("close", 0),), (("move", 1, 2), ("line", 1))):
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                backend._rust_pack_path(commands)


if __name__ == "__main__":
    unittest.main()
