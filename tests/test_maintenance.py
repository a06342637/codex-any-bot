import hashlib
import json
from types import SimpleNamespace

import pytest

from anybot import cli


def test_update_verifies_installer_before_execution(monkeypatch, tmp_path):
    installer = b"installer"
    manifest = {"version": "v0.1.0", "files": {"install.ps1": {"sha256": "0" * 64}, "install.sh": {"sha256": "0" * 64}}}
    monkeypatch.setattr(cli, "fetch", lambda url: json.dumps(manifest).encode() if url.endswith("manifest.json") else installer)
    called = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: called.append(a))
    with pytest.raises(RuntimeError, match="checksum"):
        cli.maintenance("update")
    assert not called


def test_failed_installer_is_reported_for_previous_version_restart(monkeypatch, tmp_path):
    installer = b"installer"
    digest = hashlib.sha256(installer).hexdigest()
    manifest = {"version": "v0.1.0", "files": {"install.ps1": {"sha256": digest}, "install.sh": {"sha256": digest}}}
    monkeypatch.setattr(cli, "fetch", lambda url: json.dumps(manifest).encode() if url.endswith("manifest.json") else installer)
    monkeypatch.setattr(cli, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(RuntimeError, match="retained previous"):
        cli.maintenance("update")
    assert list((tmp_path / "cache").iterdir()) == []
