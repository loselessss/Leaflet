"""Bounded LZ4 scene archive in RAM; packing never blocks the GUI thread."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from .render_memory import MIB

_packer = ThreadPoolExecutor(max_workers=1, thread_name_prefix='scene-ram')


class SceneMemoryCache:
    def __init__(self):
        self.entries = OrderedDict()
        self.bytes = 0
        self.limit = 0
        self.job = None
        self.hits = 0

    def clear(self):
        if self.job is not None:
            self.job[0].cancel()
        self.job = None
        self.entries.clear()
        self.bytes = 0

    def trim(self, limit):
        self.limit = max(0, limit)
        if self.limit == 0:
            self.clear()
            return
        self.poll()
        while self.bytes > self.limit and self.entries:
            _key, (_metadata, blob) = self.entries.popitem(last=False)
            self.bytes -= len(blob)
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
        self.bytes += len(blob)
        while self.bytes > self.limit and self.entries:
            _key, (_metadata, old) = self.entries.popitem(last=False)
            self.bytes -= len(old)

    def store(self, key, scene):
        self.poll()
        packet = scene.compiled_packet
        if (self.job is not None or not scene.supported or scene.viewport is not None or
                not packet or not 64 * 1024 <= len(packet) <= min(32 * MIB, self.limit)):
            return False
        from .scene_cache_packet import encode
        while self.bytes + len(packet) > self.limit and self.entries:
            _key, (_metadata, old) = self.entries.popitem(last=False)
            self.bytes -= len(old)
        self.bytes += len(packet)  # Charge the in-flight source, not just its compressed output.
        self.job = (_packer.submit(encode, scene), key,
                    (scene.raster_scale, scene.features), len(packet), scene)
        return True

    def contains(self, index, scale, variant):
        self.poll()
        if self.job is not None and self.job[1][0] == index and self.job[1][2] == variant:
            density, features = self.job[2]
            if density >= scale or 'image-downsample' not in features:
                return True
        return self._key(index, scale, variant) is not None

    def _key(self, index, scale, variant):
        for key, ((density, features), _blob) in reversed(self.entries.items()):
            if key[0] == index and key[2] == variant and (
                    density >= scale or 'image-downsample' not in features):
                return key
        return None

    def take(self, index, scale, variant):
        self.poll()
        if self.job is not None and self.job[1][0] == index and self.job[1][2] == variant:
            density, features = self.job[2]
            if density >= scale or 'image-downsample' not in features:
                future, _key, _metadata, raw_bytes, scene = self.job
                future.cancel()
                self.job = None
                self.bytes -= raw_bytes
                self.hits += 1
                return scene
        key = self._key(index, scale, variant)
        if key is None:
            return None
        _metadata, blob = self.entries.pop(key)
        self.bytes -= len(blob)
        from .scene_cache_packet import decode
        try:
            scene = decode(blob)
        except (ValueError, RuntimeError, ImportError, MemoryError):
            return None
        self.hits += 1
        return scene
