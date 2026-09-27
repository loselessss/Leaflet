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
FILE_TYPES = ((".pdf", PROG_ID, "PDF", "spdf_doc.ico"),
              (".ai", "Leaflet.Illustrator", "AI", "leaflet_ai.ico"),
              (".eps", "Leaflet.EPS", "EPS", "leaflet_eps.ico"))
EXTENSIONS = tuple(item[0] for item in FILE_TYPES)
HERE = os.path.dirname(os.path.abspath(__file__))


def _pythonw():
    """run.pyw를 콘솔 없이 띄울 pythonw.exe 경로."""
    cand = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable


def register():
    pythonw = _pythonw()
    runpyw = os.path.join(HERE, "run.pyw")
    command = '"%s" "%s" "%%1"' % (pythonw, runpyw)

    for extension, prog_id, label, icon in FILE_TYPES:
        base = r"Software\Classes\%s" % prog_id
        for suffix, value in (("", label),
                              (r"\DefaultIcon", '"%s",0' % os.path.join(HERE, "assets", icon)),
                              (r"\shell\open\command", command)):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + suffix) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, value)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Classes\%s\OpenWithProgids" % extension) as k:
            if prog_id != PROG_ID:
                try:
                    winreg.DeleteValue(k, PROG_ID)
                except FileNotFoundError:
                    pass
            winreg.SetValueEx(k, prog_id, 0, winreg.REG_NONE, b"")

    print("등록 완료. PDF/AI/EPS 파일의 '연결 프로그램'에 '%s'가 보입니다." % APP_NAME)
    print("명령:", command)


def unregister():
    for prog_id in (*[item[1] for item in FILE_TYPES], LEGACY_PROG_ID):
        for path in (
                r"Software\Classes\%s\DefaultIcon" % prog_id,
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
