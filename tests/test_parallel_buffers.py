import pickle
import random
import struct
import unittest
from unittest.mock import patch

try:
    from pdfeditor._path_packer import compress_buffers, decompress_buffer
except ImportError:
    compress_buffers = None


@unittest.skipIf(compress_buffers is None, 'Rust parallel buffers not built')
class ParallelBufferTests(unittest.TestCase):
    def test_parallel_output_is_deterministic_and_lossless(self):
        sources=[b'abcd'*700000, bytes(range(256))*1000, b'xyz']
        reference=compress_buffers(sources,1)
        for workers in (2,4):
            self.assertEqual(compress_buffers(sources,workers),reference)
        for source,packet in zip(sources,reference):
            self.assertEqual(decompress_buffer(packet) if packet is not None else source,source)

    def test_incompressible_data_and_resource_limits(self):
        noise=random.Random(819).randbytes(1024*1024)
        self.assertEqual(compress_buffers([noise],2),[None])
        self.assertEqual(compress_buffers([],2),[])
        for workers in (0,5):
            with self.assertRaises(ValueError):
                compress_buffers([],workers)
        with self.assertRaises(ValueError):
            compress_buffers([b'x'*(1024*1024)]*65,2)

    def test_corrupted_packets_fail_without_oversized_allocation(self):
        header=b'LFZ1'+struct.pack('<Q',100)
        for packet in (b'',b'bad magic!!!',header,header+b'x',
                       header+struct.pack('<II',100,1)+b'x',
                       b'LFZ1'+struct.pack('<Q',64*1024*1024+1)):
            with self.subTest(packet=packet),self.assertRaises(ValueError):
                decompress_buffer(packet)

    def test_scene_roundtrip_preserves_images_aliases_and_small_job_bypass(self):
        from pdfeditor import scene_transfer as wire
        from pdfeditor.gpu_raster import VectorPage,VectorImage
        pixels=b'\x10\x20\x30\xff'*(2048*1024)
        image=VectorImage(pixels,2048,1024,8192,(1.,0.,0.,1.,0.,0.))
        scene=VectorPage(True,items=(image,image))
        restored=pickle.loads(wire.dumps(scene,parallel_workers=2))
        self.assertEqual(restored,scene)
        self.assertIs(restored.items[0].pixels,restored.items[1].pixels)
        self.assertLess(len(wire.dumps(scene,parallel_workers=2)),len(pixels)//10)
        small=VectorPage(True,items=(VectorImage(b'\0'*4,1,1,4,image.transform),))
        with patch('pdfeditor._path_packer.compress_buffers',side_effect=AssertionError('small job')):
            self.assertEqual(pickle.loads(wire.dumps(small,parallel_workers=2)),small)
