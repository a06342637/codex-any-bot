import time
from pathlib import Path

import pytest

from anybot.runtime import Agent
from anybot.state import Settings, Task


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr("anybot.runtime.find_codex", lambda: "fake-codex")
    current = [1000.0]
    result = Agent({"device_id": "device1", "cwd": str(tmp_path)}, root=tmp_path,
                   clock=lambda: current[0], turn_runner=lambda *args: {"kind": "success", "thread_id": "thread1"})
    result.current = current
    result.connected = True
    result.synced = True
    result.last_connected = 1000
    yield result
    result.cancel.set()
    if result.worker:
        result.worker.join(5)
    result.pool.shutdown(wait=True)
    result.store.close()


def command(agent, action, payload=None, version=1, command_id="cmd1", **extra):
    return {"id": command_id, "device_id": "device1", "version": version,
            "expires_at": agent.clock() + 60, "action": action, "payload": payload or {}, **extra}


def drain(agent):
    if agent.worker:
        agent.worker.join(5)
    while not agent.events.empty():
        agent.event(*agent.events.get_nowait())


def test_start_replay_does_not_duplicate_task(agent):
    cmd = command(agent, "start")
    agent.command(cmd)
    agent.tick()
    drain(agent)
    task = agent.task
    assert task.rounds == 1 and task.settings.thread_id == "thread1"
    agent.command(cmd)
    agent.tick()
    assert agent.task is task and task.rounds == 1


def test_deadline_stops_even_disconnected_and_after_sleep(agent):
    agent.task = Task("job", 1, Settings(hold_minutes=1), first_success_at=1000, phase="holding")
    agent.connected = False
    agent.current[0] = 3000
    agent.tick()
    assert agent.task.phase == "stopped" and agent.cancel.is_set()
    assert agent.worker is None


def test_runtime_shortening_and_interval_changes(agent):
    agent.task = Task("job", 1, Settings(hold_minutes=120), first_success_at=1000,
                      last_finished_at=1100, phase="holding")
    agent.current[0] = 1120
    agent.command(command(agent, "settings", {"interval_minutes": 5}, 2))
    assert agent.task.next_at == 1400
    agent.command(command(agent, "settings", {"hold_minutes": 1}, 3, "cmd2"))
    assert agent.task.phase == "stopped"


def test_disconnect_grace_blocks_new_turns(agent):
    agent.task = Task("job", 1, Settings(cwd=str(agent.root)), phase="holding")
    agent.connected = False
    agent.current[0] = 1061
    agent.tick()
    assert agent.worker is None


def test_stale_or_other_device_command_cannot_start(agent):
    agent.version = 5
    agent.command(command(agent, "start", version=4))
    agent.command(command(agent, "start", version=6, command_id="cmd2", device_id="other"))
    agent.command(command(agent, "start", version=6, command_id="cmd3", expires_at=999))
    assert agent.task is None


def test_restart_stays_idle_and_command_claim_survives(agent):
    cmd = command(agent, "start")
    agent.command(cmd)
    other = Agent(agent.config, root=agent.root)
    try:
        assert other.task is None
        other.command(cmd)
        assert other.task is None
    finally:
        other.pool.shutdown()
        other.store.close()


def test_cancel_during_new_session_and_no_overlap(agent):
    started = []
    def slow(binary, settings, cancel, emit):
        started.append(1)
        emit({"event": "thread", "thread_id": "new1"})
        cancel.wait(10)
        return {"kind": "cancelled", "thread_id": "new1"}
    agent.turn_runner = slow
    agent.command(command(agent, "start"))
    agent.tick()
    agent.command(command(agent, "start", version=2, command_id="double"))
    agent.command(command(agent, "stop", version=3, command_id="stop"))
    drain(agent)
    agent.tick()
    assert len(started) == 1 and agent.task.phase == "stopped"


def test_reconcile_applies_offline_changes_without_restarting(agent):
    agent.task = Task("job", 1, Settings(hold_minutes=60, thread_id="live"), first_success_at=1000, phase="holding")
    agent.current[0] = 1200
    agent.event("message", {"type": "reconcile", "version": 10, "desired": "running",
                            "settings": {"hold_minutes": 1, "interval_minutes": 5}, "stop_at": None})
    agent.tick()
    assert agent.task.phase == "stopped"
    assert agent.settings.thread_id == "live"


def test_local_shutdown_marker(agent):
    (agent.root / "stop.request").touch()
    agent.tick()
    assert agent.shutdown.is_set()


def test_reconnection_waits_for_reconciliation_before_sending(agent):
    agent.task = Task("job", 1, Settings(cwd=str(agent.root)))
    agent.event("connected", None)
    agent.tick()
    assert agent.worker is None
    agent.event("message", {"type": "reconcile", "version": 5, "desired": "stopped", "settings": agent.settings.json()})
    agent.tick()
    assert agent.task.phase == "stopped" and agent.worker is None


def test_revoked_credentials_stop_and_disable_client(agent):
    agent.event("revoked", None)
    assert agent.shutdown.is_set()
    assert agent.after_exit == "revoke"


def test_schedule_deadline_can_change_during_a_task(agent):
    agent.task = Task("job", 1, Settings(hold_minutes=120), first_success_at=1000, phase="holding")
    agent.command(command(agent, "deadline", {"stop_at": 1030}, 2))
    assert agent.task.deadline == 1030
    agent.current[0] = 1040
    agent.tick()
    assert agent.task.phase == "stopped"
