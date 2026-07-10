from __future__ import annotations

import pytest

from app_store import AppStore


def make_store(config=None, data=None, save_config_fn=None, save_data_fn=None):
    config = {} if config is None else config
    data = {} if data is None else data
    calls: dict[str, list] = {"config": [], "data": []}

    def default_save_config(cfg):
        calls["config"].append(cfg)

    def default_save_data(dat):
        calls["data"].append(dat)

    store = AppStore(
        config,
        data,
        save_config_fn or default_save_config,
        save_data_fn or default_save_data,
    )
    return store, calls


def test_get_returns_config_value_or_default():
    store, _ = make_store(config={"language": "ko"})
    assert store.get("language") == "ko"
    assert store.get("missing", "fallback") == "fallback"
    assert store.get("missing") is None


def test_set_updates_config_and_fires_notify():
    store, _ = make_store(config={"language": "ko"})
    seen = []
    store.subscribe("config", lambda: seen.append(store.get("language")))

    store.set("language", "en")

    assert store.get("language") == "en"
    assert seen == ["en"]


def test_set_with_explicit_topic_notifies_that_topic_only():
    store, _ = make_store()
    config_calls = []
    plan_calls = []
    store.subscribe("config", lambda: config_calls.append(1))
    store.subscribe("plans", lambda: plan_calls.append(1))

    store.set("some_key", "value", notify_topic="plans")

    assert plan_calls == [1]
    assert config_calls == []


# S4/M6: refresh-storm 가드 — 값이 안 바뀌면 알리지 않고, notify_topic=None이면
# 값이 바뀌어도 절대 알리지 않는다(예: 창 이동마다 geometry set이 구독자를 깨우면 안 됨).
def test_set_skips_notify_when_value_unchanged():
    store, _ = make_store(config={"calendar_geometry": "980x620+180+40"})
    seen = []
    store.subscribe("config", lambda: seen.append(1))

    store.set("calendar_geometry", "980x620+180+40")

    assert store.get("calendar_geometry") == "980x620+180+40"
    assert seen == []


def test_set_still_notifies_when_value_actually_changes_after_unchanged_set():
    store, _ = make_store(config={"calendar_geometry": "980x620+180+40"})
    seen = []
    store.subscribe("config", lambda: seen.append(1))

    store.set("calendar_geometry", "980x620+180+40")  # no-op, no notify
    store.set("calendar_geometry", "900x600+100+40")  # real change, notify

    assert seen == [1]


def test_set_with_notify_topic_none_is_silent_even_when_value_changes():
    store, _ = make_store(config={"calendar_geometry": "980x620+180+40"})
    seen = []
    store.subscribe("config", lambda: seen.append(1))

    store.set("calendar_geometry", "900x600+100+40", notify_topic=None)

    assert store.get("calendar_geometry") == "900x600+100+40"
    assert seen == []


def test_subscribe_and_unsubscribe_lifecycle():
    store, _ = make_store()
    calls = []

    def callback():
        calls.append(1)

    store.subscribe("plans", callback)
    store.notify("plans")
    assert calls == [1]

    store.unsubscribe("plans", callback)
    store.notify("plans")
    assert calls == [1]  # unchanged after unsubscribe


def test_unsubscribe_unknown_callback_is_noop():
    store, _ = make_store()

    def callback():
        pass

    # Never subscribed — must not raise.
    store.unsubscribe("plans", callback)


def test_save_calls_both_injected_save_functions():
    config = {"language": "ko"}
    data = {"plans": []}
    store, calls = make_store(config=config, data=data)

    store.save()

    assert calls["config"] == [config]
    assert calls["data"] == [data]


def test_unknown_topic_raises_key_error_on_subscribe():
    store, _ = make_store()
    with pytest.raises(KeyError):
        store.subscribe("not_a_topic", lambda: None)


def test_unknown_topic_raises_key_error_on_unsubscribe():
    store, _ = make_store()
    with pytest.raises(KeyError):
        store.unsubscribe("not_a_topic", lambda: None)


def test_unknown_topic_raises_key_error_on_notify():
    store, _ = make_store()
    with pytest.raises(KeyError):
        store.notify("not_a_topic")


@pytest.mark.parametrize(
    ("accessor", "key"),
    [
        ("plans", "plans"),
        ("schedules", "schedules"),
        ("recurring_tasks", "recurring_tasks"),
        ("alarms", "alarms"),
    ],
)
def test_collection_accessors_return_live_refs(accessor, key):
    data: dict = {}
    store, _ = make_store(data=data)

    collection = getattr(store, accessor)()
    if isinstance(collection, list):
        collection.append("marker")
        assert data[key] == ["marker"]
    else:
        collection["marker"] = True
        assert data[key] == {"marker": True}

    # Calling the accessor again must return the same live object, not a copy.
    assert getattr(store, accessor)() is collection
