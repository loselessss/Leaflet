"""리소스/데이터 경로 — 개발 실행과 PyInstaller 프로즌 실행을 함께 지원.

프로즌 EXE에서는 파일 배치가 달라진다:
- 번들 리소스(아이콘 등)는 sys._MEIPASS 임시 폴더에 풀린다 → resource()
- 쓰기가 필요한 것(OCR 모델 다운로드, 설정)은 임시 폴더가 아니라 사용자
  폴더여야 재실행 간 유지된다 → user_data_dir()
"""

import os
import sys


def is_frozen():
    return getattr(sys, "frozen", False)


def is_packaged():
    """Detect MSIX identity without registry or environment heuristics."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        length = ctypes.c_uint32(0)
        query = ctypes.windll.kernel32.GetCurrentPackageFullName
        query.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p]
        query.restype = ctypes.c_long
        return query(ctypes.byref(length), None) == 122
    except (OSError, AttributeError):
        return False


def resource(*parts):
    """번들에 포함된 읽기 전용 리소스 경로(개발: 프로젝트 루트 기준)."""
    if is_frozen():
        base = sys._MEIPASS  # PyInstaller가 푸는 임시 폴더
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def user_data_dir():
    """쓰기 가능한 사용자 데이터 폴더 (%LOCALAPPDATA%\\sPDF). 없으면 만든다."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "sPDF")
    os.makedirs(d, exist_ok=True)
    return d


def app_icon():
    return resource("assets", "spdf.ico")


def ocr_command():
    """OCR 자식 프로세스를 띄우는 명령 리스트.

    프로즌이면 별도 실행 파일 ocr\\spdf-ocr.exe (PyQt5 없이 빌드해 Qt DLL
    충돌을 피한 것). 개발이면 python -m 으로 모듈 실행.
    """
    if is_frozen():
        exe_dir = os.path.dirname(sys.executable)
        return [os.path.join(exe_dir, "ocr", "spdf-ocr.exe")]
    return [sys.executable, "-m", "pdfeditor.ocr_subprocess"]


def gpu_scene_worker_command():
    """Return the isolated GPU scene worker command for dev or frozen mode."""
    if is_frozen():
        return [sys.executable, "--gpu-scene-worker"]
    return [sys.executable, "-m", "pdfeditor.gpu_scene_worker"]
