from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QListWidgetItem, QMessageBox

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:
    QAudioOutput = None
    QMediaPlayer = None

from app_constants import APP_NAME

from .alarm_dialog import AlarmEditorDialog
from .alarm_row import AlarmRow


class ClockAlarmMixin:
    """Alarm persistence, triggering, and notification behavior."""

    def current_clock_datetime(self) -> datetime:
        return datetime.now()

    AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
    WEEKDAY_LABEL_KEYS = [
        ("calendar.weekday.mon", "월"),
        ("calendar.weekday.tue", "화"),
        ("calendar.weekday.wed", "수"),
        ("calendar.weekday.thu", "목"),
        ("calendar.weekday.fri", "금"),
        ("calendar.weekday.sat", "토"),
        ("calendar.weekday.sun", "일"),
    ]

    def alarms(self) -> list[dict]:
        return self.app.store.alarms()

    def alarms_for_scheduler(self) -> list[dict]:
        """스케줄러 tick마다 정규화된 알람 목록을 돌려준다 (기존 check_alarms가 매 스캔마다
        하던 방어적 normalize_alarm 호출을 유지한다)."""
        for alarm in self.alarms():
            self.normalize_alarm(alarm)
        return self.alarms()

    def next_alarm_occurrence(self) -> datetime | None:
        """켜져 있는 알람들 중 앞으로 7일 안에 가장 먼저 울릴 시각을 돌려줍니다."""
        now = datetime.now()
        best: datetime | None = None
        for alarm in self.alarms():
            if not alarm.get("enabled", True):
                continue
            try:
                hour, minute = (int(part) for part in str(alarm.get("time", "")).split(":"))
            except ValueError:
                continue
            if alarm.get("kind") == "date":
                try:
                    day = date.fromisoformat(str(alarm.get("date", "")))
                except ValueError:
                    continue
                candidate = datetime(day.year, day.month, day.day, hour, minute)
                if candidate > now and (best is None or candidate < best):
                    best = candidate
                continue
            repeat_days = alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6])
            for offset in range(8):
                day = now.date() + timedelta(days=offset)
                if day.weekday() not in repeat_days:
                    continue
                candidate = datetime(day.year, day.month, day.day, hour, minute)
                if candidate <= now:
                    continue
                if best is None or candidate < best:
                    best = candidate
                break
        return best

    def refresh_next_alarm_label(self) -> None:
        if not hasattr(self, "next_alarm_label"):
            return
        best = self.next_alarm_occurrence()
        if best is None:
            self.next_alarm_label.setText("")
            return
        today = date.today()
        if best.date() == today:
            day_text = self.tr("detail.when.today", "오늘")
        elif best.date() == today + timedelta(days=1):
            day_text = self.tr("detail.when.tomorrow", "내일")
        else:
            key, fallback = self.WEEKDAY_LABEL_KEYS[best.weekday()]
            day_text = self.tr(key, fallback)
        self.next_alarm_label.setText(
            self.tr("clock.next_alarm", "다음 알람 · {day} {time}").format(day=day_text, time=f"{best:%H:%M}")
        )

    def normalize_alarm(self, alarm: dict) -> dict:
        alarm.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S%f"))
        alarm.setdefault("time", "07:00")
        alarm.setdefault("label", "알람")
        alarm.setdefault("enabled", True)
        alarm.setdefault("last_triggered", "")
        alarm.setdefault("kind", "repeat")
        alarm.setdefault("date", "")
        alarm.setdefault("notify_mode", "popup")
        alarm.setdefault("repeat_days", [0, 1, 2, 3, 4, 5, 6])
        alarm.setdefault("snooze_minutes", 5)
        alarm.setdefault("snoozed_until", "")
        alarm.setdefault("sound_mode", self.normalized_alert_sound_mode(str(self.app.store.get("alert_sound_mode", "default"))))
        alarm.setdefault("sound_path", str(self.app.store.get("alert_sound_path", "")))
        alarm.setdefault("sound_url", str(self.app.store.get("alert_sound_url", "")))
        return alarm

    def alarm_label_text(self, alarm: dict) -> str:
        label = str(alarm.get("label", "")).strip()
        if not label or label == "알람":
            return self.tr("alarm.default_label", "알람")
        return label

    def add_alarm(self) -> None:
        self.show_alarm_editor()

    def save_alarm_payload(self, payload: dict, alarm_id: str = "") -> None:
        if alarm_id:
            alarm = self.find_alarm(alarm_id)
            if alarm is not None:
                enabled = bool(alarm.get("enabled", True))
                alarm.update(payload)
                alarm["enabled"] = enabled
        else:
            self.alarms().append({"id": datetime.now().strftime("%Y%m%d%H%M%S%f"), **payload})
        self.app.save()
        self.app.store.notify("alarms")
        self.refresh_alarms()

    def find_alarm(self, alarm_id: str) -> dict | None:
        for alarm in self.alarms():
            if str(alarm.get("id")) == alarm_id:
                return alarm
        return None

    def edit_alarm(self, alarm_id: str) -> None:
        alarm = self.find_alarm(alarm_id)
        if alarm is None:
            return
        self.normalize_alarm(alarm)
        dialog = AlarmEditorDialog(self, alarm)
        if dialog.exec() == QDialog.Accepted:
            self.save_alarm_payload(dialog.payload(), alarm_id)

    def reset_alarm_editor(self, save: bool = True) -> None:
        self.editing_alarm_id = ""
        if save:
            self.app.save()

    def show_alarm_editor(self) -> None:
        dialog = AlarmEditorDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.save_alarm_payload(dialog.payload())

    def hide_alarm_editor(self, save: bool = True) -> None:
        if save:
            self.app.save()

    def refresh_alarm_kind_controls(self) -> None:
        return

    def refresh_alarms(self) -> None:
        if not hasattr(self, "alarm_list"):
            if hasattr(self, "clock_window") and self.clock_window:
                self.clock_window.refresh_alarms()
            return
        self.alarm_list.clear()
        changed = False
        for alarm in sorted(self.alarms(), key=lambda item: (item.get("date", ""), item.get("time", "00:00"))):
            before = dict(alarm)
            self.normalize_alarm(alarm)
            changed = changed or alarm != before
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 104))
            self.alarm_list.addItem(item)
            row = AlarmRow(self, alarm)
            self.alarm_list.setItemWidget(item, row)
        if changed:
            self.app.save()
        self.refresh_next_alarm_label()

    def set_alarm_enabled(self, alarm_id: str, enabled: bool) -> None:
        for alarm in self.alarms():
            if str(alarm.get("id")) == alarm_id:
                alarm["enabled"] = enabled
                if enabled:
                    alarm["last_triggered"] = ""
                else:
                    alarm["snoozed_until"] = ""
                break
        self.app.save()
        self.app.store.notify("alarms")
        self.refresh_alarms()

    def delete_alarm(self, alarm_id: str) -> None:
        self.app.store.alarms()[:] = [alarm for alarm in self.alarms() if str(alarm.get("id")) != alarm_id]
        if self.editing_alarm_id == alarm_id:
            self.reset_alarm_editor(save=False)
        self.app.save()
        self.app.store.notify("alarms")
        self.refresh_alarms()

    def on_scheduler_alarm_due(self, alarm: dict) -> None:
        """NotificationScheduler.on_alarm_due 콜백. 마킹은 스케줄러가 이미 끝냈으므로
        여기서는 표시 큐에 넣기만 한다 (D6 — tick()은 블로킹하지 않는다)."""
        self.normalize_alarm(alarm)
        now = self.current_clock_datetime()
        stamp = now.strftime("%H:%M")
        message = f"{stamp} {self.alarm_label_text(alarm)}"
        if not hasattr(self, "_alert_queue"):
            self._alert_queue = []
        self._alert_queue.append((alarm, message))
        self._drain_alert_queue()

    def _drain_alert_queue(self) -> None:
        """`_alert_active` 가드로 한 번에 모달 하나만 표시한다 (D6, S5)."""
        if getattr(self, "_alert_active", False):
            return
        queue = getattr(self, "_alert_queue", None)
        if not queue:
            return
        alarm, message = queue.pop(0)
        self._alert_active = True
        try:
            self.trigger_alarm(alarm, message)
        finally:
            self._alert_active = False
        self._drain_alert_queue()

    def on_scheduler_alarms_missed(self, alarms: list[dict]) -> None:
        """NotificationScheduler.on_alarms_missed 콜백. 모달 대신 트레이 요약 1건 (D3).
        스케줄러가 찍은 last_triggered 마킹을 영속화해 재시작 후 재요약을 막는다 (D4)."""
        self.app.save()
        self.app.store.notify("alarms")
        tray = getattr(self.app, "tray", None)
        message = self.format_missed_alarms_message(alarms)
        if tray is not None and tray.isVisible():
            tray.showMessage(self.app_display_name(), message, msecs=10000)
        else:
            QApplication.beep()

    def format_missed_alarms_message(self, alarms: list[dict]) -> str:
        count = len(alarms)
        labels = [f"{alarm.get('time', '')} {self.alarm_label_text(alarm)}" for alarm in alarms]
        items = ", ".join(labels[:3])
        if count > 3:
            more = self.tr("alarm.missed.more", "외 {count}건").format(count=count - 3)
            items = f"{items} {more}"
        return self.tr(
            "alarm.missed.summary",
            "절전/종료 중 놓친 알람 {count}건: {items}",
        ).format(count=count, items=items)

    def snooze_due(self, alarm: dict, now: datetime) -> bool:
        value = str(alarm.get("snoozed_until", ""))
        if not value:
            return False
        try:
            snoozed_until = datetime.fromisoformat(value)
        except ValueError:
            alarm["snoozed_until"] = ""
            return False
        if snoozed_until.tzinfo is None and now.tzinfo is not None:
            now = now.astimezone().replace(tzinfo=None)
        elif snoozed_until.tzinfo is not None and now.tzinfo is None:
            snoozed_until = snoozed_until.astimezone().replace(tzinfo=None)
        return now >= snoozed_until

    def trigger_alarm(self, alarm: dict, message: str) -> None:
        alarm["last_triggered"] = self.current_clock_datetime().date().isoformat()
        self.app.save()
        self.active_alert_alarm = alarm
        action = "stop"
        try:
            action = self.show_alert(message, allow_snooze=True, notify_mode=alarm.get("notify_mode", "popup"))
        finally:
            self.active_alert_alarm = None
        if action == "snooze":
            minutes = max(1, int(alarm.get("snooze_minutes", 5)))
            alarm["snoozed_until"] = (self.current_clock_datetime() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        else:
            alarm["snoozed_until"] = ""
            if alarm.get("kind") == "date":
                alarm["enabled"] = False
        self.app.save()
        self.app.store.notify("alarms")
        self.refresh_alarms()

    def show_alert(self, message: str, allow_snooze: bool = False, notify_mode: str = "popup") -> str:
        self.play_alert_sound(getattr(self, "active_alert_alarm", None))
        if notify_mode == "sound":
            QTimer.singleShot(15000, self.stop_alert_sound)
            return "stop"
        if notify_mode == "windows":
            self.show_windows_notification(message)
            QTimer.singleShot(15000, self.stop_alert_sound)
            return "stop"
        self.raise_()
        self.activateWindow()
        if allow_snooze:
            box = QMessageBox(self if self.isVisible() else None)
            box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
            box.setWindowTitle(APP_NAME)
            box.setText(message)
            stop_button = box.addButton(self.tr("alarm.action.stop", "정지"), QMessageBox.AcceptRole)
            snooze_button = box.addButton(self.tr("alarm.action.snooze", "다시 울림"), QMessageBox.ActionRole)
            box.setDefaultButton(stop_button)
            box.exec()
            clicked = box.clickedButton()
            result = "snooze" if clicked == snooze_button else "stop"
        else:
            box = QMessageBox(self if self.isVisible() else None)
            box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
            box.setWindowTitle(APP_NAME)
            box.setText(message)
            box.setIcon(QMessageBox.Information)
            box.exec()
            result = "stop"
        self.stop_alert_sound()
        return result

    def show_windows_notification(self, message: str) -> None:
        tray = getattr(self.app, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage(APP_NAME, message, msecs=7000)
        else:
            box = QMessageBox(self if self.isVisible() else None)
            box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
            box.setWindowTitle(APP_NAME)
            box.setText(message)
            box.setIcon(QMessageBox.Information)
            box.exec()

    def play_alert_sound(self, alarm: dict | None = None) -> None:
        mode = self.alert_sound_mode(alarm)
        if mode == "local":
            path_text = self.alert_sound_path(alarm)
            path = Path(path_text)
            if path.is_file() and path.suffix.lower() in self.AUDIO_SUFFIXES and QMediaPlayer is not None and QAudioOutput is not None:
                if self.alert_player is None:
                    self.alert_player = QMediaPlayer(self)
                    self.alert_audio = QAudioOutput(self)
                    self.alert_audio.setVolume(0.85)
                    self.alert_player.setAudioOutput(self.alert_audio)
                self.alert_player.setSource(QUrl.fromLocalFile(str(path)))
                self.alert_player.play()
                return
        elif mode == "url":
            url = self.alert_sound_url(alarm)
            if self.is_supported_alert_url(url):
                QDesktopServices.openUrl(QUrl(url))
                return
        QApplication.beep()

    def alert_sound_mode(self, alarm: dict | None = None) -> str:
        if alarm is None:
            return self.normalized_alert_sound_mode(str(self.app.store.get("alert_sound_mode", "default")))
        mode = str(alarm.get("sound_mode", "")).strip()
        if not mode:
            mode = str(self.app.store.get("alert_sound_mode", "default"))
        return self.normalized_alert_sound_mode(mode)

    def alert_sound_path(self, alarm: dict | None = None) -> str:
        if alarm is None:
            return str(self.app.store.get("alert_sound_path", "")).strip()
        path = str(alarm.get("sound_path", "")).strip()
        return path or str(self.app.store.get("alert_sound_path", "")).strip()

    def alert_sound_url(self, alarm: dict | None = None) -> str:
        if alarm is None:
            return str(self.app.store.get("alert_sound_url", "")).strip()
        url = str(alarm.get("sound_url", "")).strip()
        return url or str(self.app.store.get("alert_sound_url", "")).strip()

    def normalized_alert_sound_mode(self, mode: str) -> str:
        if mode == "youtube":
            return "url"
        return mode if mode in {"default", "local", "url"} else "default"

    def is_supported_alert_url(self, url: str) -> bool:
        parsed = urlparse(url.strip())
        return parsed.scheme == "https" and bool(parsed.hostname)

    def stop_alert_sound(self) -> None:
        if self.alert_player is not None:
            self.alert_player.stop()
