"""수동 보조 업데이트의 Qt 수명주기와 사용자 승인 흐름."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from chronofox.core import app_constants
from chronofox.core.app_constants import (
    APP_VERSION,
    UPDATE_CHANNEL,
    UPDATE_RELEASES_URL,
)
from chronofox.core.app_update import (
    CHECKSUM_MAX_BYTES,
    DownloadError,
    ReleaseAsset,
    ReleaseError,
    UpdateRelease,
    download_atomic,
    fetch_release_payload,
    is_inno_installed_runtime,
    select_update_release,
    verify_installer,
)


class UpdatePhase(StrEnum):
    IDLE = "idle"
    CHECKING = "checking"
    CURRENT = "current"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    CONNECTION_ERROR = "connection_error"
    RELEASE_ERROR = "release_error"
    ERROR = "error"


@dataclass(frozen=True)
class UpdateState:
    phase: UpdatePhase = UpdatePhase.IDLE
    current_version: str = APP_VERSION
    available_version: str | None = None
    progress_percent: int | None = None
    can_check: bool = True
    can_update: bool = False
    installed: bool = False


def _start_daemon(work: Callable[[], None]) -> None:
    threading.Thread(target=work, name="ChronoFoxUpdate", daemon=True).start()


def _launch_setup(path: Path, arguments: list[str]) -> bool:
    result = QProcess.startDetached(str(path), arguments)
    return bool(result[0] if isinstance(result, tuple) else result)


class UpdateController(QObject):
    """사용자 클릭에서만 worker를 시작하고 UI에는 불변 상태만 전달한다."""

    state_changed = Signal(object)
    _check_finished = Signal(object, object)
    _download_finished = Signal(object, object, object)
    _download_progress = Signal(int)

    def __init__(
        self,
        app,
        *,
        cache_root: Path | None = None,
        release_fetcher: Callable[[], object] = fetch_release_payload,
        worker_runner: Callable[[Callable[[], None]], None] = _start_daemon,
        installed_detector: Callable[[], bool] = is_inno_installed_runtime,
        setup_downloader: Callable[[ReleaseAsset, Path, Callable[[], bool], Callable[[int, int | None], None]], Path] | None = None,
        checksum_fetcher: Callable[[ReleaseAsset, Callable[[], bool]], str] | None = None,
        confirmer: Callable[[UpdateRelease], bool] | None = None,
        setup_launcher: Callable[[Path, list[str]], bool] = _launch_setup,
        url_opener: Callable[[QUrl], bool] = QDesktopServices.openUrl,
        quit_app: Callable[[], None] = QApplication.quit,
    ) -> None:
        super().__init__()
        self.app = app
        self.cache_root = Path(cache_root or app_constants.UPDATE_CACHE_DIR)
        self._release_fetcher = release_fetcher
        self._worker_runner = worker_runner
        self._installed_detector = installed_detector
        self._setup_downloader = setup_downloader or self._download_setup
        self._checksum_fetcher = checksum_fetcher or self._download_checksum
        self._confirmer = confirmer or self._confirm_unsigned_update
        self._setup_launcher = setup_launcher
        self._url_opener = url_opener
        self._quit_app = quit_app
        self._release: UpdateRelease | None = None
        self._busy = False
        self._shutdown = False
        self._stop_event = threading.Event()
        self.state = UpdateState(installed=self._installed_detector())
        self._check_finished.connect(self._apply_check_result)
        self._download_finished.connect(self._apply_download_result)
        self._download_progress.connect(self._apply_progress)

    def _set_state(self, state: UpdateState) -> None:
        self.state = state
        self.state_changed.emit(state)

    def check_for_updates(self) -> None:
        if self._busy or self._shutdown:
            return
        self._busy = True
        self._release = None
        self._set_state(UpdateState(phase=UpdatePhase.CHECKING, can_check=False, installed=self.state.installed))

        def work() -> None:
            release = None
            error = None
            try:
                payload = self._release_fetcher()
                release = select_update_release(payload, current_version=APP_VERSION, channel=UPDATE_CHANNEL)
            except Exception as exc:  # 결과 유형은 메인 스레드에서 사용자 상태로 축약한다.
                error = exc
            self._check_finished.emit(release, error)

        self._worker_runner(work)

    def _apply_check_result(self, release: object, error: object) -> None:
        if self._shutdown:
            return
        self._busy = False
        if error is not None:
            phase = UpdatePhase.RELEASE_ERROR if isinstance(error, ReleaseError) else UpdatePhase.CONNECTION_ERROR
            self._set_state(UpdateState(phase=phase, can_check=True, installed=self.state.installed))
            return
        if release is None:
            self._set_state(UpdateState(phase=UpdatePhase.CURRENT, can_check=True, installed=self.state.installed))
            return
        if not isinstance(release, UpdateRelease):
            self._set_state(UpdateState(phase=UpdatePhase.RELEASE_ERROR, can_check=True, installed=self.state.installed))
            return
        self._release = release
        self._set_state(
            UpdateState(
                phase=UpdatePhase.AVAILABLE,
                available_version=str(release.version),
                can_check=True,
                can_update=True,
                installed=self.state.installed,
            )
        )

    def start_update(self) -> None:
        if self._busy or self._shutdown or self._release is None or not self.state.can_update:
            return
        if not self.state.installed:
            if not self._url_opener(QUrl(UPDATE_RELEASES_URL)):
                self._set_state(replace(self.state, phase=UpdatePhase.ERROR))
            return
        self._busy = True
        self._set_state(replace(self.state, phase=UpdatePhase.DOWNLOADING, can_check=False, can_update=False, progress_percent=0))
        release = self._release

        def work() -> None:
            installer = None
            error = None
            try:
                version_dir = self.cache_root / str(release.version)
                installer_path = version_dir / release.setup.name
                installer = self._setup_downloader(release.setup, installer_path, self._stop_event.is_set, self._emit_progress)
                checksum_text = self._checksum_fetcher(release.checksum, self._stop_event.is_set)
                verify_installer(Path(installer), checksum_text, api_digest=release.setup.digest)
            except Exception as exc:
                error = exc
                if isinstance(installer, (str, Path)):
                    Path(installer).unlink(missing_ok=True)
            self._download_finished.emit(release, installer, error)

        self._worker_runner(work)

    def _emit_progress(self, received: int, total: int | None) -> None:
        percent = 0 if not total else min(100, int(received * 100 / total))
        self._download_progress.emit(percent)

    def _apply_progress(self, percent: int) -> None:
        if not self._shutdown and self.state.phase is UpdatePhase.DOWNLOADING:
            self._set_state(replace(self.state, progress_percent=percent))

    def _apply_download_result(self, release: object, installer: object, error: object) -> None:
        if self._shutdown:
            return
        self._busy = False
        if error is not None or not isinstance(release, UpdateRelease) or installer is None:
            self._set_state(replace(self.state, phase=UpdatePhase.ERROR, can_check=True, can_update=True))
            return
        if not self._confirmer(release):
            self._set_state(replace(self.state, phase=UpdatePhase.AVAILABLE, can_check=True, can_update=True))
            return
        try:
            self.app.save()
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.app.create_backup(app_constants.APP_DIR / "backups" / f"pre-update-{stamp}.zip")
            if not self._setup_launcher(Path(installer), ["/CLOSEAPPLICATIONS"]):
                raise OSError("Setup process did not start")
        except Exception:
            self._set_state(replace(self.state, phase=UpdatePhase.ERROR, can_check=True, can_update=True))
            return
        self.app.force_quit = True
        self._quit_app()

    def _download_setup(
        self,
        asset: ReleaseAsset,
        destination: Path,
        stop_requested: Callable[[], bool],
        progress: Callable[[int, int | None], None],
    ) -> Path:
        return download_atomic(
            asset.url,
            destination,
            max_bytes=asset.size if asset.size > 0 else 1,
            expected_size=asset.size,
            stop_requested=stop_requested,
            progress=progress,
        )

    def _download_checksum(self, asset: ReleaseAsset, stop_requested: Callable[[], bool]) -> str:
        destination = self.cache_root / "checksums" / "SHA256SUMS.txt"
        download_atomic(
            asset.url,
            destination,
            max_bytes=CHECKSUM_MAX_BYTES,
            expected_size=asset.size,
            stop_requested=stop_requested,
        )
        try:
            return destination.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise DownloadError("checksum 파일을 UTF-8로 읽지 못했습니다.") from exc

    def _confirm_unsigned_update(self, release: UpdateRelease) -> bool:
        tr = getattr(self.app, "tr", None)
        fallback = (
            "v{version} 설치 파일의 SHA-256 검증이 완료되었습니다.\n\n"
            "변경 사항:\n{notes}\n\n"
            "현재 개발 빌드는 코드 서명이 없습니다. 설치 프로그램을 실행할까요?"
        )
        message = (
            tr(
                "settings.update.unsigned_confirm",
                fallback,
                version=str(release.version),
                notes=release.notes or "-",
            )
            if callable(tr)
            else fallback.format(version=release.version, notes=release.notes or "-")
        )
        answer = QMessageBox.warning(
            None,
            "ChronoFox 업데이트",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def shutdown(self) -> None:
        self._shutdown = True
        self._stop_event.set()
