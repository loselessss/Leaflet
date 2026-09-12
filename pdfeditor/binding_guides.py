"""Printable binding/folding guides in displayed page coordinates (no Qt)."""

import math
import pymupdf


def guide_points(width, height, edge, offset, inset, mirror=False, page=0):
    if edge not in ('left', 'right', 'top', 'bottom', 'vertical-center', 'horizontal-center'):
        raise ValueError('Unknown guide position')
    if not all(math.isfinite(v) and v >= 0 for v in (offset, inset)):
        raise ValueError('Invalid guide distance')
    if mirror and page % 2 and edge in ('left', 'right'):
        edge = 'right' if edge == 'left' else 'left'
    if edge in ('left', 'right', 'vertical-center'):
        x = offset if edge == 'left' else width-offset if edge == 'right' else width/2
        points = ((x, inset), (x, height-inset))
        valid = 0 < x < width and inset * 2 < height
    else:
        y = offset if edge == 'top' else height-offset if edge == 'bottom' else height/2
        points = ((inset, y), (width-inset, y))
        valid = 0 < y < height and inset * 2 < width
    if not valid:
        raise ValueError('안내선이 페이지 안에 들어오도록 위치와 끝 여백을 조절하세요. / Guide must fit inside the page.')
    return points


def add_guides(document, pages, *, edge='left', offset=42.52, inset=14.17,
               width=.5, dashed=True, gray=.45, mirror=False):
    document.ensure_editable()
    indices = sorted(set(pages))
    if not indices or any(not isinstance(i, int) or i < 0 or i >= document.page_count for i in indices):
        raise ValueError('Invalid page range')
    if not math.isfinite(width) or not .1 <= width <= 10 or not math.isfinite(gray) or not 0 <= gray <= 1:
        raise ValueError('Invalid guide style')
    prepared = []
    for index in indices:
        page = document._doc[index]
        points = guide_points(page.rect.width, page.rect.height, edge, offset, inset, mirror, index)
        prepared.append((index, tuple(pymupdf.Point(*p) * page.derotation_matrix for p in points)))
    for index, points in prepared:
        page = document._doc[index]
        page.draw_line(*points, color=(gray, gray, gray), width=width,
                       dashes='[3 3] 0' if dashed else None, overlay=True)
    document.invalidate_render()
