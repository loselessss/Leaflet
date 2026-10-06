"""OCR 자식 프로세스 — Qt 없이 onnxruntime만 로드해 실행한다.

왜 별도 프로세스인가: PyQt5가 먼저 로드된 프로세스에서 onnxruntime를
import하면 DLL 초기화가 실패한다(Windows, "DLL 초기화 루틴을 실행할 수
없습니다"). 스레드로는 못 피한다 — 같은 프로세스이기 때문. 그래서 OCR은
이 스크립트를 자식 프로세스로 띄워 처리하고, 부모(Qt 앱)는 stdout으로
결과 JSON만 받는다.

프로토콜(부모가 파싱):
    stdin(JSON 한 줄): {"path","password","pages":[...],"zoom"}
    stdout(줄 단위 JSON):
        {"type":"progress","done":k,"total":n}
        {"type":"page","page":p,"items":[[x0,y0,x1,y1,text],...]}
        {"type":"error","message":...}
        {"type":"done"}

사용법:
    python -m pdfeditor.ocr_subprocess    # stdin으로 작업 전달
"""

import json
import re
import sys


def _force_utf8_io():
    """stdin/stdout을 UTF-8로 고정한다.

    PYTHONIOENCODING 환경변수로는 부족하다 — PyInstaller로 얼린 EXE에서는
    무시되고 콘솔 기본 인코딩(한국어 Windows면 cp949)으로 출력해서, 부모가
    UTF-8로 읽다 UnicodeDecodeError로 죽는다(한글 OCR 결과가 통째로 유실).
    파일 경로에 한글이 있으면 stdin도 같은 이유로 깨진다.
    """
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # 파이프가 아닌 경우 등 — 무시


# 렌더 목표: 긴 변 기준 픽셀 수. A4(842pt)면 약 6배율(430dpi 상당)이 된다.
# 고정 3배율로는 저해상도 스캔(예: 115dpi 영수증)의 작은 글씨가 깨졌다 —
# 실측으로 이 값에서 인식이 눈에 띄게 좋아지고 처리 시간은 거의 같았다.
# 상한을 두는 이유: 스캐너가 만드는 '페이지=픽셀' PDF(수천 pt)는 배율을
# 낮춰야 렌더 버퍼가 수백 MB로 터지지 않는다. 페이지당 순간 사용량은
# 긴 변 5000px 기준 약 50MB이고, 자식 프로세스가 페이지마다 해제한다.
# 5100인 이유: A4(842pt)가 상한 6.0배에 정확히 걸리게 — 5.9배 근처에서
# '일시불' 같은 작은 글씨가 왔다갔다 하는 걸 실측으로 확인했다.
TARGET_LONG_PX = 5100.0
ZOOM_MIN, ZOOM_MAX = 1.0, 6.0

# VL은 프로세서가 어차피 약 1.6M 픽셀(2048*28*28)로 줄여서 보므로 고해상도
# 렌더가 낭비다 — 긴 변 2000px이면 축소 후에도 여유가 있다.
VL_TARGET_LONG_PX = 2000.0

# RapidOCR의 검출기는 큰 입력을 내부에서 다시 줄인다. 5100px 페이지를 한 번에
# 넣으면 저해상도 작은 글씨와 2단 논문의 글자가 너무 작아지므로, 세로 구간과
# 감지된 단을 겹쳐 잘라 인식한다. 겹침은 경계에 걸린 줄을 온전히 잡기 위함.
OCR_TILE_SIZE = 2200
OCR_TILE_OVERLAP = 200
OCR_TILE_TRIGGER = 3000


def _page_zoom(rect, target=TARGET_LONG_PX):
    long_pt = max(rect.width, rect.height)
    if long_pt <= 0:
        return 3.0
    return max(ZOOM_MIN, min(ZOOM_MAX, target / long_pt))


def _emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _build_engine(engine="rapidocr"):
    """OCR 엔진 생성 — recognize(img_rgb) -> [[x0,y0,x1,y1,text],...] (픽셀).

    engine="vl"이면 PaddleOCR-VL(고품질 AI). 모델이 사용자 폴더에 설치돼
    있어야 한다(vl.py). 미설치면 명확한 예외를 던져 호출부가 사용자에게
    안내하게 한다 — 조용히 RapidOCR로 떨어지지 않는다(품질 기대가 다르므로).

    프로세스 공존: VL 경로는 torch/transformers만, rapidocr 경로는
    onnxruntime만 import한다 — 한 작업에서 둘이 섞이지 않으므로 같은 워커
    스크립트를 그대로 쓴다.
    """
    if engine == "vl":
        return _VLEngine()
    return _RapidOCREngine()


# --- PaddleOCR-VL (transformers) ----------------------------------------
# "Spotting:" 태스크가 줄 단위 텍스트+위치를 함께 준다. 파싱은 PaddleX의
# post_process_for_spotting과 동일하게 두 형식을 지원한다:
#   ① <|TEXT_START|>글자<|TEXT_END|> ... <|LOC_BEGIN|><|LOC_x|>*8<|LOC_END|>
#   ② 글자<|LOC_x|>*8 줄바꿈 반복 (마커 없음 — 실측으로 이 모델이 내는 형식)
# LOC 값은 입력 이미지 기준 0~1000 정규화 좌표(4점 폴리곤, x,y 교대).

_SPOT_TEXT_RE = re.compile(r"<\|TEXT_START\|>(.*?)<\|TEXT_END\|>", re.S)
_SPOT_BLOCK_RE = re.compile(r"<\|LOC_BEGIN\|>(.*?)<\|LOC_END\|>", re.S)
_SPOT_LOC_RE = re.compile(r"<\|LOC_(\d+)\|>")


def _rect_from_locs(vals, w, h):
    """LOC 정수 8개(0~1000 정규화 4점 폴리곤) → 픽셀 [x0,y0,x1,y1]."""
    xs = [vals[j] / 1000.0 * w for j in range(0, 8, 2)]
    ys = [vals[j] / 1000.0 * h for j in range(1, 8, 2)]
    return [min(xs), min(ys), max(xs), max(ys)]


def _parse_spotting(s, w, h):
    items = []
    texts = _SPOT_TEXT_RE.findall(s)
    blocks = _SPOT_BLOCK_RE.findall(s)
    for txt, blk in zip(texts, blocks):
        txt = txt.strip()
        locs = _SPOT_LOC_RE.findall(blk)
        if not txt or len(locs) < 8:
            continue
        items.append(_rect_from_locs([int(v) for v in locs[:8]], w, h)
                     + [txt])
    if items:
        return items
    # 폴백(PaddleX와 동일): TEXT 마커 없이 "글자 <LOC>*8" 이 이어지는 형식
    matches = list(_SPOT_LOC_RE.finditer(s))
    last_end, i = 0, 0
    while i + 7 < len(matches):
        group = matches[i:i + 8]
        txt = s[last_end:group[0].start()].strip()
        if txt:
            vals = [int(m.group(1)) for m in group]
            items.append(_rect_from_locs(vals, w, h) + [txt])
        last_end = group[-1].end()
        i += 8
    return items


class _VLEngine:
    """PaddleOCR-VL을 transformers로 로드해 페이지를 인식한다.

    bf16 + CUDA 기준 모델 약 2GB VRAM. CPU면 fp32로 폴백(매우 느림 —
    UI가 켜기 전에 사양 경고를 한다, app.show_ocr_engine_dialog).
    """

    _PROMPT = "Spotting:"
    # 줄당 대략 (글자 토큰 + 특수 토큰 12개). 빽빽한 페이지도 수천 토큰이면
    # 충분하고, 상한에 닿으면 그 줄부터 잘릴 뿐 앞의 결과는 유효하다.
    _MAX_NEW_TOKENS = 8192
    # 모델 카드 권장: spotting 입력 상한 2048*28*28 픽셀, 작은 이미지(긴 변
    # <1500px)는 2배 확대. 좌표는 0~1000 상대값이라 확대해도 복원식이 같다.
    _MAX_PIXELS = 2048 * 28 * 28
    _UPSCALE_BELOW_PX = 1500

    def __init__(self):
        from pdfeditor import vl
        if not vl.vl_installed():
            raise RuntimeError(
                "VL을 쓸 수 없습니다 — 빠진 것: %s" % vl.install_hint())
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        self._torch = torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.bfloat16 if device == "cuda" else torch.float32
        model_dir = vl.models_dir()
        # trust_remote_code를 쓰지 않는다 — repo에 든 커스텀 모델링 코드는
        # 구버전 transformers용이라 5.x 내장 구현과 충돌한다('text_config'
        # AttributeError). transformers>=5.0은 PaddleOCR-VL을 내장 지원한다.
        self._model = AutoModelForImageTextToText.from_pretrained(
            model_dir, dtype=dtype).to(device).eval()
        self._processor = AutoProcessor.from_pretrained(model_dir)

    def recognize(self, img_rgb):
        from PIL import Image
        image = Image.fromarray(img_rgb)
        w, h = image.size
        if max(w, h) < self._UPSCALE_BELOW_PX:
            image = image.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
        proc = self._processor
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": self._PROMPT},
        ]}]
        # 최소 픽셀: 내장 프로세서는 size.shortest_edge, 구식(remote code)
        # 프로세서는 min_pixels — 둘 다 지원한다.
        ip = proc.image_processor
        min_px = getattr(ip, "min_pixels", None)
        if min_px is None:
            min_px = ip.size.shortest_edge
        inputs = proc.apply_chat_template(
            messages, add_generation_prompt=True, tokenize=True,
            return_dict=True, return_tensors="pt",
            images_kwargs={"size": {
                "shortest_edge": min_px,
                "longest_edge": self._MAX_PIXELS}},
        ).to(self._model.device)
        with self._torch.no_grad():
            # use_cache=True 필수 — 이 모델의 generation_config는
            # use_cache=false로 배포돼 있어 그대로 두면 토큰마다 전체
            # 재계산이 일어난다(실측 1.2 tok/s, 페이지당 100초+).
            out = self._model.generate(
                **inputs, max_new_tokens=self._MAX_NEW_TOKENS,
                do_sample=False, use_cache=True)
        # LOC/TEXT 마커가 특수 토큰이라 skip_special_tokens면 좌표가 통째로
        # 사라진다 — 반드시 남긴 채 디코드해서 직접 파싱한다.
        text = proc.decode(out[0][inputs["input_ids"].shape[-1]:],
                           skip_special_tokens=False)
        return _parse_spotting(text, w, h)


class _RapidOCREngine:
    """RapidOCR(onnxruntime) 엔진을 공통 인터페이스로 감싼다."""

    def __init__(self):
        self._ocr = _build_rapidocr()

    def recognize(self, img_rgb):
        result = self._ocr(img_rgb)
        out = []
        if result is None:
            return out
        if hasattr(result, "boxes") and result.boxes is not None:
            pairs = zip(result.boxes, result.txts or [])
        else:
            res = result[0] if isinstance(result, tuple) else result
            if not res:
                return out
            pairs = ((item[0], item[1]) for item in res)
        for box, text in pairs:
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            out.append([min(xs), min(ys), max(xs), max(ys), str(text)])
        return out


def _build_rapidocr():
    import os

    from rapidocr import RapidOCR
    # 프로즌 EXE는 모델을 사용자 폴더에 받아야 재실행 간 유지된다
    # (부모가 RAPIDOCR_MODEL_DIR로 넘겨준다). RapidOCR은 전역 설정에서
    # 모델 저장 위치를 읽으므로, 지정돼 있으면 그리로 돌린다.
    model_dir = os.environ.get("RAPIDOCR_MODEL_DIR")
    extra = {}
    if model_dir:
        os.makedirs(model_dir, exist_ok=True)
        extra["Global.model_root_dir"] = model_dir
    try:
        from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
        params = {
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.lang_type": LangRec.KOREAN,
            "Rec.model_type": ModelType.MOBILE,
        }
        params.update(extra)
        return RapidOCR(params=params)
    except Exception:
        try:
            return RapidOCR(params=extra) if extra else RapidOCR()
        except Exception:
            return RapidOCR()


def _preprocess(img_rgb):
    """OCR 전처리 — 기울기·저대비 보정 + 언샤프 마스크.

    실측(영수증 6배 렌더): 샤픈이 인식률을 21개 토큰 중 20→21로 올렸고,
    deskew는 똑바른 문서엔 무해(0도면 원본 그대로), 기울어진 스캔에서 효과.
    cv2가 없으면 원본을 그대로 돌려준다(설치 선택 사항).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return img_rgb

    img = img_rgb
    # --- deskew: 전경 픽셀의 최소 외접 사각형 각도로 회전 ---
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    thr = cv2.threshold(gray, 0, 255,
                        cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    if len(coords) >= 100:
        ang = cv2.minAreaRect(coords)[-1]
        if ang < -45:
            ang = 90 + ang
        elif ang > 45:
            ang = ang - 90
        # 아주 작은 각도는 보정 자체가 노이즈 — 0.3도 이상만, 5도 넘는 큰
        # 각도는 오탐(표/그림 때문)일 수 있어 건드리지 않는다.
        if 0.3 <= abs(ang) <= 5.0:
            h, w = img.shape[:2]
            M = cv2.getRotationMatrix2D((w // 2, h // 2), ang, 1.0)
            img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                                 borderMode=cv2.BORDER_REPLICATE)

    # --- low contrast: 빛바랜 스캔만 국소 명암 보정 ---
    # 깨끗한 디지털 PDF까지 CLAHE를 거치면 획 가장자리가 거칠어질 수 있어,
    # 밝기 범위가 좁은 경우에만 L 채널을 완만하게 늘린다.
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    p02, p98 = np.percentile(gray, (2, 98))
    clean_extremes = int(gray.min()) < 40 and int(gray.max()) > 245
    if p98 - p02 < 110 and not clean_extremes and gray.std() > 3:
        lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
        lch, ach, bch = cv2.split(lab)
        lch = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8)).apply(lch)
        img = cv2.cvtColor(cv2.merge((lch, ach, bch)), cv2.COLOR_LAB2RGB)

    # --- sharpen: 언샤프 마스크 ---
    blur = cv2.GaussianBlur(img, (0, 0), 3)
    img = cv2.addWeighted(img, 1.5, blur, -0.5, 0)
    return img


def _otsu_threshold(gray):
    """OpenCV 없이도 단 판별 테스트가 가능하도록 작은 Otsu 구현을 둔다."""
    import numpy as np
    values = np.asarray(gray, dtype=np.uint8)
    hist = np.bincount(values.ravel(), minlength=256).astype(np.float64)
    total = hist.sum()
    if total == 0:
        return 0
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    sum_bg = np.cumsum(hist * np.arange(256))
    sum_total = sum_bg[-1]
    valid = (weight_bg > 0) & (weight_fg > 0)
    score = np.zeros(256, dtype=np.float64)
    mean_bg = np.zeros(256, dtype=np.float64)
    mean_fg = np.zeros(256, dtype=np.float64)
    mean_bg[valid] = sum_bg[valid] / weight_bg[valid]
    mean_fg[valid] = (sum_total - sum_bg[valid]) / weight_fg[valid]
    score[valid] = weight_bg[valid] * weight_fg[valid] * \
        (mean_bg[valid] - mean_fg[valid]) ** 2
    return int(np.argmax(score))


def _find_column_gutter(img_rgb, min_width=1600):
    """가운데의 지속적인 세로 공백을 찾아 2단 분할 x 좌표를 반환한다."""
    import numpy as np
    h, w = img_rgb.shape[:2]
    if w < min_width or h < 100:
        return None
    step = max(1, h // 1200)
    sample = img_rgb[::step]
    if sample.ndim == 3:
        gray = sample[..., :3].mean(axis=2).astype(np.uint8)
    else:
        gray = sample.astype(np.uint8)
    if int(gray.min()) == int(gray.max()):
        return None
    threshold = _otsu_threshold(gray)
    ink = (gray <= threshold).mean(axis=0)
    smooth_n = max(7, w // 100)
    kernel = np.ones(smooth_n, dtype=np.float64) / smooth_n
    smooth = np.convolve(ink, kernel, mode="same")

    c0, c1 = int(w * 0.35), int(w * 0.65)
    sides = np.concatenate((smooth[int(w * 0.12):c0],
                            smooth[c1:int(w * 0.88)]))
    baseline = float(np.median(sides)) if len(sides) else 0.0
    if baseline < 0.002:
        return None
    split = c0 + int(np.argmin(smooth[c0:c1]))
    valley = float(smooth[split])
    if valley > min(0.03, baseline * 0.45):
        return None
    return split


def _tile_starts(length, size=OCR_TILE_SIZE, overlap=OCR_TILE_OVERLAP):
    """끝 조각이 지나치게 작지 않도록 마지막 타일을 끝에 맞춘다."""
    import math
    if length <= size:
        return [0]
    count = max(2, int(math.ceil((length - overlap) /
                                 max(1, size - overlap))))
    last = float(length - size)
    return [int(round(last * i / (count - 1))) for i in range(count)]


def _box_iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ab = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(1e-9, aa + ab - inter)


def _merge_ocr_items(items):
    """겹친 타일에서 같은 줄을 두 번 잡은 결과를 하나로 합친다."""
    merged = []
    for item in items:
        text = " ".join(str(item[4]).split())
        duplicate = None
        for i, old in enumerate(merged):
            old_text = " ".join(str(old[4]).split())
            if text == old_text and _box_iou(item, old) >= 0.25:
                duplicate = i
                break
        if duplicate is None:
            merged.append(item)
            continue
        old = merged[duplicate]
        old_area = max(0.0, old[2] - old[0]) * max(0.0, old[3] - old[1])
        new_area = max(0.0, item[2] - item[0]) * max(0.0, item[3] - item[1])
        if new_area > old_area:
            merged[duplicate] = item
    return merged


def _recognize_tiled(engine, img_rgb, tile_size=OCR_TILE_SIZE,
                     overlap=OCR_TILE_OVERLAP, trigger=OCR_TILE_TRIGGER):
    """긴 페이지와 2단 문서를 확대 효과가 있는 겹친 조각으로 인식한다."""
    h, w = img_rgb.shape[:2]
    gutter = _find_column_gutter(img_rgb)
    if gutter is None:
        x_ranges = [(0, w)]
    else:
        pad = min(overlap, max(20, w // 20))
        x_ranges = [(0, min(w, gutter + pad)),
                    (max(0, gutter - pad), w)]
    y_starts = _tile_starts(h, tile_size, overlap) if h > trigger else [0]
    if gutter is None and len(y_starts) == 1:
        return engine.recognize(img_rgb)

    found = []
    for x0, x1 in x_ranges:       # 왼쪽 단 전체 뒤 오른쪽 단 — 읽기 순서 유지
        for y0 in y_starts:
            y1 = min(h, y0 + tile_size)
            tile = img_rgb[y0:y1, x0:x1]
            for item in engine.recognize(tile):
                if len(item) < 5 or not str(item[4]).strip():
                    continue
                found.append([
                    max(0.0, float(item[0]) + x0),
                    max(0.0, float(item[1]) + y0),
                    min(float(w), float(item[2]) + x0),
                    min(float(h), float(item[3]) + y0),
                    str(item[4]),
                ])
    return _merge_ocr_items(found)


def _recognize(engine, img_rgb, zoom, tiled=False):
    """엔진 실행 후 픽셀 좌표를 PDF 좌표(pt)로 되돌린다."""
    raw = _recognize_tiled(engine, img_rgb) if tiled \
        else engine.recognize(img_rgb)
    return [[it[0] / zoom, it[1] / zoom, it[2] / zoom, it[3] / zoom, it[4]]
            for it in raw]


def main():
    _force_utf8_io()  # 반드시 첫 입출력 전에 (프로즌 EXE의 cp949 폴백 방지)

    try:
        job = json.loads(sys.stdin.readline())
    except Exception as e:
        _emit({"type": "error", "message": "잘못된 작업 입력: %s" % e})
        return 1

    path = job["path"]
    password = job.get("password")
    pages = job["pages"]
    fixed_zoom = job.get("zoom")  # 없으면 페이지별 자동 배율
    engine = job.get("engine", "rapidocr")

    try:
        import numpy as np
        import pymupdf as fitz
        ocr = _build_engine(engine)
    except Exception as e:
        _emit({"type": "error", "message": "OCR 초기화 실패: %s" % e})
        return 1

    try:
        doc = fitz.open(path)
        if doc.needs_pass:
            doc.authenticate(password or "")
        try:
            target = VL_TARGET_LONG_PX if engine == "vl" else TARGET_LONG_PX
            for i, pno in enumerate(pages):
                zoom = fixed_zoom or _page_zoom(doc[pno].rect, target)
                pix = doc[pno].get_pixmap(
                    matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8) \
                    .reshape(pix.height, pix.width, 3)
                if job.get("preprocess", True):
                    img = _preprocess(img)
                items = _recognize(
                    ocr, img, zoom, tiled=(engine == "rapidocr"))
                del pix, img
                _emit({"type": "page", "page": pno, "items": items})
                _emit({"type": "progress", "done": i + 1, "total": len(pages)})
        finally:
            doc.close()
        _emit({"type": "done"})
        return 0
    except Exception as e:
        _emit({"type": "error", "message": str(e)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
