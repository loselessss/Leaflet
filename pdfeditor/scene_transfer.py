"""Private worker transport retaining packed float64 paths through GPU upload."""
from dataclasses import fields
import io
import pickle
import struct
from dataclasses import replace


class PackedCommands:
    __slots__ = ('data', 'count')

    def __init__(self, data, count):
        self.data, self.count = data, count

    def __len__(self):
        return self.count

    def __sizeof__(self):
        return object.__sizeof__(self) + len(self.data)

    __hash__ = None

    @property
    def native_key(self):
        return self.data

    def __eq__(self, other):
        if isinstance(other, PackedCommands):
            return self.data == other.data
        if isinstance(other, tuple):
            return tuple(self) == other
        return NotImplemented

    def __iter__(self):
        # Compatibility for CPU-side refinement/cache analysis. Never retained.
        names = {1: ('move', 2), 2: ('line', 2), 3: ('cubic', 6), 4: ('close', 0)}
        offset = 0
        while offset < len(self.data):
            kind, count = names[self.data[offset]]
            offset += 1
            values = struct.unpack_from('<' + 'd'*count, self.data, offset)
            offset += count*8
            yield (kind, *values)

    def __getitem__(self, index):
        return tuple(self)[index]


def _restore_item(kind, values):
    return kind(*values)


def _restore_pixels(packet):
    from ._path_packer import decompress_buffer
    return decompress_buffer(packet)


def _restore_compiled_page(scene, packet):
    return replace(scene,compiled_packet=_restore_pixels(packet))


class _CompiledPageTransfer:
    def __init__(self,scene,packet):
        self.scene,self.packet=replace(scene,compiled_packet=b''),packet

    def __reduce__(self):
        return _restore_compiled_page,(self.scene,self.packet)


class _CompressedImage:
    def __init__(self, packet):
        self.packet = packet

    def __reduce__(self):
        return _restore_pixels, (self.packet,)


def _prepare_images(scene, workers):
    from .gpu_raster import VectorImage, MAX_GPU_IMAGE_BYTES
    images = {id(item.pixels): item.pixels for item in scene.drawables
              if isinstance(item, VectorImage) and len(item.pixels) >= 64*1024}
    total = sum(map(len, images.values()))
    if total < 8*1024*1024 or total > MAX_GPU_IMAGE_BYTES:
        return {}
    try:
        from ._path_packer import compress_buffers
        packets = compress_buffers(list(images.values()), workers)
    except (ImportError, MemoryError):
        return {}
    return {identity: _CompressedImage(packet) for identity, packet in zip(images, packets)
            if packet is not None}


class _ScenePickler(pickle.Pickler):
    def __init__(self, stream, images=None):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self.paths = {}
        self.images = images or {}

    def reducer_override(self, value):
        from .gpu_raster import (VectorPath, ClipPush, ClipStrokePush,
                                 VectorLinearGradient, VectorRadialGradient, VectorImage)
        if type(value) is VectorImage and id(value.pixels) in self.images:
            values = tuple(self.images[id(value.pixels)] if field.name == 'pixels'
                           else getattr(value, field.name) for field in fields(value))
            return _restore_item, (type(value), values)
        if type(value) in (VectorPath, ClipPush, ClipStrokePush,
                           VectorLinearGradient, VectorRadialGradient):
            commands = value.commands
            if not isinstance(commands, PackedCommands):
                identity = id(commands)
                if identity not in self.paths:
                    from ._path_packer import encode_commands
                    self.paths[identity] = PackedCommands(encode_commands(commands), len(commands))
                commands = self.paths[identity]
            values = tuple(commands if field.name == 'commands' else getattr(value, field.name)
                           for field in fields(value))
            return _restore_item, (type(value), values)
        return NotImplemented


def dump(scene, stream, *, parallel_workers=0):
    packet=getattr(scene,'compiled_packet',b'')
    if packet:
        if parallel_workers and 8*1024*1024<=len(packet)<=64*1024*1024:
            from ._path_packer import compress_buffers
            compressed=compress_buffers([packet],parallel_workers)[0]
            if compressed is not None:
                scene=_CompiledPageTransfer(scene,compressed)
        pickle.dump(scene,stream,protocol=pickle.HIGHEST_PROTOCOL)
        return
    try:
        from ._path_packer import encode_commands
    except ImportError:
        pickle.dump(scene, stream, protocol=pickle.HIGHEST_PROTOCOL)
    else:
        images = _prepare_images(scene, parallel_workers) if parallel_workers else None
        _ScenePickler(stream, images).dump(scene)


def dumps(scene, *, parallel_workers=0):
    stream = io.BytesIO()
    dump(scene, stream, parallel_workers=parallel_workers)
    return stream.getvalue()
