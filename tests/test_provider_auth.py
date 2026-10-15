from anybot import codex


def test_custom_provider_with_own_auth_does_not_require_openai_login(tmp_path):
    (tmp_path / "config.toml").write_text('model_provider="custom"\n[model_providers.custom]\nbase_url="https://provider.example/v1"\nrequires_openai_auth=false\nexperimental_bearer_token="private-provider-key"\n')
    result = codex.provider_auth_status(tmp_path)
    assert result["ready"] and not result["requires_openai_login"]
    assert "private-provider-key" not in str(result)
    assert "provider.example" not in str(result)


def test_openai_or_explicit_openai_auth_still_requires_login(tmp_path):
    assert codex.provider_auth_status(tmp_path)["requires_openai_login"]
    (tmp_path / "config.toml").write_text('model_provider="custom"\n[model_providers.custom]\nrequires_openai_auth=true\n')
    assert codex.provider_auth_status(tmp_path)["requires_openai_login"]


def test_missing_custom_env_key_reports_its_name_without_a_secret(tmp_path, monkeypatch):
    (tmp_path / "config.toml").write_text('model_provider="custom"\n[model_providers.custom]\nbase_url="https://example.invalid"\nenv_key="ANYBOT_TEST_PROVIDER_KEY"\n')
    monkeypatch.delenv("ANYBOT_TEST_PROVIDER_KEY", raising=False)
    assert not codex.provider_auth_status(tmp_path)["ready"]
    monkeypatch.setenv("ANYBOT_TEST_PROVIDER_KEY", "private-value")
    result = codex.provider_auth_status(tmp_path)
    assert result["ready"] and "private-value" not in str(result)


def test_selected_profile_controls_provider_auth(tmp_path):
    (tmp_path / "config.toml").write_text('profile="work"\n[profiles.work]\nmodel_provider="custom"\n[model_providers.custom]\nrequires_openai_auth=false\n')
    assert codex.provider_auth_status(tmp_path)["ready"]


def test_invalid_config_does_not_allow_binding(tmp_path, monkeypatch):
    from types import SimpleNamespace
    (tmp_path / "config.toml").write_text('invalid = [')
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex, "find_codex", lambda: "codex")
    monkeypatch.setattr(codex.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="version"))
    assert not codex.diagnose()["ready"]
