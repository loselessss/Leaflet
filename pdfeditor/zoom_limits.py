"""Physical-DPI display limits, separate from bounded raster preparation."""
MAX_ZOOM_PERCENT = 3200
MAX_RASTER_SCALE = 64.0  # Native worker/scene codec contract; vectors use display scale.
MAX_PREFETCH_RASTER_SCALE = 8.0  # Nearby pages are whole-page jobs, not viewport crops.
MAX_SAVED_ZOOM = 1024.0  # Defensive raw-coordinate bound; the view clamps on restore.


def actual_size_scale(view):
    # PDF points are 1/72 inch; Qt's physical DPI is device-independent.
    return max(1.0, float(view.viewport().physicalDpiX())) / 72.0


class ZoomLimits:
    @property
    def ZOOM_MAX(self):
        return MAX_ZOOM_PERCENT / 100.0 * actual_size_scale(self)
