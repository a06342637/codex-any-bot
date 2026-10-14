import pytest

from anybot.state import Settings, Task


def test_holding_begins_on_first_success_and_never_renews():
    task = Task("one", 1, Settings(hold_minutes=30, interval_minutes=2))
    task.finish(100, "failed")
    assert task.first_success_at is None and task.deadline is None
    assert task.finish(200, "success")
    assert task.deadline == 2000
    assert not task.finish(500, "success")
    assert task.deadline == 2000 and task.next_at == 620
    assert not task.expired(1999)
    assert task.expired(2000)


def test_change_duration_uses_original_start_and_earliest_stop():
    task = Task("one", 1, Settings(hold_minutes=120), stop_at=5000)
    task.finish(1000, "success")
    assert task.deadline == 5000
    task.settings.hold_minutes = 30
    assert task.deadline == 2800
    task.settings.hold_minutes = 1
    assert task.expired(1060)
    task.settings.hold_minutes = None
    assert task.deadline == 5000


def test_retry_backoff_and_pauses():
    task = Task("one", 1, Settings())
    for i, delay in enumerate((5, 10, 20, 40, 60, 60)):
        task.finish(i * 100, "failed")
        assert task.next_at == i * 100 + delay
    task.finish(1000, "locked")
    assert task.next_at == 1060
    task.finish(1100, "auth")
    assert task.phase == "paused"


@pytest.mark.parametrize("value", [0, -1, 1.5, "1", True, 525601])
def test_invalid_minutes(value):
    with pytest.raises(ValueError):
        Settings.parse({"hold_minutes": value})
    with pytest.raises(ValueError):
        Settings.parse({"interval_minutes": value})


def test_independent_machine_settings():
    win = Task("win", 1, Settings(hold_minutes=30, interval_minutes=1))
    mac = Task("mac", 1, Settings(hold_minutes=120, interval_minutes=5))
    win.finish(1000, "success")
    mac.finish(1000, "success")
    assert (win.deadline, win.next_at) == (2800, 1060)
    assert (mac.deadline, mac.next_at) == (8200, 1300)
