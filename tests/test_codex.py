import pytest

from anybot import codex


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


def test_session_metadata_reads_only_metadata_and_verifies_the_id(monkeypatch):
    calls = []
    monkeypatch.setattr(codex, "rpc", lambda *args: calls.append(args) or {"thread": {"id": "selected", "name": "My session"}})
    assert codex.thread_info("selected") == {"id": "selected", "name": "My session"}
    assert calls == [("thread/read", {"threadId": "selected", "includeTurns": False})]


def test_delete_uses_official_api_for_only_the_explicit_target(monkeypatch):
    calls = []
    monkeypatch.setattr(codex, "rpc", lambda *args: calls.append(args) or {})
    codex.delete_thread("selected")
    assert calls == [("thread/delete", {"threadId": "selected"})]
