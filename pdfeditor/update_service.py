"""GitHub Releases 기반 업데이트 확인, 다운로드, 설치 실행."""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


GITHUB_REPOSITORY = "loselessss/Leaflet"
GITHUB_API_URL = (
    "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPOSITORY)
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_INSTALLER_RE = re.compile(
    r"^(?:Leaflet|sPDF)_Setup_(\d+\.\d+\.\d+)\.exe$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_MAX_RELEASE_JSON_BYTES = 2 * 1024 * 1024
_LOCALIZED_NOTES_RE = re.compile(
    r"<!--\s*spdf-release-notes:start:(?P<language>en|ko)\s*-->"
    r"(?P<body>.*?)"
    r"<!--\s*spdf-release-notes:end:(?P=language)\s*-->",
    re.DOTALL | re.IGNORECASE)


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class AvailableUpdate:
    version: str
    tag_name: str
    release_name: str
    release_notes: str
    release_url: str
    asset: object


@dataclass(frozen=True)
class UpdateDownloadProgress:
    completed_bytes: int
    total_bytes: int
    bytes_per_second: float


def version_tuple(value):
    match = _VERSION_RE.fullmatch(value.strip())
    if not match:
        raise UpdateError("지원하지 않는 버전 형식입니다: %s" % value)
    return tuple(int(part) for part in match.groups())


def _trusted_github_url(value, release_asset=False):
    parsed = urlparse(value)
    if parsed.scheme.casefold() != "https" or \
            (parsed.hostname or "").casefold() != "github.com":
        return False
    expected = "/%s/releases/" % GITHUB_REPOSITORY
    path = parsed.path.rstrip("/") + "/"
    if not path.casefold().startswith(expected.casefold()):
        return False
    if release_asset and "/download/" not in path.casefold():
        return False
    return not parsed.params and not parsed.query and not parsed.fragment


def localized_release_notes(body, language="en"):
    """Return the requested language block from a bilingual release body."""
    text = str(body or "")
    blocks = {
        match.group("language").lower(): match.group("body").strip()
        for match in _LOCALIZED_NOTES_RE.finditer(text)
    }
    if not blocks:
        return text
    requested = str(language or "en").lower()
    return blocks.get(requested) or blocks.get("en") or next(iter(blocks.values()))


class GitHubUpdateService:
    def __init__(self, current_version, opener=urlopen, download_root=None,
                 language="en"):
        self.current_version = current_version
        self._open = opener
        self._download_root = download_root
        self.language = language if language in ("en", "ko") else "en"

    def _download_directory(self):
        return Path(self._download_root) if self._download_root is not None else (
            Path(tempfile.gettempdir()) / "sPDF" / "updates")

    def cleanup_downloads(self):
        """Remove only sPDF updater files from the dedicated temp directory.

        The newly installed application calls this more than once because the
        installer executable can remain locked briefly while Inno Setup exits.
        Unrelated files are deliberately left alone.
        """
        root = self._download_directory()
        if not root.is_dir():
            return 0
        removed = 0
        try:
            entries = list(root.iterdir())
        except OSError:
            return 0
        for path in entries:
            name = path.name
            installer_name = (
                name[:-5] if name.casefold().endswith(".part") else name)
            if not _INSTALLER_RE.fullmatch(installer_name) or not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        try:
            root.rmdir()
        except OSError:
            pass
        return removed

    def check(self):
        request = Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Leaflet/%s" % self.current_version,
                "X-GitHub-Api-Version": "2022-11-28",
            })
        try:
            with self._open(request, timeout=15) as response:
                payload = response.read(_MAX_RELEASE_JSON_BYTES + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            raise UpdateError(
                "GitHub 릴리스 정보를 확인하지 못했습니다: %s" % error)
        if len(payload) > _MAX_RELEASE_JSON_BYTES:
            raise UpdateError("GitHub 릴리스 응답이 허용 크기를 초과했습니다.")
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise UpdateError("GitHub 릴리스 응답을 읽지 못했습니다: %s" % error)
        if not isinstance(data, dict):
            raise UpdateError("GitHub 릴리스 응답 형식이 올바르지 않습니다.")

        tag_name = str(data.get("tag_name", "")).strip()
        latest_version = tag_name[1:] if tag_name.startswith("v") else tag_name
        if version_tuple(latest_version) <= version_tuple(self.current_version):
            return None
        if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag_name):
            raise UpdateError("GitHub 릴리스 태그 형식이 올바르지 않습니다.")
        release_url = "https://github.com/%s/releases/tag/%s" % (
            GITHUB_REPOSITORY, tag_name)
        return AvailableUpdate(
            version=latest_version,
            tag_name=tag_name,
            release_name=str(data.get("name") or tag_name),
            release_notes=localized_release_notes(
                data.get("body"), self.language),
            release_url=release_url,
            asset=self._select_installer(data.get("assets"), latest_version))

    def _select_installer(self, assets, version):
        if not isinstance(assets, list):
            return None
        expected = ("Leaflet_Setup_%s.exe" % version,
                    "sPDF_Setup_%s.exe" % version)
        candidates = [
            item for name in expected for item in assets if isinstance(item, dict)
            and str(item.get("name", "")).casefold() == name.casefold()]
        if not candidates:
            return None
        item = candidates[0]
        name = str(item.get("name", ""))
        download_url = str(item.get("browser_download_url", ""))
        if Path(name).name != name or not _INSTALLER_RE.fullmatch(name) or \
                not _trusted_github_url(download_url, release_asset=True):
            raise UpdateError("릴리스 설치 파일 정보가 안전하지 않습니다.")
        digest = str(item.get("digest") or "")
        match = _SHA256_RE.fullmatch(digest)
        return ReleaseAsset(
            name=name,
            download_url=download_url,
            size=max(0, int(item.get("size") or 0)),
            sha256=match.group(1).lower() if match else "")

    def download(self, update, progress=None, cancel=None):
        asset = update.asset
        if asset is None:
            raise UpdateError("이 릴리스에는 Windows 설치 파일이 없습니다.")
        if not asset.sha256:
            raise UpdateError(
                "설치 파일의 SHA-256 정보가 없어 자동 업데이트할 수 없습니다.")
        root = self._download_directory()
        root.mkdir(parents=True, exist_ok=True)
        destination = root / asset.name
        partial = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        completed = 0
        started = time.monotonic()
        request = Request(
            asset.download_url,
            headers={"User-Agent": "Leaflet/%s" % self.current_version})
        try:
            with self._open(request, timeout=60) as response, \
                    partial.open("wb") as stream:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateCancelled("업데이트 다운로드를 취소했습니다.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                    digest.update(chunk)
                    completed += len(chunk)
                    if progress is not None:
                        elapsed = max(time.monotonic() - started, 0.001)
                        progress(UpdateDownloadProgress(
                            completed, asset.size, completed / elapsed))
                stream.flush()
                os.fsync(stream.fileno())
        except UpdateCancelled:
            if partial.exists():
                partial.unlink()
            raise
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            if partial.exists():
                partial.unlink()
            raise UpdateError("업데이트 다운로드에 실패했습니다: %s" % error)
        if asset.size and completed != asset.size:
            partial.unlink()
            raise UpdateError(
                "설치 파일 크기가 다릅니다: %s / %s bytes"
                % (format(completed, ","), format(asset.size, ",")))
        if digest.hexdigest().lower() != asset.sha256:
            partial.unlink()
            raise UpdateError("설치 파일 SHA-256 검증에 실패했습니다.")
        os.replace(str(partial), str(destination))
        return destination

    def launch_installer(self, path):
        installer = Path(path).resolve()
        if not installer.is_file() or installer.suffix.casefold() != ".exe" or \
                not _INSTALLER_RE.fullmatch(installer.name):
            raise UpdateError("실행할 업데이트 설치 파일이 올바르지 않습니다.")
        try:
            installer_language = "korean" if self.language == "ko" else "english"
            subprocess.Popen(
                [str(installer), "/SP-", "/CLOSEAPPLICATIONS",
                 "/LANG=%s" % installer_language],
                close_fds=True,
                creationflags=getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        except (OSError, subprocess.SubprocessError) as error:
            raise UpdateError(
                "업데이트 설치 파일을 실행하지 못했습니다: %s" % error)
