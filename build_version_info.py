"""PyInstaller EXE용 Windows 버전 리소스를 빌드 폴더에 생성한다."""

from pathlib import Path
from pdfeditor.meta import APP_NAME


def _version_tuple(version):
    parts = [int(part) for part in version.split(".")]
    if not 1 <= len(parts) <= 4:
        raise ValueError("Windows 버전은 1~4개의 숫자여야 합니다: %s" % version)
    return tuple(parts + [0] * (4 - len(parts)))


def version_info_text(version, description, internal_name, filename):
    """PyInstaller가 읽는 VSVersionInfo 텍스트를 반환한다."""
    numeric = repr(_version_tuple(version))
    strings = {
        "CompanyName": APP_NAME,
        "FileDescription": description,
        "FileVersion": version,
        "InternalName": internal_name,
        "OriginalFilename": filename,
        "ProductName": APP_NAME,
        "ProductVersion": version,
    }
    string_rows = ",\n        ".join(
        "StringStruct(%r, %r)" % item for item in strings.items())
    return """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric},
    prodvers={numeric},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('041204B0', [
        {string_rows}
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])
  ])
""".format(numeric=numeric, string_rows=string_rows)


def write_version_info_files(directory, version):
    """GUI와 OCR 작업 프로세스의 버전 리소스를 만들고 경로를 반환한다."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    definitions = (
        ("spdf-version.txt", APP_NAME, "sPDF", "sPDF.exe"),
        ("spdf-ocr-version.txt", "Leaflet OCR 작업 프로세스",
         "sPDF OCR Worker", "spdf-ocr.exe"),
    )
    paths = []
    for name, description, internal_name, filename in definitions:
        path = directory / name
        path.write_text(
            version_info_text(version, description, internal_name, filename),
            encoding="utf-8")
        paths.append(str(path.resolve()))
    return tuple(paths)
