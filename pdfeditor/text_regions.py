"""Conservative geometric text grouping and bounded paragraph replacement."""

import fitz


def _join(spans):
    text = spans[0]['text']
    for previous, span in zip(spans, spans[1:]):
        gap = span['bbox'][0] - previous['bbox'][2]
        if (text and not text[-1].isspace() and not span['text'][0].isspace()
                and gap > min(previous['size'], span['size']) * .16
                and span['text'][0] not in ',.;:!?)]}、。，！？'):
            text += ' '
        text += span['text']
    return text


def make_region(lines):
    spans = [span for line in lines for span in line['sources']]
    bounds = fitz.Rect(spans[0]['bbox'])
    for span in spans[1:]:
        bounds |= fitz.Rect(span['bbox'])
    first = spans[0]
    return dict(first, bbox=tuple(bounds), text='\n'.join(line['text'] for line in lines),
                sources=spans, mixed=any(
                    span['font'] != first['font'] or abs(span['size']-first['size']) > .1
                    or span['rgb'] != first['rgb'] for span in spans),
                multiline=len(lines) > 1)


def text_lines(spans):
    """Join horizontal fragments on a baseline, stopping at column-sized gaps."""
    rows = []
    for span in sorted(spans, key=lambda s: (s['origin'][1], s['bbox'][0])):
        if tuple(span.get('dir', (1, 0))) != (1, 0) or span.get('wmode', 0):
            continue
        row = next((r for r in reversed(rows)
                    if abs(r[0]['origin'][1]-span['origin'][1])
                    <= min(r[0]['size'], span['size']) * .22), None)
        if row is None:
            rows.append([span])
        else:
            row.append(span)
    lines = []
    for row in rows:
        pieces = []
        for span in sorted(row, key=lambda s: s['bbox'][0]):
            if pieces and (span['bbox'][0]-pieces[-1]['bbox'][2]
                           > min(span['size'], pieces[-1]['size']) * 1.4):
                lines.append(make_region([dict(sources=pieces, text=_join(pieces))]))
                pieces = []
            pieces.append(span)
        if pieces:
            lines.append(make_region([dict(sources=pieces, text=_join(pieces))]))
    return sorted(lines, key=lambda s: (s['bbox'][1], s['bbox'][0]))


def selected_region(lines, rect):
    """A drag selects complete fragments whose centers lie inside its box."""
    rect = fitz.Rect(rect)
    selected = []
    for line in lines:
        spans = [s for s in line['sources'] if rect.contains(
            (fitz.Rect(s['bbox']).tl + fitz.Rect(s['bbox']).br) / 2)]
        if spans:
            selected.append(make_region([dict(sources=spans, text=_join(spans))]))
    return make_region(selected) if selected else None


def layout_region(document, index, region, text, size, rgb, *, box=None,
                  fontname='korea', fontfile=None, align=0, lineheight=1.2):
    """Validate before mutation and prepare the exact PDF textbox drawing."""
    document.ensure_editable()
    fontname, font = document._edit_font(fontname, fontfile)
    document._validate_edit_glyphs(font, text)
    bounds = fitz.Rect(box or region['bbox'])
    page_bounds = document._doc[index].rect * document._doc[index].derotation_matrix
    if bounds.is_empty or not page_bounds.contains(bounds):
        raise ValueError('텍스트 상자는 페이지 안에 있어야 합니다. / Keep the text box inside the page.')
    with fitz.open() as scratch:
        page = scratch.new_page(width=page_bounds.width, height=page_bounds.height)
        remaining = page.insert_textbox(bounds, text, fontsize=size, fontname=fontname,
            fontfile=fontfile, color=rgb, align=align, lineheight=lineheight)
        if remaining < 0:
            raise ValueError('글이 상자를 넘칩니다. 상자를 늘리거나 글자 크기를 줄여 주세요. / Text overflows the box.')
        # Reuse the tested PDF drawing, so preview validation and output agree.
        return scratch.tobytes() if text.strip() else None


def replace_region(document, index, region, text, size, rgb, **options):
    drawing = layout_region(document, index, region, text, size, rgb, **options)
    page = document._doc[index]
    # Existing redaction annotations must not be applied as a side effect.
    if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in (page.annots() or ())):
        raise ValueError('기존 삭제 표시를 먼저 처리해 주세요. / Resolve existing redactions first.')
    selected = {(tuple(s['bbox']), s['text']) for s in region['sources']}
    for span in document.spans(index):
        if (tuple(span['bbox']), span['text']) not in selected and any(
                fitz.Rect(span['bbox']).intersects(fitz.Rect(s['bbox'])) for s in region['sources']):
            raise ValueError('선택 밖의 글자가 겹쳐 있습니다. 선택 범위를 조정해 주세요. / Overlapping unselected text.')
    cleanups = []
    for span in region['sources']:
        if document.is_scanned_area(index, span['bbox']):
            cleanups.append((span['bbox'], document.sample_bg_fg(index, span['bbox'])[0]))
    for span in region['sources']:
        page.add_redact_annot(span['bbox'], fill=None, cross_out=False)
    page.apply_redactions(images=0, graphics=0)
    page = document._doc[index]
    for bbox, bg in cleanups:
        page.draw_rect(bbox, color=None, fill=bg, overlay=True)
    if drawing:
        with fitz.open(stream=drawing, filetype='pdf') as source:
            # show_pdf_page uses displayed coordinates on rotated target pages.
            rotation = page.rotation
            try:
                page.set_rotation(0)
                page.show_pdf_page(page.rect, source, 0, overlay=True)
            finally:
                page.set_rotation(rotation)
