# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — 실행 파일 두 개(원폴더 빌드).

  dist\\Leaflet\\Leaflet.exe          GUI (PyQt5, onnxruntime 미포함)
  dist\\Leaflet\\ocr\\leaflet-ocr.exe  OCR 워커 (onnxruntime, PyQt5 미포함)

왜 둘로 나누나: 같은 프로세스/같은 폴더에서 Qt DLL과 onnxruntime가
공존하면 onnxruntime DLL 초기화가 깨진다(dev·frozen 공통). GUI가 OCR을
이 별도 실행 파일로 shell-out 해서 완전히 격리한다. 워커를 Leaflet\\ocr\\
하위 폴더에 두어 _internal(DLL 폴더)이 서로 겹치지 않게 한다.

OCR 모델(korean_PP-OCRv5 등)은 번들 안 함 — 첫 OCR 때 사용자 폴더로
자동 다운로드(설치본을 가볍게).
"""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

# PyInstaller는 spec 파일 폴더를 자동으로 import 경로에 넣지 않는다.
spec_root = Path(SPEC).resolve().parent
sys.path.insert(0, str(spec_root))

from build_version_info import write_version_info_files
from build_legal import write_legal_bundle
from pdfeditor.meta import APP_VERSION


# 작업 관리자가 GUI와 OCR 자식 프로세스를 의미 있는 제품명으로 표시하도록
# 두 EXE에 같은 제품/버전 정보와 역할별 파일 설명을 넣는다.
gui_version_info, ocr_version_info = write_version_info_files(
    spec_root / "build" / "version-info", APP_VERSION)
legal_bundle = write_legal_bundle(spec_root / "build" / "legal")
legal_datas = [("LICENSE", "."), ("LICENSES.md", "."), ("SOURCE_CODE.md", "."),
               ("licenses", "licenses"), (str(legal_bundle), "third-party")]
d2d_renderer = spec_root / "native" / "bin" / "spdf_d2d_renderer.dll"
if not d2d_renderer.is_file():
    raise FileNotFoundError(
        "Direct2D renderer is missing; run native\\build_d2d_renderer.bat first")

# --- OCR 워커: onnxruntime/rapidocr/cv2, PyQt5 제외 ---
ocr_datas, ocr_bins, ocr_hidden = [], [], []
for pkg in ("rapidocr", "onnxruntime"):
    d, b, h = collect_all(pkg)
    ocr_datas += d
    ocr_bins += b
    ocr_hidden += h
ocr_hidden += ["cv2", "numpy", "fitz", "pdfeditor.ocr_subprocess"]

# 실제 쓰는 OCR 모델(det + cls + 한국어 rec)만 번들에 남긴다. collect_all이
# rapidocr/models의 .onnx를 전부 쓸어담는데, 기본 중국어 rec 모델
# (PP-OCRv6_rec_small, ~20MB)은 한국어 rec으로 덮어쓰므로 로드조차 되지
# 않는다 — 순수 낭비라 제외. 한국어 rec 모델이 한글+영문/숫자를 함께
# 인식하므로(영수증·영어 논문 테스트로 확인) 영어 OCR에는 영향 없다.
# 새 언어 rec을 추가하려면 여기 화이트리스트에도 그 모델명을 넣을 것.
_KEEP_MODELS = ("PP-OCRv6_det_small.onnx",
                "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                "korean_PP-OCRv5_rec_mobile.onnx")


def _keep(entry):
    src = entry[0].replace("\\", "/")
    if "/rapidocr/models/" in src and src.endswith(".onnx"):
        return any(src.endswith(name) for name in _KEEP_MODELS)
    return True


ocr_datas = [e for e in ocr_datas if _keep(e)]
ocr_bins = [e for e in ocr_bins if _keep(e)]

a_ocr = Analysis(
    ["ocr_worker_main.py"],
    binaries=ocr_bins,
    datas=ocr_datas + legal_datas,
    hiddenimports=ocr_hidden,
    excludes=["PyQt5", "tkinter", "matplotlib", "onnx", "tensorrt", "paddle"],
)
pyz_ocr = PYZ(a_ocr.pure)
exe_ocr = EXE(
    pyz_ocr, a_ocr.scripts, [],
    exclude_binaries=True,
    name="leaflet-ocr",
    console=True,   # 콘솔 워커(창은 CREATE_NO_WINDOW로 숨김)
    icon="assets/spdf.ico",
    version=ocr_version_info,
)

# --- GUI: PyQt5/PyMuPDF, onnxruntime류 제외(워커가 담당) ---
a_gui = Analysis(
    ["run.py"],
    binaries=[(str(d2d_renderer), "native")],
    datas=[("assets/spdf.ico", "assets"),
           ("assets/spdf_doc.ico", "assets")] + legal_datas,
    hiddenimports=["pdfeditor", "fitz", "pdfeditor.gpu_scene_worker"],
    excludes=["rapidocr", "onnxruntime", "cv2", "onnx", "tensorrt", "paddle",
              "tkinter", "matplotlib"],
)
pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(
    pyz_gui, a_gui.scripts, [],
    exclude_binaries=True,
    name="Leaflet",
    console=False,
    icon="assets/spdf.ico",
    version=gui_version_info,
)

# 각각 별도 dist 폴더로 수집(DLL 격리). 설치 시 Leaflet-ocr\* 를 {app}\ocr 로,
# 로컬 테스트는 Leaflet-ocr\ 를 Leaflet\ocr\ 로 복사해 확인한다.
coll_gui = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, name="Leaflet")
coll_ocr = COLLECT(exe_ocr, a_ocr.binaries, a_ocr.datas, name="Leaflet-ocr")
