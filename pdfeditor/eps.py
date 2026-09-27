"""Convert EPS into a private PDF using an installed Ghostscript interpreter."""
import os
from pathlib import Path
import re
import shutil
import subprocess


def find_ghostscript():
    for name in ("gswin64c.exe", "gswin32c.exe", "gs"):
        executable = shutil.which(name)
        if executable:
            return executable
    candidates = []
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates.extend((Path(root) / "gs").glob("gs*/bin/gswin*c.exe"))
    if candidates:
        return str(max(candidates, key=lambda p: tuple(
            int(n) for n in re.findall(r"\d+", p.parent.parent.name))))
    raise RuntimeError(
        "EPS 파일을 열려면 Ghostscript를 설치해 주세요. / "
        "Install Ghostscript to open EPS files: https://www.ghostscript.com/releases/gsdnld.html")


def convert_eps(source, destination):
    """Preserve vector content and the EPS bounding box; never modify source."""
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if source == destination:
        raise ValueError("EPS 원본에 덮어쓸 수 없습니다.")
    executable = find_ghostscript()
    env = {key: value for key, value in os.environ.items()
           if key.upper() not in {"GS_OPTIONS", "GS_LIB", "GS_FONTPATH"}}
    try:
        result = subprocess.run(
            [executable, "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dEPSCrop",
             "-sDEVICE=pdfwrite", "-dAutoRotatePages=/None",
             "-sOutputFile=" + str(destination), "-f", str(source)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=120, env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("EPS 변환 시간 제한을 초과했습니다. / EPS conversion timed out.") from error
    if result.returncode or not destination.is_file():
        raise RuntimeError("EPS 파일을 변환할 수 없습니다. / Unable to convert this EPS file.")
    with destination.open("rb") as stream:
        if not stream.read(5) == b"%PDF-":
            raise RuntimeError("EPS 변환 결과가 올바른 PDF가 아닙니다.")
