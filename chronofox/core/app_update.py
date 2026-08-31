"""GitHub Releases 기반 수동 업데이트의 Qt-free 검증·다운로드 로직."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from chronofox.core.app_constants import UPDATE_API_URL

RELEASE_DOWNLOAD_PREFIX = "/YuRang211/ChronoFox/releases/download/"
INITIAL_HOST = "github.com"
REDIRECT_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})
SETUP_MAX_BYTES = 300 * 1024 * 1024
CHECKSUM_MAX_BYTES = 256 * 1024
_SEMVER_RE = re.compile(
    r"^v?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*))?$"
)
_CHECKSUM_RE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>[^/\\\r\n]+)$")


class ReleaseError(ValueError):
    """릴리스 메타데이터나 checksum 계약이 올바르지 않음."""


class DownloadError(OSError):
    """다운로드가 안전하게 완료되지 않음."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = _SEMVER_RE.fullmatch(str(value).strip())
        if match is None:
            raise ValueError(f"invalid SemVer: {value!r}")
        prerelease_text = match.group("prerelease")
        prerelease: tuple[int | str, ...] = ()
        if prerelease_text:
            prerelease = tuple(int(item) if item.isdigit() else item for item in prerelease_text.split("."))
        return cls(int(match.group("major")), int(match.group("minor")), int(match.group("patch")), prerelease)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return base if not self.prerelease else f"{base}-{".".join(map(str, self.prerelease))}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        core = (self.major, self.minor, self.patch)
        other_core = (other.major, other.minor, other.patch)
        if core != other_core:
            return core < other_core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease, strict=False):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, str):
                return True
            if isinstance(left, str) and isinstance(right, int):
                return False
            return left < right
        return len(self.prerelease) < len(other.prerelease)


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    size: int
    digest: str | None = None


@dataclass(frozen=True)
class UpdateRelease:
    version: SemVer
    tag: str
    prerelease: bool
    notes: str
    html_url: str
    setup: ReleaseAsset
    checksum: ReleaseAsset


def validate_download_url(url: str, *, final: bool = False) -> None:
    parsed = urlparse(str(url))
    hosts = REDIRECT_HOSTS if final else {INITIAL_HOST}
    try:
        port = parsed.port
    except ValueError as exc:
        raise ReleaseError("업데이트 URL 포트가 올바르지 않습니다.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        raise ReleaseError("허용되지 않은 업데이트 URL입니다.")
    if not final and not parsed.path.startswith(RELEASE_DOWNLOAD_PREFIX):
        raise ReleaseError("공식 Release 다운로드 URL이 아닙니다.")


def _asset_from_json(row: object, expected_name: str, *, max_bytes: int) -> ReleaseAsset:
    if not isinstance(row, dict) or row.get("name") != expected_name:
        raise ReleaseError("업데이트 자산 형식이 올바르지 않습니다.")
    size = row.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= max_bytes:
        raise ReleaseError("업데이트 자산 크기가 허용 범위를 벗어났습니다.")
    url = row.get("browser_download_url")
    if not isinstance(url, str):
        raise ReleaseError("업데이트 자산 URL이 없습니다.")
    validate_download_url(url)
    digest = row.get("digest")
    if digest is not None and not isinstance(digest, str):
        raise ReleaseError("업데이트 자산 digest 형식이 올바르지 않습니다.")
    return ReleaseAsset(expected_name, url, size, digest)


def select_update_release(
    payload: object,
    *,
    current_version: str,
    channel: str = "beta",
) -> UpdateRelease | None:
    """공개된 릴리스 중 현재보다 큰 최신 유효 SemVer와 필수 자산을 고른다."""
    if channel not in {"stable", "beta"}:
        raise ValueError(f"unsupported update channel: {channel}")
    if not isinstance(payload, list):
        raise ReleaseError("릴리스 응답이 목록이 아닙니다.")
    current = SemVer.parse(current_version)
    candidates: list[tuple[SemVer, dict]] = []
    for row in payload:
        if not isinstance(row, dict) or row.get("draft") is True:
            continue
        if channel == "stable" and row.get("prerelease") is True:
            continue
        try:
            version = SemVer.parse(str(row.get("tag_name", "")))
        except ValueError:
            continue
        if current < version:
            candidates.append((version, row))
    if not candidates:
        return None

    version, release = max(candidates, key=lambda item: item[0])
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ReleaseError("릴리스 자산 목록이 없습니다.")
    setup_name = f"ChronoFox-{version}-Setup.exe"
    setup_rows = [item for item in assets if isinstance(item, dict) and item.get("name") == setup_name]
    checksum_rows = [item for item in assets if isinstance(item, dict) and item.get("name") == "SHA256SUMS.txt"]
    if len(setup_rows) != 1 or len(checksum_rows) != 1:
        raise ReleaseError("필수 업데이트 자산이 없거나 중복되었습니다.")
    setup = _asset_from_json(setup_rows[0], setup_name, max_bytes=SETUP_MAX_BYTES)
    checksum = _asset_from_json(checksum_rows[0], "SHA256SUMS.txt", max_bytes=CHECKSUM_MAX_BYTES)
    notes = str(release.get("body") or "")[:4000]
    return UpdateRelease(
        version=version,
        tag=str(release.get("tag_name", "")),
        prerelease=bool(release.get("prerelease")),
        notes=notes,
        html_url=str(release.get("html_url") or ""),
        setup=setup,
        checksum=checksum,
    )


def fetch_release_payload(*, opener: Callable[..., object] = urlopen, timeout: float = 12.0) -> list[dict]:
    """GitHub API의 공개 Release 목록을 제한된 크기로 읽는다."""
    request = Request(
        UPDATE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ChronoFox-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "api.github.com":
                raise ReleaseError("허용되지 않은 Release API 리다이렉트입니다.")
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ReleaseError("Release 응답이 너무 큽니다.")
        payload = json.loads(raw.decode("utf-8"))
    except ReleaseError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError("Release 응답 형식이 올바르지 않습니다.") from exc
    except OSError as exc:
        raise DownloadError("Release 목록을 읽지 못했습니다.") from exc
    if not isinstance(payload, list):
        raise ReleaseError("Release 응답이 목록이 아닙니다.")
    return payload


def parse_checksum(text: str, filename: str) -> str:
    matches: list[str] = []
    for line in text.splitlines():
        if not line:
            continue
        match = _CHECKSUM_RE.fullmatch(line)
        if match is None:
            raise ReleaseError("checksum 파일 형식이 올바르지 않습니다.")
        if match.group("name") == filename:
            matches.append(match.group("digest"))
    if len(matches) != 1:
        raise ReleaseError("설치 파일 checksum이 없거나 중복되었습니다.")
    return matches[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installer(path: Path, checksum_text: str, *, api_digest: str | None = None) -> str:
    expected = parse_checksum(checksum_text, path.name)
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise ReleaseError("설치 파일 checksum이 일치하지 않습니다.")
    if api_digest and (not api_digest.startswith("sha256:") or not hmac.compare_digest(api_digest[7:], expected)):
        raise ReleaseError("GitHub asset digest가 checksum과 일치하지 않습니다.")
    return actual


def download_atomic(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    expected_size: int | None = None,
    opener: Callable[..., object] = urlopen,
    stop_requested: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int | None], None] | None = None,
    timeout: float = 20.0,
) -> Path:
    """허용된 URL을 제한 크기로 내려받고 완료된 파일만 원자 교체한다."""
    validate_download_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    total = 0
    try:
        request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "ChronoFox-Updater"})
        with opener(request, timeout=timeout) as response:
            final_url = response.geturl()
            try:
                validate_download_url(final_url, final=True)
            except ReleaseError as exc:
                raise DownloadError("허용되지 않은 다운로드 리다이렉트입니다.") from exc
            header_value = response.headers.get("Content-Length")
            header_size = int(header_value) if header_value is not None else None
            if header_size is not None and (header_size < 1 or header_size > max_bytes):
                raise DownloadError("다운로드 크기가 허용 범위를 벗어났습니다.")
            if expected_size is not None and header_size is not None and header_size != expected_size:
                raise DownloadError("다운로드 크기 정보가 릴리스 정보와 다릅니다.")
            with partial.open("xb") as stream:
                while True:
                    if stop_requested():
                        raise DownloadError("다운로드가 중단되었습니다.")
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError("다운로드 크기가 허용 범위를 벗어났습니다.")
                    stream.write(chunk)
                    if progress is not None:
                        progress(total, expected_size)
                stream.flush()
                os.fsync(stream.fileno())
        if total < 1 or (expected_size is not None and total != expected_size):
            raise DownloadError("다운로드가 완전하지 않습니다.")
        os.replace(partial, destination)
        return destination
    except (ReleaseError, DownloadError):
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise DownloadError("업데이트 파일을 내려받지 못했습니다.") from exc


def is_inno_installed_runtime(
    *,
    executable: Path | None = None,
    frozen: bool | None = None,
) -> bool:
    target = Path(sys.executable if executable is None else executable)
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    return is_frozen and (target.parent / "unins000.exe").is_file()
