"""Bounded LZ4 scene archive in RAM; packing never blocks the GUI thread."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from .render_memory import MIB

try:
    from ._path_packer import PackedSceneIndex
except ImportError:
    PackedSceneIndex = None

_packer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='scene-ram')


class SceneMemoryCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.bytes = 0
        self.limit = 0
        self.job = None
        self.hits = 0
        self._index = PackedSceneIndex() if PackedSceneIndex is not None else None

    def clear(self):
        if self.job is not None:
            self.job[0].cancel()
        self.job = None
        self.entries.clear()
        if self._index is not None:
            self._index.clear()
        self.bytes = 0

    def _evict(self):
        key, ((_, _, viewport), blob) = self.entries.popitem(last=False)
        if self._index is not None:
            self._index.remove(*key[:3], viewport)
        self.bytes -= len(blob)

    def trim(self, limit):
        self.limit = max(0, limit)
        if self.limit == 0:
            self.clear()
            return
        self.poll()
        while self.bytes > self.limit and self.entries:
            self._evict()
        if self.bytes > self.limit and self.job is not None:
            self.job[0].cancel()
            self.bytes -= self.job[3]
            self.job = None

    def poll(self, *, wait=False):
        if self.job is None or (not wait and not self.job[0].done()):
            return
        future, key, metadata, raw_bytes, _scene = self.job
        self.job = None
        self.bytes -= raw_bytes
        try:
            blob = future.result()
        except (ValueError, TypeError, RuntimeError, ImportError, MemoryError):
            return
        if len(blob) >= raw_bytes * .9 or len(blob) > self.limit:
            return
        previous = self.entries.pop(key, None)
        if previous is not None:
            self.bytes -= len(previous[1])
        self.entries[key] = (metadata, blob)
        if self._index is not None:
            density, features, viewport = metadata
            self._index.insert(*key[:3], density, 'image-downsample' in features, viewport)
        self.bytes += len(blob)
        while self.bytes > self.limit and self.entries:
            self._evict()

    def store(self, key, scene):
        self.poll()
        packet = scene.compiled_packet
        if (self.job is not None or not scene.supported or
                not packet or not 64 * 1024 <= len(packet) <= min(32 * MIB, self.limit)):
            return False
        from .scene_cache_packet import encode
        while self.bytes + len(packet) > self.limit and self.entries:
            self._evict()
        self.bytes += len(packet)  # Charge the in-flight source, not just its compressed output.
        # Keep the bounds in RAM metadata. The existing disk format still
        # contains whole pages only.
        viewport = scene.viewport
        payload = scene if viewport is None else replace(scene, viewport=None)
        key = key if viewport is None else (*key, viewport)
        self.job = (_packer.submit(encode, payload), key,
                    (scene.raster_scale, scene.features, viewport), len(packet), scene)
        return True

    @staticmethod
    def _matches(key, metadata, index, scale, variant, viewport):
        density, features, coverage = metadata
        if (key[0] != index or key[2] != variant or
                (density < scale and 'image-downsample' in features)):
            return False
        if viewport is None:
            return coverage is None
        return coverage is not None and (
            coverage[0] <= viewport[0] + 1e-6 and coverage[1] <= viewport[1] + 1e-6
            and coverage[2] >= viewport[2] - 1e-6 and coverage[3] >= viewport[3] - 1e-6)

    def contains(self, index, scale, variant, *, viewport=None):
        self.poll()
        return (self.job is not None and self._matches(
                    self.job[1], self.job[2], index, scale, variant, viewport)
                or self._key(index, scale, variant, viewport) is not None)

    def _key(self, index, scale, variant, viewport):
        if self._index is not None:
            found = self._index.find(index, scale, variant, viewport)
            if found is None:
                return None
            stored_scale, coverage = found
            key = index, stored_scale, variant
            return key if coverage is None else (*key, coverage)
        for key, (metadata, _blob) in reversed(self.entries.items()):
            if self._matches(key, metadata, index, scale, variant, viewport):
                return key
        return None

    def take(self, index, scale, variant, *, viewport=None):
        self.poll()
        if self.job is not None and self._matches(
                self.job[1], self.job[2], index, scale, variant, viewport):
            future, _key, _metadata, raw_bytes, scene = self.job
            future.cancel()
            self.job = None
            self.bytes -= raw_bytes
            self.hits += 1
            return scene
        key = self._key(index, scale, variant, viewport)
        if key is None:
            return None
        (_, _, coverage), blob = self.entries.pop(key)
        if self._index is not None:
            self._index.remove(*key[:3], coverage)
        self.bytes -= len(blob)
        from .scene_cache_packet import decode
        try:
            scene = decode(blob)
        except (ValueError, RuntimeError, ImportError, MemoryError):
            return None
        self.hits += 1
        return scene if coverage is None else replace(scene, viewport=coverage)
