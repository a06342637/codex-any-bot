from pathlib import Path

import pytest

from anybot.directories import list_directories


def test_lists_only_immediate_folders_with_stable_pagination(tmp_path):
    for index in range(19):
        (tmp_path / f"项目 {index:02}").mkdir()
    (tmp_path / "项目 00" / "nested").mkdir()
    (tmp_path / "private.txt").write_text("not directory data")
    first = list_directories(str(tmp_path))
    assert first["total"] == 19 and len(first["entries"]) == 8
    assert first["path"] == str(tmp_path.resolve())
    second = list_directories("", first["path"], first["next_offset"])
    last = list_directories("", first["path"], second["next_offset"])
    names = [entry["name"] for page in [first, second, last] for entry in page["entries"]]
    assert names == [f"项目 {index:02}" for index in range(19)]
    assert last["next_offset"] is None and last["previous_offset"] == 8


def test_empty_folder_parent_and_fallback_to_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    page = list_directories(str(tmp_path / "missing"))
    assert page["path"] == str(tmp_path) and page["entries"] == []
    assert page["parent"] == str(tmp_path.parent)
    assert page["next_offset"] is None
    assert list_directories("", location="home")["path"] == str(tmp_path)


def test_drive_roots_can_be_browsed_without_probing_each_drive(monkeypatch):
    monkeypatch.setattr("anybot.directories.drive_roots", lambda: ["C:\\", "D:\\"])
    page = list_directories("", location="roots")
    assert page["path"] is None and page["parent"] is None
    assert [entry["path"] for entry in page["entries"]] == ["C:\\", "D:\\"]


def test_invalid_missing_and_inaccessible_paths(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="绝对"):
        list_directories("", "relative/path")
    with pytest.raises(ValueError, match="不存在"):
        list_directories("", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="页码"):
        list_directories(str(tmp_path), offset=-1)
    def denied(_):
        raise PermissionError()
    monkeypatch.setattr("anybot.directories.os.scandir", denied)
    with pytest.raises(ValueError, match="权限"):
        list_directories("", str(tmp_path))
