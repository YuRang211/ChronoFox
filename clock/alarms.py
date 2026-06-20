from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

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

    def alarms(self) -> list[dict]:
        return self.app.data.setdefault("alarms", [])

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
        return alarm

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
                self.trigger_alarm(alarm, f"{stamp} {alarm.get('label') or '알람'}")
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
            self.trigger_alarm(alarm, f"{stamp} {alarm.get('label') or '알람'}")
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
        action = self.show_alert(message, allow_snooze=True, notify_mode=alarm.get("notify_mode", "popup"))
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
        self.play_alert_sound()
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
            stop_button = box.addButton("정지", QMessageBox.AcceptRole)
            snooze_button = box.addButton("다시 울림", QMessageBox.ActionRole)
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

    def play_alert_sound(self) -> None:
        mode = self.app.config.get("alert_sound_mode", "default")
        if mode == "local":
            path = Path(self.app.config.get("alert_sound_path", ""))
            if path.exists() and QMediaPlayer is not None and QAudioOutput is not None:
                if self.alert_player is None:
                    self.alert_player = QMediaPlayer(self)
                    self.alert_audio = QAudioOutput(self)
                    self.alert_audio.setVolume(0.85)
                    self.alert_player.setAudioOutput(self.alert_audio)
                self.alert_player.setSource(QUrl.fromLocalFile(str(path)))
                self.alert_player.play()
                return
        elif mode in {"youtube", "url"}:
            url = self.app.config.get("alert_sound_url", "").strip()
            if url:
                QDesktopServices.openUrl(QUrl(url))
        QApplication.beep()

    def stop_alert_sound(self) -> None:
        if self.alert_player is not None:
            self.alert_player.stop()
