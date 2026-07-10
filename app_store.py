from __future__ import annotations

from collections.abc import Callable

_MISSING = object()


class AppStore:
    """config/data 접근 단일 지점 + 변경 구독. Qt 비의존.

    F3 스펙(`planning/specs/architecture-v1.md` §3) 스켈레톤을 그대로 구현한다.
    dict는 복사·검증 없이 그대로 참조를 반환한다 — 호출부가 기존처럼
    `store.plans().append(...)` 같은 live-mutation 패턴을 쓸 수 있게 하기 위함이다.
    """

    TOPICS = ("plans", "schedules", "tasks", "alarms", "config")

    def __init__(self, config: dict, data: dict, save_config_fn: Callable[[dict], None], save_data_fn: Callable[[dict], None]) -> None:
        self._config = config
        self._data = data
        self._save_config = save_config_fn
        self._save_data = save_data_fn
        self._subs: dict[str, list[Callable[[], None]]] = {topic: [] for topic in self.TOPICS}

    # config -----------------------------------------------------------
    def get(self, key: str, default=None):
        return self._config.get(key, default)

    def set(self, key: str, value, notify_topic: str | None = "config") -> None:
        """config[key] = value. 값이 바뀌지 않으면 알림을 생략한다(S4/M6 refresh-storm 가드
        — 예: 창을 옮길 때마다 geometry set이 구독자를 깨우면 안 된다).
        ``notify_topic=None``이면 값이 바뀌어도 알리지 않는 silent set이다
        (geometry 영속 같은, 다른 창이 절대 반응하면 안 되는 쓰기용)."""
        if self._config.get(key, _MISSING) == value:
            return
        self._config[key] = value
        if notify_topic is not None:
            self.notify(notify_topic)

    # data collections (live references, setdefault 패턴 유지) ----------
    def plans(self) -> list:
        return self._data.setdefault("plans", [])

    def schedules(self) -> dict:
        return self._data.setdefault("schedules", {})

    def recurring_tasks(self) -> dict:
        return self._data.setdefault("recurring_tasks", {})

    def alarms(self) -> list:
        return self._data.setdefault("alarms", [])

    # persistence --------------------------------------------------------
    def save(self) -> None:
        self._save_config(self._config)
        self._save_data(self._data)

    # pub/sub --------------------------------------------------------------
    def subscribe(self, topic: str, callback: Callable[[], None]) -> None:
        self._subs[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[], None]) -> None:
        subs = self._subs[topic]
        if callback in subs:
            subs.remove(callback)

    def notify(self, topic: str) -> None:
        for callback in list(self._subs[topic]):
            callback()
