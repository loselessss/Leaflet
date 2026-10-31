"""Build the optional CPython path packer with the active Python and Cargo."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def main():
    root = Path(__file__).resolve().parent.parent
    manifest = root / "native/path_packer/Cargo.toml"
    target = root / "native/bin/path-packer-target"
    env = dict(os.environ, PYO3_PYTHON=sys.executable)
    cargo = shutil.which("cargo")
    if cargo is None:
        raise RuntimeError("Install Rust (MSVC x64) and put cargo on PATH first")
    subprocess.run([cargo, "build", "--release", "--locked", "--manifest-path",
                    str(manifest), "--target-dir", str(target)], env=env, check=True)
    shutil.copy2(target / "release/_path_packer.dll", root / "pdfeditor/_path_packer.pyd")
    metadata = json.loads(subprocess.check_output([
        cargo, "metadata", "--locked", "--format-version", "1", "--manifest-path",
        str(manifest)], env=env, text=True))
    legal = root / "native/bin/path-packer-legal"
    legal.mkdir(parents=True, exist_ok=True)
    records = []
    lock = tomllib.loads(manifest.with_name("Cargo.lock").read_text(encoding="utf-8"))
    checksums = {(p["name"], p["version"]): p.get("checksum") for p in lock["package"]}
    for package in metadata["packages"]:
        if not package["source"]:
            continue
        source = Path(package["manifest_path"]).parent
        destination = legal / (package["name"] + "-" + package["version"])
        destination.mkdir(exist_ok=True)
        for notice in source.iterdir():
            if notice.is_file() and notice.name.upper().startswith(("LICENSE", "NOTICE", "COPYING")):
                shutil.copy2(notice, destination / notice.name)
        records.append({"name": package["name"], "version": package["version"],
                        "license": package["license"],
                        "sha256": checksums[(package["name"], package["version"])],
                        "url": "https://crates.io/api/v1/crates/%s/%s/download" %
                                  (package["name"], package["version"])})
    sysroot = Path(subprocess.check_output(["rustc", "--print", "sysroot"], env=env, text=True).strip())
    rust_docs = sysroot / "share/doc/rust"
    shutil.copytree(rust_docs / "licenses", legal / "rust-runtime/licenses", dirs_exist_ok=True)
    shutil.copy2(rust_docs / "COPYRIGHT-library.html", legal / "rust-runtime/COPYRIGHT-library.html")
    compiler = subprocess.check_output(["rustc", "--version", "--verbose"], env=env, text=True)
    commit = next(line.split(": ", 1)[1] for line in compiler.splitlines() if line.startswith("commit-hash:"))
    records.append({"name": "Rust standard library", "version": commit,
                    "license": "MIT OR Apache-2.0 and bundled notices", "sha256": None,
                    "url": "https://github.com/rust-lang/rust/archive/" + commit + ".tar.gz"})
    (legal / "dependencies.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    shutil.copy2(manifest.with_name("Cargo.lock"), legal / "Cargo.lock")
    (legal / "rustc.txt").write_text(compiler, encoding="utf-8")


if __name__ == "__main__":
    main()
