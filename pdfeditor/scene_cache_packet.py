"""Bounded binary storage for opaque Rust GPU scenes; no executable objects."""
import hashlib
import math
import struct

MAGIC = b'LFDC\x01\0\0\0'
SCENE_MAGIC = b'LFSC\x04\0\0\0'
MAX_PACKET = 512 * 1024 * 1024
CHUNK_BYTES = 64 * 1024 * 1024  # Matches the independent Rust buffer codec limit.
MAX_FEATURES = 64
MAX_FEATURE_BYTES = 256
HEADER = struct.Struct('<dIHQH')
CHUNK = struct.Struct('<BII')
MAX_BLOB = (MAX_PACKET + 32 + len(MAGIC) + HEADER.size
            + MAX_FEATURES * (2 + MAX_FEATURE_BYTES)
            + ((MAX_PACKET + CHUNK_BYTES - 1) // CHUNK_BYTES) * CHUNK.size)


def _metadata(scale, count, features):
    if not math.isfinite(scale) or not 1 <= scale <= 64:
        raise ValueError('invalid cached scene scale')
    if type(count) is not int or not 0 <= count <= 1_048_576:
        raise ValueError('invalid cached command count')
    if not isinstance(features, tuple) or len(features) > MAX_FEATURES:
        raise ValueError('invalid cached features')
    encoded = []
    for feature in features:
        if not isinstance(feature, str):
            raise ValueError('invalid cached feature')
        raw = feature.encode('utf-8')
        if not 1 <= len(raw) <= MAX_FEATURE_BYTES:
            raise ValueError('invalid cached feature length')
        encoded.extend((struct.pack('<H', len(raw)), raw))
    return encoded


def encode(scene):
    packet = scene.compiled_packet
    if (not isinstance(packet, bytes) or not packet.startswith(SCENE_MAGIC)
            or not len(SCENE_MAGIC) <= len(packet) <= MAX_PACKET
            or not scene.supported or scene.viewport is not None
            or scene.paths or scene.items or scene.reason):
        raise ValueError('invalid compiled cache scene')
    scale = float(scene.raster_scale)
    features = _metadata(scale, scene.command_count, scene.features)
    count = (len(packet) + CHUNK_BYTES - 1) // CHUNK_BYTES
    prefix = b''.join((MAGIC, HEADER.pack(scale, scene.command_count,
                                         len(scene.features), len(packet), count), *features))
    digest = hashlib.sha256(prefix)
    digest.update(packet)
    parts = [prefix, digest.digest()]
    try:
        from ._path_packer import compress_buffers
    except ImportError:
        compress_buffers = None
    for start in range(0, len(packet), CHUNK_BYTES):
        raw = packet[start:start + CHUNK_BYTES]
        compressed = None
        if compress_buffers is not None and len(raw) >= 64 * 1024:
            compressed = compress_buffers([raw], 2 if len(raw) >= 8 * 1024 * 1024 else 1)[0]
        stored = raw if compressed is None else compressed
        parts.extend((CHUNK.pack(int(compressed is not None), len(raw), len(stored)), stored))
    return b''.join(parts)


def decode(data):
    if not isinstance(data, bytes) or len(data) > MAX_BLOB:
        raise ValueError('invalid cached scene size')
    view = memoryview(data)
    offset = 0

    def take(size):
        nonlocal offset
        if size < 0 or size > len(view) - offset:
            raise ValueError('truncated cached scene')
        result = view[offset:offset + size]
        offset += size
        return result

    if take(len(MAGIC)) != MAGIC:
        raise ValueError('invalid cached scene version')
    scale, commands, feature_count, packet_size, chunk_count = HEADER.unpack(take(HEADER.size))
    if not len(SCENE_MAGIC) <= packet_size <= MAX_PACKET or feature_count > MAX_FEATURES:
        raise ValueError('invalid cached scene budget')
    if chunk_count != (packet_size + CHUNK_BYTES - 1) // CHUNK_BYTES:
        raise ValueError('invalid cached chunk count')
    features = []
    for _ in range(feature_count):
        length, = struct.unpack('<H', take(2))
        if not 1 <= length <= MAX_FEATURE_BYTES:
            raise ValueError('invalid cached feature length')
        features.append(bytes(take(length)).decode('utf-8'))
    features = tuple(features)
    _metadata(scale, commands, features)
    digest = hashlib.sha256(view[:offset])
    expected_digest = bytes(take(32))
    parts = []
    remaining = packet_size
    for _ in range(chunk_count):
        codec, raw_size, stored_size = CHUNK.unpack(take(CHUNK.size))
        if raw_size != min(CHUNK_BYTES, remaining) or stored_size == 0 or stored_size > raw_size:
            raise ValueError('invalid cached chunk size')
        stored = take(stored_size)
        if codec == 0:
            if stored_size != raw_size:
                raise ValueError('invalid raw cached chunk')
            raw = stored
        elif codec == 1:
            if (len(stored) < 12 or stored[:4] != b'LFZ1'
                    or struct.unpack_from('<Q', stored, 4)[0] != raw_size):
                raise ValueError('invalid compressed cached chunk')
            from ._path_packer import decompress_buffer
            raw = decompress_buffer(bytes(stored))
            if len(raw) != raw_size:
                raise ValueError('invalid decoded cached chunk')
        else:
            raise ValueError('unknown cached scene codec')
        digest.update(raw)
        parts.append(raw)
        remaining -= raw_size
    if offset != len(view) or remaining or digest.digest() != expected_digest:
        raise ValueError('corrupt cached scene')
    packet = parts[0] if len(parts) == 1 and isinstance(parts[0], bytes) else b''.join(parts)
    if not packet.startswith(SCENE_MAGIC):
        raise ValueError('invalid cached GPU packet')
    from .gpu_raster import VectorPage
    return VectorPage(True, features=features, raster_scale=scale,
                      compiled_packet=packet, command_count=commands)
