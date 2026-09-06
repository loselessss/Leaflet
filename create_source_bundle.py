"""Publish tagged app source and exact-version dependency-source directions.

Upstream source hosting is used under AGPL/GPL section 6(d); maintainers
remain responsible for source availability and native-wheel correspondence.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import zipfile

from build_legal import normalized
from pdfeditor.meta import APP_VERSION


COMPANION_FILES = {
    "paper_organizer.py", "paper_organizer.pyw", "tests/test_paperlib.py",
    "tests/test_paper_settings.py", "docs/PAPER_ORGANIZER_INTEGRATION.md",
}


def include_source(name):
    path = PurePosixPath(name)
    return (bool(path.parts) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and name not in COMPANION_FILES
            and path.parts[:2] != ("native", "bin")
            and path.parts[0] not in {"paperorganizer", ".git", ".venv", "build", "dist", "Output", "test"})


def clean_source_status(status):
    # build_exe regenerates these derived assets from the tagged make_icons.py.
    # Font/Pillow differences can change their bytes on the build server.
    allowed = {b" M assets/spdf.ico", b" M assets/spdf_doc.ico",
               b" M native/bin/spdf_d2d_renderer.dll"}
    return all(line in allowed for line in status.splitlines())


def read_json(url):
    request = Request(url, headers={"User-Agent": "sPDF-source-release"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def source_record(package, fetch=read_json):
    name, version = package["name"], package["version"]
    canonical = normalized(name)
    data = fetch("https://pypi.org/pypi/%s/%s/json" % (quote(name, safe=""), quote(version, safe="")))
    if (normalized(data["info"]["name"]) != canonical
            or data["info"]["version"] != version):
        raise ValueError("Source metadata version mismatch: " + name)
    sources = [entry for entry in data["urls"] if entry["packagetype"] == "sdist"]
    if sources:
        entry = sorted(sources, key=lambda item: item["filename"])[0]
        url, digest = entry["url"], entry["digests"]["sha256"]
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError("Missing source SHA-256: " + name)
    elif canonical == "pyqt5-qt5" and version == "5.15.2":
        url = "https://download.qt.io/archive/qt/5.15/5.15.2/single/qt-everywhere-src-5.15.2.tar.xz"
        digest = None
    elif canonical in {"onnxruntime", "flatbuffers", "rapidocr"} and re.fullmatch(r"\d+\.\d+\.\d+", version):
        repository = {"onnxruntime": "microsoft/onnxruntime",
                      "flatbuffers": "google/flatbuffers", "rapidocr": "RapidAI/RapidOCR"}[canonical]
        url = "https://github.com/%s/archive/refs/tags/v%s.tar.gz" % (repository, version)
        digest = None
    elif canonical == "pywin32" and version.isdigit():
        url = "https://github.com/mhammond/pywin32/archive/refs/tags/b%s.tar.gz" % version
        digest = None
    else:
        # Never silently point a wheel-only dependency at an unrelated main branch.
        raise ValueError("Exact upstream source mapping required: %s==%s" % (name, version))
    if urlparse(url).scheme != "https":
        raise ValueError("Source URL must use HTTPS: " + name)
    return {"name": name, "version": version, "url": url, "sha256": digest}


def check_source_access(record):
    request = Request(record["url"], method="HEAD", headers={"User-Agent": "sPDF-source-release"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError("Source archive is unavailable: " + record["name"])


def dependency_document(version, records):
    lines = [
        "# sPDF %s dependency sources / 의존성 소스" % version, "",
        "These exact-version upstream archives accompany the application source ZIP.",
        "이 소스들은 앱 소스 ZIP과 함께 사용합니다. 링크가 끊기면 배포자가 대응 소스를 제공해야 합니다.",
        "PyMuPDF's sdist contains its MuPDF source archive; retain its build configuration.",
        "Upstream archives may require submodules or build tools described in their own documentation.",
        "This inventory does not replace a native-binary/license audit. See SOURCE_CODE.md.", "",
    ]
    for record in records:
        lines += ["## %s %s" % (record["name"], record["version"]), "",
                  "[Source archive / 소스 받기](%s)" % record["url"], ""]
        if record["sha256"]:
            lines += ["SHA-256: `%s`" % record["sha256"], ""]
    return "\n".join(lines)


def write_archive(destination, archive_bytes, legal_root, document, records, version):
    prefix = "sPDF-%s/" % version
    # Exclusive creation prevents accidental replacement of existing release assets.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as output:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as source:
            for item in source.infolist():
                if not item.is_dir() and include_source(item.filename):
                    output.writestr(prefix + item.filename, source.read(item))
        for path in sorted(Path(legal_root).rglob("*")):
            if path.is_symlink():
                raise ValueError("Symlink in generated legal bundle")
            if path.is_file():
                output.write(path, prefix + "third-party/" + path.relative_to(legal_root).as_posix())
        output.writestr(prefix + "DEPENDENCY_SOURCES.md", document)
        output.writestr(prefix + "dependency-sources.json", json.dumps(records, indent=2) + "\n")


def prepare_source_release(root, version):
    root = Path(root)
    if version != APP_VERSION or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Source release version must match APP_VERSION")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root)

    if not clean_source_status(git("status", "--porcelain", "--untracked-files=normal")):
        raise ValueError("Release source requires a clean working tree")
    commit = git("rev-parse", "HEAD").decode().strip()
    if git("rev-parse", "v%s^{commit}" % version).decode().strip() != commit:
        raise ValueError("Release tag must match HEAD")
    legal = root / "build" / "legal"
    environment = json.loads((legal / "build-environment.json").read_text(encoding="utf-8"))
    if environment["commit"] != commit or environment["app_version"] != version:
        raise ValueError("Legal inventory belongs to a different build")
    packages = environment["packages"]
    if not {"pymupdf", "pyqt5", "pyqt5-qt5"}.issubset({normalized(p["name"]) for p in packages}):
        raise ValueError("Required runtime dependencies missing from build inventory")
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(source_record, packages))
    python_version = environment["python"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", python_version):
        raise ValueError("Unsupported Python source version")
    records.append({"name": "Python", "version": python_version, "sha256": None,
                    "url": "https://www.python.org/ftp/python/%s/Python-%s.tar.xz" % (python_version, python_version)})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(check_source_access, records))
    document = dependency_document(version, records)
    output = root / "Output"
    output.mkdir(exist_ok=True)
    archive_path = output / ("sPDF_Source_%s.zip" % version)
    write_archive(archive_path, git("archive", "--format=zip", "HEAD"), legal, document, records, version)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with Path(str(archive_path) + ".sha256").open("x", encoding="ascii") as stream:
        stream.write(digest + "  " + archive_path.name + "\n")
    with (output / ("sPDF_Dependency_Sources_%s.md" % version)).open("x", encoding="utf-8") as stream:
        stream.write(document)
    return archive_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    print(prepare_source_release(Path(__file__).resolve().parent, args.version))
