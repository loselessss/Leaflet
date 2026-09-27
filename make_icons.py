"""아이콘 생성 — Leaflet 앱 아이콘 + PDF/AI/EPS 문서 아이콘.

외부 이미지 없이 Pillow로 그린다(재생성 가능해야 로고 수정이 쉬움).
결과: assets/spdf.ico (앱), assets/spdf_doc.ico (연결된 PDF 파일용)

    python make_icons.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
SIZES = [16, 24, 32, 48, 64, 128, 256]

# 앱은 초록, 문서는 확장자별 색으로 구분한다.
PAPER = (255, 255, 255, 255)
EDGE = (203, 213, 225, 255)
FOLD = (226, 232, 240, 255)
ACCENT = (16, 112, 88, 255)
DOC_ACCENT = (190, 48, 62, 255)
AI_ACCENT = (166, 88, 10, 255)
EPS_ACCENT = (109, 70, 173, 255)


def draw_app_icon(px, accent=ACCENT, label=None):
    """A folded white leaflet and a green leaf; no text at small sizes."""
    scale = px * 4 / 256
    img = Image.new("RGBA", (px * 4, px * 4))
    d = ImageDraw.Draw(img)

    def points(coords):
        return [(round(x * scale), round(y * scale)) for x, y in coords]

    d.rounded_rectangle(points([(12, 12), (244, 244)]),
                        radius=round(54 * scale), fill=accent)
    d.polygon(points([(65, 43), (151, 43), (192, 84),
                      (192, 212), (65, 212)]), fill=PAPER)
    d.polygon(points([(151, 43), (151, 84), (192, 84)]),
              fill=((183, 220, 206, 255) if label is None else
                    tuple(round(v * 0.3 + 255 * 0.7) for v in accent[:3]) + (255,)))
    # Two cubic curves form a leaf pointing towards the folded corner.
    leaf = []
    for a, b, c, e in [((85, 175), (67, 121), (111, 102), (170, 102)),
                       ((170, 102), (170, 158), (130, 193), (85, 175))]:
        for i in range(33):
            t = i / 32
            leaf.append(tuple((1-t)**3*a[j] + 3*(1-t)**2*t*b[j]
                              + 3*(1-t)*t*t*c[j] + t**3*e[j]
                              for j in (0, 1)))
    d.polygon(points(leaf), fill=accent)
    d.line(points([(83, 184), (142, 126)]), fill=PAPER,
           width=max(1, round(7 * scale)))
    if label:
        box = points([(82, 181), (235, 237)])
        d.rounded_rectangle(box, radius=round(10 * scale), fill=accent,
                            outline=PAPER, width=max(1, round(4 * scale)))
        _centered(d, (*box[0], *box[1]), label,
                  _font(round(39 * scale)), PAPER)
    return img.resize((px, px), Image.Resampling.LANCZOS)


def _font(px):
    """굵은 산세리프 — 없으면 기본 폰트로 폴백."""
    for name in ("segoeuib.ttf", "arialbd.ttf", "calibrib.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered(d, box, text, font, fill):
    x0, y0, x1, y1 = box
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    d.text((x0 + (x1 - x0 - (r - l)) / 2 - l,
            y0 + (y1 - y0 - (b - t)) / 2 - t), text, font=font, fill=fill)


def draw_icon(px, label, accent):
    """Use the Leaflet mark with a contrasting file-type badge."""
    return draw_app_icon(px, accent, label)


def build(name, label, accent):
    frames = [draw_app_icon(s) if label is None else draw_icon(s, label, accent)
              for s in SIZES]
    path = os.path.join(OUT, name)
    frames[-1].save(path, format="ICO",
                    sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    # 설치 마법사용 미리보기(선택) — 확인이 쉽도록 PNG도 남긴다
    frames[-1].save(path.replace(".ico", "_256.png"), format="PNG")
    print("wrote", path)


def main():
    os.makedirs(OUT, exist_ok=True)
    # Retain internal resource paths for existing packaging integrations.
    build("spdf.ico", None, ACCENT)         # Leaflet 앱 실행 파일
    build("spdf_doc.ico", "PDF", DOC_ACCENT)
    build("leaflet_ai.ico", "AI", AI_ACCENT)
    build("leaflet_eps.ico", "EPS", EPS_ACCENT)


if __name__ == "__main__":
    main()
