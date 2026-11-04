# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — GUI·OCR와 독립 Rust 열람 작업 프로세스(원폴더 빌드).

  dist\\Leaflet\\Leaflet.exe          GUI (PyQt5, onnxruntime 미포함)
  dist\\Leaflet\\ocr\\leaflet-ocr.exe  OCR 워커 (onnxruntime, PyQt5 미포함)
  dist\\Leaflet\\_internal\\native\\leaflet-gpu-scene-worker.exe  GPU 장면 워커

왜 둘로 나누나: 같은 프로세스/같은 폴더에서 Qt DLL과 onnxruntime가
공존하면 onnxruntime DLL 초기화가 깨진다(dev·frozen 공통). GUI가 OCR을
이 별도 실행 파일로 shell-out 해서 완전히 격리한다. 워커를 Leaflet\\ocr\\
하위 폴더에 두어 _internal(DLL 폴더)이 서로 겹치지 않게 한다.

OCR 모델(korean_PP-OCRv5 등)은 번들 안 함 — 첫 OCR 때 사용자 폴더로
자동 다운로드(설치본을 가볍게).
"""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files

# PyInstaller는 spec 파일 폴더를 자동으로 import 경로에 넣지 않는다.
spec_root = Path(SPEC).resolve().parents[1]
sys.path.insert(0, str(spec_root))

from tools.build.build_version_info import write_version_info_files
from tools.build.build_legal import write_legal_bundle
from pdfeditor.meta import APP_VERSION
from tools.build.build_payload import trim_payload, native_worker_runtime_binaries, prefer_ocr_runtimes, runtime_ssl_datas


# 작업 관리자가 GUI와 OCR 자식 프로세스를 의미 있는 제품명으로 표시하도록
# 두 EXE에 같은 제품/버전 정보와 역할별 파일 설명을 넣는다.
build_root = Path(workpath).resolve().parent
gui_version_info, ocr_version_info = write_version_info_files(
    build_root / "version-info", APP_VERSION)
legal_bundle = write_legal_bundle(build_root / "legal")
legal_datas = [(str(spec_root / "LICENSE"), "."), (str(spec_root / "LICENSES.md"), "."), (str(spec_root / "SOURCE_CODE.md"), "."),
               (str(spec_root / "licenses"), "licenses"), (str(legal_bundle), "third-party")] + runtime_ssl_datas()
d2d_renderer = spec_root / "native" / "bin" / "spdf_d2d_renderer.dll"
if not d2d_renderer.is_file():
    raise FileNotFoundError(
        "Direct2D renderer is missing; run native\\build_d2d_renderer.bat first")
if not (spec_root / "pdfeditor" / "_path_packer.pyd").is_file():
    raise FileNotFoundError("Rust path packer is missing; run native/build_path_packer.py first")
mupdf_path_bridge = spec_root / "native" / "bin" / "leaflet_mupdf_path.dll"
if not mupdf_path_bridge.is_file():
    raise FileNotFoundError("MuPDF path bridge is missing; run native/build_mupdf_path.py first")
scene_worker = spec_root / "native" / "bin" / "leaflet-gpu-scene-worker.exe"
if not scene_worker.is_file():
    raise FileNotFoundError("Native GPU worker is missing; run native/build_path_packer.py first")
import pymupdf
from PyQt5.QtCore import QLibraryInfo
worker_runtimes = native_worker_runtime_binaries(
    scene_worker, mupdf_path_bridge, Path(pymupdf.__file__).parent / 'mupdfcpp64.dll',
    search_paths=[str(Path(pymupdf.__file__).parent), sys.base_prefix,
                  QLibraryInfo.location(QLibraryInfo.BinariesPath)])

# --- OCR 워커: onnxruntime/rapidocr/cv2, PyQt5 제외 ---
ocr_datas, ocr_bins, ocr_hidden = [], [], []
for pkg in ("rapidocr", "onnxruntime"):
    d, b, h = collect_all(pkg)
    ocr_datas += d
    ocr_bins += b
    ocr_hidden += h
ocr_hidden += ["cv2", "numpy", "pdfeditor.ocr_subprocess"]

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
    [str(spec_root / "ocr_worker_main.py")],
    pathex=[str(spec_root)],
    binaries=ocr_bins,
    datas=ocr_datas + legal_datas,
    hiddenimports=ocr_hidden,
    excludes=["PyQt5", "pymupdf", "fitz", "tkinter", "matplotlib", "onnx", "tensorrt", "paddle",
              "PIL.AvifImagePlugin"],
)
a_ocr.binaries, a_ocr.datas = trim_payload(a_ocr.binaries, a_ocr.datas, gui=False)
a_ocr.binaries = prefer_ocr_runtimes(a_ocr.binaries)
pyz_ocr = PYZ(a_ocr.pure)
exe_ocr = EXE(
    pyz_ocr, a_ocr.scripts, [],
    exclude_binaries=True,
    name="leaflet-ocr",
    console=True,   # 콘솔 워커(창은 CREATE_NO_WINDOW로 숨김)
    icon=str(spec_root / "assets/spdf.ico"),
    version=ocr_version_info,
)

# --- GUI: PyQt5/PyMuPDF, onnxruntime류 제외(워커가 담당) ---
a_gui = Analysis(
    [str(spec_root / "run.py")],
    pathex=[str(spec_root)],
    runtime_hooks=[str(spec_root / "tools/build/rth_headless_workers.py")],
    binaries=[(str(d2d_renderer), "native"), (str(mupdf_path_bridge), "native"),
              (str(scene_worker), "native")] + worker_runtimes,
    datas=[(str(spec_root / "assets/spdf.ico"), "assets"),
           (str(spec_root / "assets/spdf_doc.ico"), "assets"),
           (str(spec_root / "assets/leaflet_ai.ico"), "assets"),
           (str(spec_root / "assets/leaflet_eps.ico"), "assets")] + legal_datas
          + collect_data_files("pymupdf", include_py_files=True, includes=["layout/**"]),
    hiddenimports=["pdfeditor", "fitz", "pdfeditor.gpu_scene_worker", "pdfeditor.ocr_render_worker",
                   "pdfeditor.layout_worker", "pdfeditor._path_packer", "pymupdf.features",
                   "packaging.version", "yaml"],
    excludes=["pymupdf.layout", "rapidocr", "onnxruntime", "cv2", "onnx", "tensorrt", "paddle",
              "tkinter", "matplotlib", "PIL.AvifImagePlugin"],
)
a_gui.binaries, a_gui.datas = trim_payload(a_gui.binaries, a_gui.datas, gui=True)
# Headless layout jobs reuse ORT from the OCR directory. Both executables need
# its supported VC runtime; loading Qt's older copy first breaks ORT imports.
a_gui.binaries = prefer_ocr_runtimes(a_gui.binaries)
pyz_gui = PYZ(a_gui.pure)
exe_gui = EXE(
    pyz_gui, a_gui.scripts, [],
    exclude_binaries=True,
    name="Leaflet",
    console=False,
    icon=str(spec_root / "assets/spdf.ico"),
    version=gui_version_info,
)

# 각각 별도 dist 폴더로 수집(DLL 격리). 설치 시 Leaflet-ocr\* 를 {app}\ocr 로,
# 로컬 테스트는 Leaflet-ocr\ 를 Leaflet\ocr\ 로 복사해 확인한다.
coll_gui = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, name="Leaflet")
coll_ocr = COLLECT(exe_ocr, a_ocr.binaries, a_ocr.datas, name="Leaflet-ocr")
