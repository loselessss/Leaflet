from dataclasses import replace
import os
import struct
import unittest
from unittest.mock import patch
from pdfeditor import scene_cache_packet as codec
from pdfeditor.gpu_raster import VectorPage


class SceneCachePacketTests(unittest.TestCase):
    def scene(self, payload=b''):
        return VectorPage(True, compiled_packet=codec.SCENE_MAGIC + payload,
                          raster_scale=8., command_count=27,
                          features=('rust-compiler', 'image', 'image-downsample', '한글'))

    def chunks_offset(self, scene):
        return len(codec.MAGIC) + codec.HEADER.size + sum(2 + len(s.encode()) for s in scene.features) + 32

    def test_compressed_packet_roundtrip_keeps_exact_metadata_and_bytes(self):
        scene = self.scene(b'rgba' * (1024 * 1024))
        data = codec.encode(scene)
        self.assertLess(len(data), len(scene.compiled_packet) // 2)
        self.assertEqual(codec.decode(data), scene)
        self.assertEqual(codec.decode(data).compiled_packet, scene.compiled_packet)

    def test_incompressible_and_small_packets_roundtrip_raw(self):
        for payload in (b'', b'abc', os.urandom(256 * 1024)):
            with self.subTest(size=len(payload)):
                scene = self.scene(payload)
                data = codec.encode(scene)
                self.assertEqual(data[self.chunks_offset(scene)], 0)
                self.assertEqual(codec.decode(data), scene)

    def test_chunks_cross_codec_boundaries_without_losing_bytes(self):
        # Smaller framing boundary exercises multiple independent Rust blocks.
        scene = self.scene(b'rgba' * (1024 * 1024))
        with patch.object(codec, 'CHUNK_BYTES', 1024 * 1024):
            data = codec.encode(scene)
            self.assertEqual(codec.decode(data), scene)

    def test_truncated_corrupt_metadata_payload_and_trailing_bytes_fail(self):
        scene = self.scene(b'abcdefgh')
        data = codec.encode(scene)
        cases = [data[:n] for n in (0, 7, 20, len(data) - 1)]
        cases.extend((b'LFDC\x02' + data[5:], data + b'x'))
        for at in (10, self.chunks_offset(scene) - 1, len(data) - 1):
            changed = bytearray(data)
            changed[at] ^= 1
            cases.append(bytes(changed))
        for bad in cases:
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                codec.decode(bad)

    def test_decoded_budget_and_inner_lz4_length_are_checked_before_decompression(self):
        scene = self.scene(b'a' * 200000)
        data = bytearray(codec.encode(scene))
        offset = self.chunks_offset(scene)
        self.assertEqual(data[offset], 1)
        struct.pack_into('<Q', data, offset + codec.CHUNK.size + 4, codec.CHUNK_BYTES + 1)
        with patch('pdfeditor._path_packer.decompress_buffer', side_effect=AssertionError), self.assertRaises(ValueError):
            codec.decode(bytes(data))
        data = bytearray(codec.encode(scene))
        # Raw packet size lives after scale, command count and feature count.
        struct.pack_into('<Q', data, len(codec.MAGIC) + 8 + 4 + 2, codec.MAX_PACKET + 1)
        with self.assertRaises(ValueError):
            codec.decode(bytes(data))

    def test_invalid_scene_metadata_and_mixed_python_draws_are_rejected(self):
        from pdfeditor.gpu_raster import VectorPath
        scene = self.scene(b'abc')
        for bad in (replace(scene, raster_scale=float('nan')),
                    replace(scene, command_count=1_048_577),
                    replace(scene, features=('x' * 257,)),
                    replace(scene, features=('x',) * 65),
                    replace(scene, viewport=(0, 0, 10, 10)),
                    replace(scene, compiled_packet=b'bad'),
                    replace(scene, items=(VectorPath((), fill_argb=0xff000000),))):
            with self.subTest(scene=bad), self.assertRaises(ValueError):
                codec.encode(bad)
