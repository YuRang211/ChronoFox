from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSize, QTimer, QUrl
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
        return self.app.data.setdefault("alarms", [])

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
        alarm.setdefault("sound_mode", self.normalized_alert_sound_mode(str(self.app.config.get("alert_sound_mode", "default"))))
        alarm.setdefault("sound_path", str(self.app.config.get("alert_sound_path", "")))
        alarm.setdefault("sound_url", str(self.app.config.get("alert_sound_url", "")))
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
        self.refresh_alarms()

    def delete_alarm(self, alarm_id: str) -> None:
        self.app.data["alarms"] = [alarm for alarm in self.alarms() if str(alarm.get("id")) != alarm_id]
        if self.editing_alarm_id == alarm_id:
            self.reset_alarm_editor(save=False)
        self.app.save()
        self.refresh_alarms()

    def check_alarms(self) -> None:
        now = self.current_clock_datetime()
        second_key = now.strftime("%Y-%m-%d %H:%M:%S")
        if second_key == self.last_alarm_check_second:
            return
        self.last_alarm_check_second = second_key
        stamp = now.strftime("%H:%M")
        today = now.date().isoformat()
        weekday = now.weekday()
        for alarm in self.alarms():
            self.normalize_alarm(alarm)
            if not alarm.get("enabled"):
                continue
            if self.snooze_due(alarm, now):
                alarm["snoozed_until"] = ""
                self.trigger_alarm(alarm, f"{stamp} {self.alarm_label_text(alarm)}")
                break
            if now.second != 0:
                continue
            if alarm.get("kind") == "date":
                if alarm.get("date") != today:
                    continue
            elif weekday not in alarm.get("repeat_days", []):
                continue
            if alarm.get("time") != stamp or alarm.get("last_triggered") == today:
                continue
            self.trigger_alarm(alarm, f"{stamp} {self.alarm_label_text(alarm)}")
            break

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
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(message)
            stop_button = box.addButton(self.tr("alarm.action.stop", "정지"), QMessageBox.AcceptRole)
            snooze_button = box.addButton(self.tr("alarm.action.snooze", "다시 울림"), QMessageBox.ActionRole)
            box.setDefaultButton(stop_button)
            box.exec()
            clicked = box.clickedButton()
            result = "snooze" if clicked == snooze_button else "stop"
        else:
            QMessageBox.information(self, APP_NAME, message)
            result = "stop"
        self.stop_alert_sound()
        return result

    def show_windows_notification(self, message: str) -> None:
        tray = getattr(self.app, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage(APP_NAME, message, msecs=7000)
        else:
            QMessageBox.information(self, APP_NAME, message)

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
            return self.normalized_alert_sound_mode(str(self.app.config.get("alert_sound_mode", "default")))
        mode = str(alarm.get("sound_mode", "")).strip()
        if not mode:
            mode = str(self.app.config.get("alert_sound_mode", "default"))
        return self.normalized_alert_sound_mode(mode)

    def alert_sound_path(self, alarm: dict | None = None) -> str:
        if alarm is None:
            return str(self.app.config.get("alert_sound_path", "")).strip()
        path = str(alarm.get("sound_path", "")).strip()
        return path or str(self.app.config.get("alert_sound_path", "")).strip()

    def alert_sound_url(self, alarm: dict | None = None) -> str:
        if alarm is None:
            return str(self.app.config.get("alert_sound_url", "")).strip()
        url = str(alarm.get("sound_url", "")).strip()
        return url or str(self.app.config.get("alert_sound_url", "")).strip()

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
