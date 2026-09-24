"""탐색기 '연결 프로그램'에 Leaflet 등록/해제 (설계 §8).

현재 사용자(HKCU)에만 쓰므로 관리자 권한이 필요 없고, 기본 PDF 뷰어를
빼앗지도 않는다 — 우클릭 '연결 프로그램' 후보로만 나타난다. 기본 앱
지정은 Windows 설정에서 사용자가 직접.

    python register_filetype.py            # 등록
    python register_filetype.py --unregister
"""
import os
import sys
import winreg

PROG_ID = "sPDF.Document"
LEGACY_PROG_ID = "PDFEditor.Document"
from pdfeditor.meta import APP_NAME
EXTENSIONS = (".pdf", ".ai")
HERE = os.path.dirname(os.path.abspath(__file__))


def _pythonw():
    """run.pyw를 콘솔 없이 띄울 pythonw.exe 경로."""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def register():
    pythonw = _pythonw()
    runpyw = os.path.join(HERE, "run.pyw")
    command = '"%s" "%s" "%%1"' % (pythonw, runpyw)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Classes\%s" % PROG_ID) as k:
        winreg.SetValueEx(
            k, "", 0, winreg.REG_SZ, "PDF")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                          r"Software\Classes\%s\shell\open\command" % PROG_ID) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)

    # 기본값은 덮어쓰지 않고 '연결 프로그램' 후보에만 추가한다.
    for extension in EXTENSIONS:
        with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\%s\OpenWithProgids" % extension) as k:
            winreg.SetValueEx(k, PROG_ID, 0, winreg.REG_NONE, b"")

    print("등록 완료. PDF/AI 파일의 '연결 프로그램'에 '%s'가 보입니다." % APP_NAME)
    print("명령:", command)


def unregister():
    for prog_id in (PROG_ID, LEGACY_PROG_ID):
        for path in (
                r"Software\Classes\%s\shell\open\command" % prog_id,
                r"Software\Classes\%s\shell\open" % prog_id,
                r"Software\Classes\%s\shell" % prog_id,
                r"Software\Classes\%s" % prog_id):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        for extension in EXTENSIONS:
            try:
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Classes\%s\OpenWithProgids" % extension,
                        0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, prog_id)
            except FileNotFoundError:
                pass
    print("등록 해제 완료.")


if __name__ == "__main__":
    if "--unregister" in sys.argv:
        unregister()
    else:
        register()
