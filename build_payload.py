"""Remove unused desktop-package payloads without sharing worker DLL folders."""

from pathlib import Path, PurePosixPath


_UNUSED_QT_LIBRARIES = {
    "qt5quick.dll", "qt5qml.dll", "qt5qmlmodels.dll",
    "qt5websockets.dll", "qt5dbus.dll",
}


def native_worker_runtime_binaries(*modules, search_paths=None):
    """Put MSVC DLLs beside the independent worker, before its entry point runs.

    The GUI's Qt DLL directories are not the worker executable directory. Its
    directly imported runtime and the dynamically loaded MuPDF runtime must be
    discoverable without requiring a machine-wide C++ runtime installation.
    """
    from PyInstaller.depend.bindepend import get_imports
    runtimes = {}
    for module in modules:
        for name, source in get_imports(str(module), search_paths=search_paths):
            key = name.lower()
            if key.startswith(('msvcp140', 'vcruntime140', 'concrt140')) and key.endswith('.dll'):
                if source is None:
                    raise RuntimeError(f'Native reader worker runtime is missing: {name}')
                runtimes.setdefault(key, source)
    return [(source, 'native') for _, source in sorted(runtimes.items())]


def keep_payload(destination, *, gui):
    path = PurePosixPath(destination.replace("\\", "/"))
    name = path.name.lower()
    if name.startswith("opencv_videoio_ffmpeg") and name.endswith(".dll"):
        # OCR uses still-image processing, never VideoCapture/VideoWriter.
        return False
    if gui and "pyqt5" in str(path).lower():
        if name in _UNUSED_QT_LIBRARIES or name in (
                "qwebgl.dll", "qxdgdesktopportal.dll"):
            return False
        if "translations" in path.parts and name.endswith(".qm"):
            # Leaflet exposes English and Korean; retain both Qt locales.
            locale = path.stem.partition("_")[2].partition("_")[0]
            return locale in ("en", "ko")
    return True


def trim_payload(binaries, datas, *, gui):
    kept_binaries = [entry for entry in binaries if keep_payload(entry[0], gui=gui)]
    kept_datas = [entry for entry in datas if keep_payload(entry[0], gui=gui)]
    removed = [entry for entry in binaries if not keep_payload(entry[0], gui=gui)]
    removed_names = {PurePosixPath(entry[0].replace("\\", "/")).name.lower()
                     for entry in removed}
    if removed_names:
        # Fail the build if an upstream wheel starts linking a retained module
        # against an excluded DLL. Optional runtime video/web plugins are safe
        # to omit; a required native import is not.
        import pefile
        for destination, source, kind in kept_binaries:
            if kind not in ("BINARY", "EXTENSION"):
                continue
            with pefile.PE(source, fast_load=True) as image:
                image.parse_data_directories(directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                ])
                for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
                    for dependency in getattr(image, attribute, ()):
                        name = dependency.dll.decode("ascii").lower()
                        if name in removed_names:
                            raise RuntimeError(f"Cannot trim required DLL: {destination} needs {name}")
    all_removed = removed + [entry for entry in datas
                             if not keep_payload(entry[0], gui=gui)]
    cost = sum(Path(entry[1]).stat().st_size for entry in all_removed)
    print(f"Trimmed {'GUI' if gui else 'OCR'} payload: {len(all_removed)} files, "
          f"{cost / (1024 * 1024):.1f} MiB before compression")
    return kept_binaries, kept_datas
