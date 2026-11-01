"""Keep both axes of touchpad scrolling in document viewports."""
import math

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication


def wheel_scroll_delta(event):
    """Prefer device-provided pixel distances to wheel-angle estimates."""
    pixels = event.pixelDelta()
    return event.angleDelta() if pixels.isNull() else pixels


def pan_wheel_event(view, event):
    """Handle pixel scrolling and horizontal/diagonal wheel input together.

    Leave ordinary vertical mouse wheels to the view's existing page-flip and
    Qt scrolling behavior. Callers also retain their zoom shortcut handling.
    """
    pixels = event.pixelDelta()
    angles = event.angleDelta()
    pixel_input = not pixels.isNull()
    previous_kind, remainders = getattr(view, '_wheel_pan_remainders', (None, [0., 0.]))
    if previous_kind != pixel_input or event.phase() in (Qt.ScrollBegin, Qt.ScrollEnd):
        remainders = [0., 0.]
    view._wheel_pan_remainders = (pixel_input, remainders)
    if not pixel_input and not angles.x():
        return False
    delta = pixels if pixel_input else angles
    for axis, bar, value in ((0, view.horizontalScrollBar(), delta.x()),
                             (1, view.verticalScrollBar(), delta.y())):
        scale = 1. if pixel_input else min(
            bar.pageStep(), bar.singleStep() * QApplication.wheelScrollLines()) / 120.
        movement = -value * scale
        if movement * remainders[axis] < 0:
            remainders[axis] = 0.
        offset = movement + remainders[axis]
        whole = math.trunc(offset)
        target = bar.value() + whole
        bar.setValue(target)
        remainders[axis] = (offset - whole if bar.minimum() < target < bar.maximum() else 0.)
    if event.phase() == Qt.ScrollEnd:
        remainders[:] = [0., 0.]
    event.accept()
    return True
