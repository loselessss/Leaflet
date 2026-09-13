"""Windows에서 sPDF 프로세스를 하나의 데스크톱 앱으로 식별한다."""

import sys


APP_USER_MODEL_ID = "sPDF.Desktop"

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_TABBEDWINDOW = 4


def set_current_process_app_id():
    """작업 표시줄과 Windows 셸에 사용할 명시적 앱 ID를 설정한다.

    다른 운영체제와 오래된 Windows에서도 앱 시작을 막지 않도록 실패는
    조용히 무시한다. UI를 만들기 전에 호출해야 창마다 같은 ID가 적용된다.
    """
    from .paths import is_packaged
    if sys.platform != "win32" or is_packaged():
        return False
    try:
        import ctypes

        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = [ctypes.c_wchar_p]
        setter.restype = ctypes.c_long
        result = setter(APP_USER_MODEL_ID)
        return result >= 0
    except (AttributeError, OSError):
        return False


def apply_fluent_window_backdrop(widget):
    """Windows 11 창에 둥근 모서리와 탭 앱용 Mica Alt를 적용한다.

    지원하지 않는 Windows나 다른 운영체제에서는 조용히 기존 창 모양을
    유지한다. Qt 위젯의 본문 배경은 그대로 두고 DWM 제목 표시줄만 연결한다.
    """
    if sys.platform != "win32":
        return False
    try:
        if sys.getwindowsversion().build < 22621:
            return False
        import ctypes
        from ctypes import wintypes

        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        setter.restype = ctypes.c_long
        hwnd = wintypes.HWND(int(widget.winId()))

        corner = ctypes.c_int(DWMWCP_ROUND)
        setter(
            hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner), ctypes.sizeof(corner),
        )
        backdrop = ctypes.c_int(DWMSBT_TABBEDWINDOW)
        result = setter(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop), ctypes.sizeof(backdrop),
        )
        return result >= 0
    except (AttributeError, OSError, TypeError, ValueError):
        return False
