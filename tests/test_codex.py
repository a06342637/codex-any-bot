import json
import sys
import threading
import time

import pytest

from anybot import codex
from anybot.state import Settings


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    script = tmp_path / "fake.py"
    real = codex.ProcessTree
    monkeypatch.setattr(codex, "ProcessTree", lambda args, cwd=None: real([sys.executable, str(script)], cwd))
    return script


@pytest.mark.parametrize("body,expected", [
    ("print('{\"type\":\"thread.started\",\"thread_id\":\"t1\"}'); print('{\"type\":\"turn.completed\"}')", "success"),
    ("print('looks like content, but not a completed event')", "failed"),
    ("print('{\"type\":\"turn.completed\"}'); raise SystemExit(1)", "failed"),
    ("print('{\"type\":\"turn.failed\",\"error\":\"already has an active writer\"}')", "locked"),
    ("print('{\"type\":\"turn.failed\",\"error\":\"401 unauthorized\"}')", "auth"),
])
def test_only_completed_event_and_zero_exit_count(fake_cli, body, expected):
    fake_cli.write_text("import sys\nsys.stdin.read()\n" + body, encoding="utf-8")
    result = codex.run_turn("fake", Settings(thread_id="t1"), threading.Event(), lambda e: None)
    assert result["kind"] == expected


def test_stop_kills_child_process_tree(fake_cli, tmp_path):
    marker = tmp_path / "child-heartbeat"
    child = "import time,pathlib; p=pathlib.Path(" + repr(str(marker)) + ");\nwhile True: p.write_text(str(time.time())); time.sleep(0.05)"
    fake_cli.write_text("import sys,subprocess,time\nsys.stdin.read()\nsubprocess.Popen([sys.executable,'-c'," + repr(child) + "])\nprint('{\"type\":\"thread.started\",\"thread_id\":\"new\"}',flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    cancel = threading.Event()
    results = []
    thread = threading.Thread(target=lambda: results.append(codex.run_turn("fake", Settings(), cancel, lambda e: None)))
    thread.start()
    until = time.time() + 10
    while not marker.exists() and time.time() < until:
        time.sleep(0.05)
    assert marker.exists()
    cancel.set()
    thread.join(10)
    assert not thread.is_alive() and results[0]["kind"] == "cancelled"
    previous = marker.read_text()
    time.sleep(0.3)
    assert marker.read_text() == previous


def test_darwin_exited_group_permission_error_is_harmless(monkeypatch):
    def denied(*args):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(codex.os, "killpg", denied, raising=False)
    monkeypatch.setattr(codex, "group_has_live_members", lambda group: False)
    codex.signal_group(1234, 9)


def test_permission_error_with_live_children_is_not_hidden(monkeypatch):
    def denied(*args):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(codex.os, "killpg", denied, raising=False)
    monkeypatch.setattr(codex, "group_has_live_members", lambda group: True)
    with pytest.raises(PermissionError):
        codex.signal_group(1234, 9)


def test_process_group_inspection_ignores_zombies_and_other_groups(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(codex.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="1 99 S\n2 1234 Z+\n"))
    assert not codex.group_has_live_members(1234)
    monkeypatch.setattr(codex.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="3 1234 S+\n"))
    assert codex.group_has_live_members(1234)
