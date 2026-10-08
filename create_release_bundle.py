"""Group matching source, dependency directions and checksums into one asset."""

import argparse
import hashlib
from pathlib import Path
import re
import zipfile


def prepare_release_bundle(output, version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected x.y.z release version")
    output = Path(output)
    source = "Leaflet_Source_%s.zip" % version
    installers = ("Leaflet_Setup_%s.exe" % version, "Leaflet_Setup_latest.exe")
    names = (source, source + ".sha256",
             "Leaflet_Dependency_Sources_%s.md" % version,
             *(name + ".sha256" for name in installers))
    # Never collect a directory recursively: only matching release assets belong
    # in this archive, regardless of other files present in Output.
    for name in (*names, *installers):
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError("Missing regular release file: " + name)
    hashes = []
    for name in (source, *installers):
        with (output / name).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        checksum = (output / (name + ".sha256")).read_text(encoding="ascii").split()
        if checksum != [digest, name]:
            raise ValueError("Release checksum mismatch: " + name)
        hashes.append(digest)
    if hashes[1] != hashes[2]:
        raise ValueError("Latest installer does not match the versioned installer")
    destination = output / ("Leaflet_Release_Files_%s.zip" % version)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.write(output / name, name,
                          compress_type=zipfile.ZIP_STORED if name.endswith(".zip")
                          else zipfile.ZIP_DEFLATED)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "Output")
    args = parser.parse_args()
    print(prepare_release_bundle(args.output, args.version))
