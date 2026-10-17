import time
from pathlib import Path

import pytest

from anybot.runtime import Agent
from anybot.state import Settings, Task


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr("anybot.runtime.find_codex", lambda: "fake-codex")
    monkeypatch.setattr("anybot.runtime.thread_info", lambda tid: {"id": tid, "name": "Test session"})
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


def test_failed_reconnect_attempts_do_not_extend_offline_grace(agent):
    agent.task = Task("job", 1, Settings(cwd=str(agent.root)), phase="holding")
    agent.event("disconnected", None)
    agent.current[0] = 1030
    agent.event("disconnected", None)  # failed TCP attempt, not a new successful connection
    agent.current[0] = 1065
    agent.event("disconnected", None)
    agent.tick()
    assert agent.last_connected == 1000
    assert agent.worker is None


def test_network_send_does_not_block_the_task_loop(agent):
    class UnavailableSocket:
        def send(self, message):
            raise AssertionError("Task loop must enqueue, not perform socket I/O")
    agent.ws = UnavailableSocket()
    agent.send({"event": "status"})
    assert agent.connected


def test_relative_workspace_is_rejected(agent, monkeypatch):
    monkeypatch.chdir(agent.root)
    agent.command(command(agent, "start", {"settings": {"cwd": "."}}))
    assert agent.task is None


def test_late_close_from_old_connection_cannot_disconnect_new_one(agent):
    old, new = object(), object()
    agent.active_socket = old
    agent.ws = new
    agent.event("transport", (new, "connected", None))
    agent.event("transport", (old, "disconnected", None))
    assert agent.connected and agent.active_socket is new


def test_expiry_is_processed_while_sender_is_blocked(agent):
    import threading
    entered, release = threading.Event(), threading.Event()
    class SlowSocket:
        def send(self, message):
            entered.set()
            release.wait(5)
        def close(self):
            release.set()
    agent.ws = SlowSocket()
    sender = threading.Thread(target=agent.sender, daemon=True)
    sender.start()
    try:
        agent.send({"event": "status"})
        assert entered.wait(2)
        agent.task = Task("job", 1, Settings(hold_minutes=1), first_success_at=1000, phase="holding")
        agent.current[0] = 1065
        agent.tick()
        assert agent.task.phase == "stopped" and agent.cancel.is_set()
    finally:
        agent.shutdown.set()
        release.set()
        sender.join(2)


def test_agent_startup_cannot_recreate_a_directory_removed_by_uninstall(tmp_path):
    missing = tmp_path / "codex-any-bot"
    with pytest.raises(FileNotFoundError):
        Agent({"device_id": "device1"}, root=missing)
    assert not missing.exists()


def test_attempt_and_retry_counters_survive_a_success_without_extending_deadline(agent):
    kinds = iter(["failed", "failed", "success", "success"])
    agent.turn_runner = lambda *args: {"kind": next(kinds), "thread_id": "thread1"}
    agent.command(command(agent, "start", {"settings": {"hold_minutes": 10}}))
    for attempt in range(1, 5):
        agent.current[0] = max(agent.current[0], agent.task.next_at)
        agent.tick()
        drain(agent)
        assert agent.task.attempts == attempt
    assert agent.task.retry_count == 2
    assert agent.task.rounds == 2 and agent.task.failures == 0
    assert agent.task.reason == ""
    assert agent.task.first_success_at == 1000
    assert agent.task.deadline == 1600


def test_running_status_is_published_every_five_seconds(agent):
    agent.task = Task("job", 1, Settings(), phase="running", attempts=3, retry_count=2)
    agent.publish()
    agent.current[0] += 5
    agent.tick()
    state = agent.store.get("last_state")
    assert state["time"] == 1005
    assert state["task"]["attempts"] == 3 and state["task"]["retry_count"] == 2


def test_selected_session_name_and_id_are_used_for_execution(agent):
    received = []
    agent.turn_runner = lambda binary, setting, *args: received.append((setting.thread_id, setting.thread_name)) or {"kind": "success", "thread_id": setting.thread_id}
    agent.command(command(agent, "settings", {"thread_id": "selected", "thread_name": "My project"}))
    agent.command(command(agent, "start", version=2, command_id="start"))
    agent.tick()
    drain(agent)
    assert received == [("selected", "My project")]
    assert agent.task.settings.thread_name == "My project"


def test_late_metadata_cannot_rename_another_selected_session(agent):
    agent.settings = Settings(thread_id="new", thread_name=None)
    agent.event("thread_info", {"id": "old", "name": "Wrong session"})
    assert agent.settings.thread_name is None
    agent.event("thread_info", {"id": "new", "name": "Correct session"})
    assert agent.settings.thread_name == "Correct session"


def test_delete_session_clears_selection_only_after_success(agent, monkeypatch):
    calls = []
    monkeypatch.setattr("anybot.runtime.delete_thread", lambda tid: calls.append(tid))
    monkeypatch.setattr(agent.pool, "submit", lambda work: work())
    agent.settings = Settings(thread_id="chosen", thread_name="Chosen")
    agent.task = Task("old", 1, Settings(thread_id="chosen", thread_name="Chosen"), phase="stopped")
    agent.command(command(agent, "delete_session", {"thread_id": "chosen"}, command_id="delete"))
    assert agent.settings.thread_id == "chosen" and agent.session_operation
    drain(agent)
    assert calls == ["chosen"]
    assert agent.settings.thread_id is None and agent.settings.thread_name is None
    assert agent.task is None and not agent.session_operation
    agent.command(command(agent, "delete_session", {"thread_id": "chosen"}, command_id="delete"))
    assert calls == ["chosen"]


def test_failed_delete_retains_selection_and_running_task_cannot_be_deleted(agent, monkeypatch):
    def fail(tid):
        raise RuntimeError("delete failed")
    monkeypatch.setattr("anybot.runtime.delete_thread", fail)
    monkeypatch.setattr(agent.pool, "submit", lambda work: work())
    agent.settings = Settings(thread_id="chosen", thread_name="Chosen")
    agent.command(command(agent, "delete_session", {"thread_id": "chosen"}))
    drain(agent)
    assert agent.settings.thread_id == "chosen" and not agent.session_operation
    agent.task = Task("running", 1, agent.settings, phase="running")
    agent.command(command(agent, "delete_session", {"thread_id": "chosen"}, version=2, command_id="delete-running"))
    assert agent.task.phase == "running" and not agent.session_operation
    assert not agent.store.claim("delete-running")["ok"]


def test_start_and_update_wait_for_delete_to_finish(agent):
    agent.session_operation = True
    agent.command(command(agent, "start"))
    agent.command(command(agent, "update", command_id="update"))
    assert agent.task is None and agent.after_exit is None


def test_late_old_task_progress_cannot_replace_current_selection(agent):
    agent.settings = Settings(thread_id="selected-b", thread_name="B")
    agent.task = Task("old", 1, Settings(thread_id="old-a", thread_name="A"), phase="stopped")
    agent.event("progress", ("old", {"thread_id": "old-a"}))
    assert agent.settings.thread_id == "selected-b" and agent.settings.thread_name == "B"
    assert agent.task.settings.thread_name == "A"


def test_queued_delete_cannot_execute_after_its_deadline(agent, monkeypatch):
    pending = []
    deleted = []
    monkeypatch.setattr(agent.pool, "submit", lambda work: pending.append(work))
    monkeypatch.setattr("anybot.runtime.delete_thread", lambda tid: deleted.append(tid))
    agent.command(command(agent, "delete_session", {"thread_id": "chosen"}))
    agent.current[0] += 61
    pending[0]()
    drain(agent)
    assert not deleted and not agent.session_operation
