"""Remove identifiable caches produced by this application; never sweep the temp directory."""
import json
import re
import os
import tempfile
from pathlib import Path

REPOSITORY = "https://github.com/a06342637/codex-any-bot/releases"
ARCHIVES = {
    "codex-any-bot-windows-x64.zip", "codex-any-bot-windows-arm64.zip",
    "codex-any-bot-macos-x64.tar.gz", "codex-any-bot-macos-arm64.tar.gz",
}


def linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def our_script(path: Path) -> bool:
    if linked(path) or not path.is_file() or path.stat().st_size > 1024 * 1024:
        return False
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return REPOSITORY in text and ("$root" in text or 'root="$HOME/Library/Application Support/codex-any-bot"' in text)


def legacy_candidates(temp_root: Path):
    temp_root = temp_root.resolve()
    for path in temp_root.iterdir():
        try:
            if linked(path) or path.resolve().parent != temp_root:
                continue
            if path.is_file():
                if (re.fullmatch(r"anybot-[a-fA-F0-9-]{32,36}\.ps1", path.name)
                        or re.fullmatch(r"anybot-bootstrap[.a-zA-Z0-9_-]+", path.name)) and our_script(path):
                    yield path
                continue
            if not path.is_dir():
                continue
            if not (re.fullmatch(r"anybot-update-[a-zA-Z0-9_-]+", path.name)
                    or re.fullmatch(r"codex-any-bot-[a-fA-F0-9]{32}", path.name)
                    or (path.name.startswith("tmp.") and (path / "manifest.json").is_file())):
                continue
            children = list(path.iterdir())
            if not children or any(linked(p) or not p.is_file() for p in children):
                continue
            names = {p.name for p in children}
            if re.fullmatch(r"anybot-update-[a-zA-Z0-9_-]+", path.name):
                if names <= {"install.ps1", "install.sh"} and all(our_script(p) for p in children):
                    yield path
            elif re.fullmatch(r"codex-any-bot-[a-fA-F0-9]{32}", path.name):
                if names <= ARCHIVES:
                    yield path
            elif path.name.startswith("tmp.") and "manifest.json" in names:
                allowed = ARCHIVES | {"manifest.json", "latest.json", "agent.plist", "current.json"}
                if names <= allowed and (path / "manifest.json").stat().st_size < 1024 * 1024:
                    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                    if ARCHIVES.intersection(manifest.get("files", {})):
                        yield path
        except (OSError, ValueError):
            continue


def cleanup_legacy(temp_root: Path | None = None) -> tuple[int, list[str]]:
    temp_root = (temp_root or Path(os.environ.get("ANYBOT_LEGACY_TEMP_DIR") or tempfile.gettempdir())).resolve()
    removed, failures = 0, []
    for path in list(legacy_candidates(temp_root)):
        try:
            # Revalidate the resolved target immediately before deleting. No recursive deletion.
            if linked(path) or path.resolve().parent != temp_root:
                continue
            if path.is_dir():
                children = list(path.iterdir())
                if any(linked(p) or not p.is_file() for p in children):
                    continue
                for child in children:
                    child.unlink()
                path.rmdir()
            else:
                path.unlink()
            removed += 1
        except OSError:
            failures.append(str(path))
    return removed, failures
