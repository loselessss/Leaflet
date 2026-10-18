"""Screen-tolerance magnetic placement, independent of Qt and PDF mutation."""

from bisect import bisect_left
from dataclasses import dataclass


@dataclass(frozen=True)
class Guide:
    axis: int  # 0: vertical, 1: horizontal (display-page coordinates)
    position: float
    start: float
    end: float


class SnapTargets:
    """Index page/object edges and centers once, rather than on every pointer move."""

    def __init__(self, rectangles):
        self.axes = []
        for axis in (0, 1):
            targets = {}
            other = 1 - axis
            for rect in rectangles:
                for value in (rect[axis], (rect[axis] + rect[axis + 2]) / 2,
                              rect[axis + 2]):
                    low, high = rect[other], rect[other + 2]
                    if value in targets:
                        low = min(low, targets[value][0])
                        high = max(high, targets[value][1])
                    targets[value] = (low, high)
            self.axes.append((sorted(targets), targets))

    def place(self, rect, tolerance, *, bypass=False, allowed=(True, True)):
        """Return a translated rectangle and at most one nearest guide per axis.

        Always derive from the raw pointer rectangle, including when bypassing;
        toggling Ctrl must never accumulate snapping offsets.
        """
        result = list(rect)
        matches = []
        for axis in (0, 1):
            if not allowed[axis]:
                continue
            values, targets = self.axes[axis]
            best = None
            for anchor in (rect[axis], (rect[axis] + rect[axis + 2]) / 2,
                           rect[axis + 2]):
                index = bisect_left(values, anchor)
                for neighbor in (index - 1, index):
                    if 0 <= neighbor < len(values):
                        value = values[neighbor]
                        delta = value - anchor
                        if abs(delta) <= tolerance[axis]:
                            candidate = (abs(delta), value, delta)
                            if best is None or candidate < best:
                                best = candidate
            if best is not None:
                _, value, delta = best
                if not bypass:
                    result[axis] += delta
                    result[axis + 2] += delta
                matches.append((axis, value, targets[value]))
        guides = []
        for axis, value, (low, high) in matches:
            other = 1 - axis
            padding = tolerance[other]
            guides.append(Guide(axis, value, min(low, result[other]) - padding,
                                max(high, result[other + 2]) + padding))
        return tuple(result), guides
