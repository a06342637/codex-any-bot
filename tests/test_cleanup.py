from anybot.cleanup import REPOSITORY, cleanup_legacy


def test_cleans_identified_legacy_downloads_and_scripts(tmp_path):
    stage = tmp_path / ("codex-any-bot-" + "a" * 32)
    stage.mkdir()
    (stage / "codex-any-bot-windows-x64.zip").write_bytes(b"download")
    update = tmp_path / "anybot-update-abcdef12"
    update.mkdir()
    (update / "install.ps1").write_text("$root='app'; $repo='" + REPOSITORY + "'")
    bootstrap = tmp_path / ("anybot-" + "b" * 32 + ".ps1")
    bootstrap.write_text("$root='app'; $repo='" + REPOSITORY + "'")
    count, errors = cleanup_legacy(tmp_path)
    assert count == 3 and errors == []
    assert list(tmp_path.iterdir()) == []


def test_never_deletes_other_temp_files_or_user_notes(tmp_path):
    unrelated = tmp_path / "anybot-update-unrelated"
    unrelated.mkdir()
    (unrelated / "install.sh").write_text("echo unrelated")
    modified = tmp_path / ("codex-any-bot-" + "a" * 32)
    modified.mkdir()
    (modified / "codex-any-bot-windows-x64.zip").write_bytes(b"archive")
    (modified / "my-notes.txt").write_text("keep")
    (tmp_path / "something.txt").write_text("keep")
    assert cleanup_legacy(tmp_path) == (0, [])
    assert (modified / "my-notes.txt").read_text() == "keep"
    assert unrelated.exists()


def test_skips_symlink_targets(tmp_path):
    import pytest
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "codex-any-bot-windows-x64.zip").write_text("keep")
    link = tmp_path / ("codex-any-bot-" + "c" * 32)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable for this Windows user")
    cleanup_legacy(tmp_path)
    assert (outside / "codex-any-bot-windows-x64.zip").read_text() == "keep"
