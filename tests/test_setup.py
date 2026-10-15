import json
from types import SimpleNamespace

import pytest

from anybot import cli
from anybot.storage import Store, load_config


def test_interactive_setup_posts_credentials_but_only_saves_device_token(tmp_path, monkeypatch, capsys):
    inputs = iter(["https://relay.example.com", "42"])
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "owner-bot-secret")
    monkeypatch.setattr(cli, "diagnose", lambda: {"logged_in": True})
    posts = []
    def response(url, body, headers=None):
        posts.append((url, body))
        return json.dumps({"device_id": "device1", "token": "a" * 64, "protocol": 1,
                           "bot_token": "must-not-be-persisted"}).encode()
    monkeypatch.setattr(cli, "fetch", response)
    cli.setup(SimpleNamespace(server=None, name="My computer", cwd=str(tmp_path)), tmp_path)
    assert posts[0][0] == "https://relay.example.com/v1/enroll"
    assert posts[0][1]["bot_token"] == "owner-bot-secret"
    assert posts[0][1]["user_id"] == "42"
    config = load_config(tmp_path)
    assert config["token"] == "a" * 64
    assert "bot_token" not in config
    assert "owner-bot-secret" not in capsys.readouterr().out
    for path in tmp_path.iterdir():
        if path.is_file():
            assert b"owner-bot-secret" not in path.read_bytes()


def test_prefilled_server_only_asks_for_token_and_id(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "42")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "token")
    calls = []
    monkeypatch.setattr(cli, "bind", lambda *args: calls.append(args))
    cli.setup(SimpleNamespace(server="https://relay.example.com", name="Mac", cwd=str(tmp_path)), tmp_path)
    assert len(prompts) == 1 and "ID" in prompts[0]
    assert calls[0][-1] == {"bot_token": "token", "user_id": "42"}


def test_setup_refuses_pipe_instead_of_echoing_a_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(RuntimeError, match="交互终端"):
        cli.setup(SimpleNamespace(), tmp_path)


def test_bad_response_does_not_write_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "diagnose", lambda: {"logged_in": True})
    monkeypatch.setattr(cli, "fetch", lambda *args: b'{"token":"bad"}')
    with pytest.raises(RuntimeError, match="响应"):
        cli.bind(tmp_path, "https://relay.example.com", "A", str(tmp_path), {"bot_token": "secret", "user_id": "42"})
    assert not (tmp_path / "config.json").exists()


def test_credential_requests_do_not_follow_redirects():
    assert cli.NoCredentialRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example") is None


def test_wait_online_requires_a_fresh_synced_status(tmp_path):
    store = Store(tmp_path)
    store.put("last_state", {"connected": True, "synced": True, "time": cli.time.time()})
    store.close()
    assert cli.wait_online(tmp_path, 1)


def test_forget_only_uses_per_device_credentials(tmp_path, monkeypatch):
    from anybot.storage import save_config
    save_config({"server": "https://relay.example.com", "device_id": "d1", "token": "device-token"}, tmp_path)
    calls = []
    monkeypatch.setattr(cli, "fetch", lambda *args: calls.append(args) or b'{"removed":true}')
    cli.forget(tmp_path)
    assert calls[0] == ("https://relay.example.com/v1/unenroll", {}, {"Authorization": "Bearer device-token", "X-Device-ID": "d1"})


def test_stop_local_invalidates_previous_online_status(tmp_path):
    store = Store(tmp_path)
    store.put("last_state", {"connected": True, "synced": True, "time": cli.time.time()})
    store.close()
    cli.stop_local(tmp_path)
    store = Store(tmp_path)
    state = store.get("last_state")
    store.close()
    assert not state["connected"] and not state["synced"]


def test_background_run_after_uninstall_does_not_recreate_data(tmp_path, monkeypatch):
    missing = tmp_path / "codex-any-bot"
    monkeypatch.setattr(cli, "data_dir", lambda: missing)
    assert cli.main(["run"]) == 0
    assert not missing.exists()
