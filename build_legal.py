"""Collect build versions and original notices, without importing GUI/OCR code.

This is an inventory, not an assertion of complete license compliance.
Generated data is bundled with both the executable and release source archive.
"""

from importlib import metadata
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from pdfeditor.meta import APP_VERSION


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def is_notice(path):
    name = Path(str(path)).name.lower()
    return any(word in name for word in ("license", "licence", "copying", "copyright", "notice"))


def collect_distributions(distributions, target):
    packages = []
    for dist in sorted(distributions, key=lambda d: normalized(d.metadata["Name"])):
        name, version = dist.metadata["Name"], dist.version
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name + version):
            raise ValueError("Unsafe package name/version: " + name)
        folder = target / "packages" / (normalized(name) + "-" + version)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "METADATA.txt").write_text(dist.read_text("METADATA") or "", encoding="utf-8")
        notices = []
        for index, entry in enumerate(dist.files or ()):
            if not is_notice(entry):
                continue
            source = Path(dist.locate_file(entry))
            if not source.is_file():
                raise FileNotFoundError("Missing installed notice: " + str(entry))
            if source.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Unexpectedly large notice: " + str(entry))
            # Use a flat destination, never trust wheel RECORD paths as targets.
            destination = folder / (str(index) + "-" + source.name)
            destination.write_bytes(source.read_bytes())
            notices.append(destination.relative_to(target).as_posix())
        packages.append({
            "name": name, "version": version,
            "license": dist.metadata.get("License-Expression") or dist.metadata.get("License", ""),
            "notices": notices,
        })
    return packages


def write_legal_bundle(target, root=None):
    target = Path(target)
    root = Path(root or Path(__file__).resolve().parent)
    target.mkdir(parents=True, exist_ok=False)
    packages = collect_distributions(metadata.distributions(), target)
    rust_legal = root / "native" / "bin" / "path-packer-legal"
    if (root / "pdfeditor" / "_path_packer.pyd").is_file():
        if not (rust_legal / "dependencies.json").is_file():
            raise FileNotFoundError("Rebuild the Rust path packer to generate its notices")
        shutil.copytree(rust_legal, target / "rust")
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        # Recipients can rebuild the source ZIP without Git or a .git folder.
        commit = None
    environment = {
        "app_version": APP_VERSION, "commit": commit,
        "python": platform.python_version(), "platform": platform.platform(),
        "architecture": platform.machine(), "packages": packages,
    }
    (target / "build-environment.json").write_text(
        json.dumps(environment, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (target / "build-requirements.txt").write_text(
        "".join(p["name"] + "==" + p["version"] + "\n" for p in packages), encoding="utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise FileNotFoundError("Python runtime LICENSE.txt is required for the Windows build")
    (target / "Python-LICENSE.txt").write_bytes(python_license.read_bytes())
    return target


if __name__ == "__main__":
    print(write_legal_bundle(Path(__file__).resolve().parent / "build" / "legal"))
