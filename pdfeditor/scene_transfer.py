"""Private worker transport retaining packed float64 paths through GPU upload."""
from dataclasses import fields
import io
import pickle
import struct


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


class _ScenePickler(pickle.Pickler):
    def __init__(self, stream):
        super().__init__(stream, protocol=pickle.HIGHEST_PROTOCOL)
        self.paths = {}

    def reducer_override(self, value):
        from .gpu_raster import (VectorPath, ClipPush, ClipStrokePush,
                                 VectorLinearGradient, VectorRadialGradient)
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


def dump(scene, stream):
    try:
        from ._path_packer import encode_commands
    except ImportError:
        pickle.dump(scene, stream, protocol=pickle.HIGHEST_PROTOCOL)
    else:
        _ScenePickler(stream).dump(scene)


def dumps(scene):
    stream = io.BytesIO()
    dump(scene, stream)
    return stream.getvalue()
