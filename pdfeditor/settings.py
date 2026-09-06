"""사용자 설정 — ~/.spdf.json (최근 파일/즐겨찾기 등)."""

import json
import math
import tempfile
import os
import time

PATH = os.path.expanduser("~/.spdf.json")
_OLD_PATH = os.path.expanduser("~/.pdfeditor.json")  # 개명 전 설정 파일
MAX_RECENT = 10
DEFAULT_THUMBNAIL_WIDTH = 160
MIN_THUMBNAIL_WIDTH = 96
MAX_THUMBNAIL_WIDTH = 480
AUTOMATIC_UPDATE_INTERVAL_SECONDS = 24 * 60 * 60
UI_LANGUAGES = ("en", "ko")
DEFAULT_UI_LANGUAGE = "en"
SIDEBAR_MODES = ("none", "thumbnails", "bookmarks")
DEFAULT_SIDEBAR_MODE = "thumbnails"
PRINT_DUPLEX_MODES = ("simplex", "long", "short")
DEFAULT_PRINT_DUPLEX_MODE = "simplex"
RENDER_BACKENDS = ("auto", "gpu", "cpu")
DEFAULT_RENDER_BACKEND = "auto"


def _load():
    # sPDF로 개명하면서 설정 파일도 이사 — 예전 파일이 있으면 한 번만 옮긴다.
    if not os.path.exists(PATH) and os.path.exists(_OLD_PATH):
        try:
            os.rename(_OLD_PATH, PATH)
        except OSError:
            pass
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # 파일이 없거나 깨졌으면 새로 시작 — 설정 파일 때문에 앱이 못 뜨면 안 된다.
        return {}


def _save(data):
    fd, temporary = tempfile.mkstemp(
        prefix=".spdf-settings-", suffix=".tmp",
        dir=os.path.dirname(os.path.abspath(PATH)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, PATH)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def recent_files():
    return list(_load().get("recent", []))


def push_recent(path):
    path = os.path.abspath(path)
    d = _load()
    rest = [p for p in d.get("recent", [])
            if os.path.normcase(p) != os.path.normcase(path)]
    d["recent"] = [path] + rest[:MAX_RECENT - 1]
    _save(d)


def remove_recent(path):
    d = _load()
    d["recent"] = [p for p in d.get("recent", [])
                   if os.path.normcase(p) != os.path.normcase(path)]
    _save(d)


def clear_recent():
    d = _load()
    d["recent"] = []
    _save(d)


# --- 사용자 인터페이스 언어 -------------------------------------------

def ui_language():
    data = _load()
    value = data.get("ui_language")
    if value is None:
        value = _installer_ui_language()
    value = str(value or DEFAULT_UI_LANGUAGE).lower()
    return value if value in UI_LANGUAGES else DEFAULT_UI_LANGUAGE


def _installer_ui_language():
    """Return the language selected in the Windows installer, if available."""
    if os.name != "nt":
        return None
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\sPDF") as key:
                    value, _kind = winreg.QueryValueEx(key, "UILanguage")
                    return str(value).lower()
            except OSError:
                continue
    except (ImportError, OSError):
        pass
    return None


def set_ui_language(language):
    normalized = str(language).lower()
    if normalized not in UI_LANGUAGES:
        return False
    d = _load()
    d["ui_language"] = normalized
    _save(d)
    return True


def startup_workspace():
    mode = _load().get("startup_workspace", "reader")
    return mode if mode in ("reader", "editor") else "reader"


def set_startup_workspace(mode):
    if mode not in ("reader", "editor"):
        return False
    data = _load()
    data["startup_workspace"] = mode
    _save(data)
    return True


def render_backend():
    mode = str(_load().get("render_backend", DEFAULT_RENDER_BACKEND)).lower()
    return mode if mode in RENDER_BACKENDS else DEFAULT_RENDER_BACKEND


def reader_resident():
    return bool(_load().get("reader_resident", False))


def set_reader_resident(enabled):
    data = _load()
    data["reader_resident"] = bool(enabled)
    _save(data)
    return True


def set_render_backend(mode):
    normalized = str(mode).lower()
    if normalized not in RENDER_BACKENDS:
        return False
    data = _load()
    data["render_backend"] = normalized
    _save(data)
    return True


def render_diagnostics():
    return bool(_load().get("render_diagnostics", False))


DISK_CACHE_SIZES = (0, 50, 100, 250, 500)


def disk_cache_mb():
    value = _load().get("disk_cache_mb", 100)
    return value if type(value) is int and value in DISK_CACHE_SIZES else 100


def set_disk_cache_mb(value):
    if type(value) is not int or value not in DISK_CACHE_SIZES:
        raise ValueError("Unsupported disk cache size")
    data = _load()
    data["disk_cache_mb"] = value
    _save(data)


def set_render_diagnostics(enabled):
    data = _load()
    data["render_diagnostics"] = bool(enabled)
    _save(data)
    return True


# --- 문서 보기 ----------------------------------------------------------

def thumbnail_width():
    try:
        width = int(_load().get("thumbnail_width", DEFAULT_THUMBNAIL_WIDTH))
    except (TypeError, ValueError):
        width = DEFAULT_THUMBNAIL_WIDTH
    return max(MIN_THUMBNAIL_WIDTH, min(width, MAX_THUMBNAIL_WIDTH))


def set_thumbnail_width(width):
    width = max(MIN_THUMBNAIL_WIDTH,
                min(int(width), MAX_THUMBNAIL_WIDTH))
    d = _load()
    d["thumbnail_width"] = width
    _save(d)


def sidebar_mode():
    mode = str(_load().get("sidebar_mode", DEFAULT_SIDEBAR_MODE)).lower()
    return mode if mode in SIDEBAR_MODES else DEFAULT_SIDEBAR_MODE


def set_sidebar_mode(mode):
    normalized = str(mode).lower()
    if normalized not in SIDEBAR_MODES:
        return False
    d = _load()
    d["sidebar_mode"] = normalized
    _save(d)
    return True


# --- 인쇄 --------------------------------------------------------------

def print_duplex_mode():
    mode = str(_load().get(
        "print_duplex_mode", DEFAULT_PRINT_DUPLEX_MODE)).lower()
    return mode if mode in PRINT_DUPLEX_MODES else DEFAULT_PRINT_DUPLEX_MODE


def set_print_duplex_mode(mode):
    normalized = str(mode).lower()
    if normalized not in PRINT_DUPLEX_MODES:
        return False
    data = _load()
    data["print_duplex_mode"] = normalized
    _save(data)
    return True


def reading_position(path):
    positions = _load().get("reading_positions", {})
    if not isinstance(positions, dict):
        return None
    value = positions.get(os.path.normcase(os.path.abspath(path)), {})
    return _clean_reading_position(value)


def _clean_reading_position(value):
    try:
        state = {"page": max(0, int(value["page"])),
                 "zoom": float(value["zoom"]),
                 "horizontal": float(value.get("horizontal", 0)),
                 "vertical": float(value.get("vertical", 0)),
                 "two_page": bool(value.get("two_page", False))}
        if not all(math.isfinite(state[k]) for k in
                   ("zoom", "horizontal", "vertical")):
            return None
        state["zoom"] = max(0.1, min(8.0, state["zoom"]))
        for key in ("horizontal", "vertical"):
            state[key] = max(0.0, min(1.0, state[key]))
        return state
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def set_reading_position(path, state):
    state = _clean_reading_position(state)
    if state is None:
        return
    data = _load()
    positions = data.get("reading_positions", {})
    if not isinstance(positions, dict):
        positions = {}
    key = os.path.normcase(os.path.abspath(path))
    positions.pop(key, None)
    positions[key] = state
    data["reading_positions"] = dict(list(positions.items())[-100:])
    _save(data)


# --- 즐겨찾기 ----------------------------------------------------------

def favorites():
    return list(_load().get("favorites", []))


def is_favorite(path):
    path = os.path.normcase(os.path.abspath(path))
    return any(os.path.normcase(p) == path for p in favorites())


def add_favorite(path):
    path = os.path.abspath(path)
    d = _load()
    favs = [p for p in d.get("favorites", [])
            if os.path.normcase(p) != os.path.normcase(path)]
    d["favorites"] = favs + [path]
    _save(d)


def remove_favorite(path):
    d = _load()
    d["favorites"] = [p for p in d.get("favorites", [])
                      if os.path.normcase(p) != os.path.normcase(path)]
    _save(d)


# --- OCR 엔진 선택 ------------------------------------------------------
# "rapidocr": 기본(가벼운 CPU, 한글+영문). "vl": PaddleOCR-VL(고품질 AI,
# 모델 수 GB·GPU 권장). vl은 모델이 실제로 설치돼 있을 때만 유효하다.

OCR_ENGINES = ("rapidocr", "vl")


def ocr_engine():
    e = _load().get("ocr_engine", "rapidocr")
    return e if e in OCR_ENGINES else "rapidocr"


def set_ocr_engine(engine):
    if engine not in OCR_ENGINES:
        return
    d = _load()
    d["ocr_engine"] = engine
    _save(d)


# --- 자동 업데이트 확인 ------------------------------------------------

def automatic_update_check_due(now=None):
    """마지막 자동 확인으로부터 24시간이 지났는지 반환한다."""
    current = time.time() if now is None else float(now)
    try:
        last = float(_load().get("last_automatic_update_check", 0))
    except (TypeError, ValueError):
        return True
    # 시스템 시간이 과거로 크게 보정된 경우에도 확인이 영구히 막히지 않게 한다.
    return last <= 0 or current < last or \
        current - last >= AUTOMATIC_UPDATE_INTERVAL_SECONDS


def mark_automatic_update_check(now=None):
    """자동 업데이트 확인을 시작한 시각을 기록한다."""
    current = time.time() if now is None else float(now)
    d = _load()
    d["last_automatic_update_check"] = current
    _save(d)
