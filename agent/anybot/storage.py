import json
import os
import sqlite3
import sys
from pathlib import Path


def data_dir() -> Path:
    if os.environ.get("ANYBOT_DATA_DIR"):
        return Path(os.environ["ANYBOT_DATA_DIR"]).resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "codex-any-bot"
    return Path.home() / "Library/Application Support/codex-any-bot"


def save_config(config: dict, root: Path | None = None) -> None:
    root = root or data_dir()
    root.mkdir(parents=True, exist_ok=True)
    temp = root / "config.tmp"
    temp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(root / "config.json")


def load_config(root: Path | None = None) -> dict:
    return json.loads(((root or data_dir()) / "config.json").read_text(encoding="utf-8"))


class Store:
    def __init__(self, root: Path, *, create_directory: bool = True):
        if create_directory:
            root.mkdir(parents=True, exist_ok=True)
        elif not root.is_dir():
            raise FileNotFoundError(root)
        self.db = sqlite3.connect(root / "state.sqlite")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, result TEXT NOT NULL);
        """)

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM records WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

    def bind_device(self, device_id: str, *, reset: bool = False) -> None:
        previous = self.get("device_id")
        if reset or (previous is not None and previous != device_id):
            with self.db:
                self.db.execute("DELETE FROM commands")
                self.db.execute("DELETE FROM records")
        self.put("device_id", device_id)

    def claim(self, command_id: str) -> dict | None:
        row = self.db.execute("SELECT result FROM commands WHERE id=?", (command_id,)).fetchone()
        if row:
            return json.loads(row[0])
        # A crash after this claim is deliberately never replayed: no duplicate new sessions.
        result = {"ok": False, "message": "命令已接收；若客户端中途重启，请查询状态后重新操作"}
        self.db.execute("INSERT INTO commands VALUES (?,?)", (command_id, json.dumps(result)))
        self.db.commit()
        return None

    def complete(self, command_id: str, result: dict) -> None:
        self.db.execute("UPDATE commands SET result=? WHERE id=?", (json.dumps(result), command_id))
        self.db.commit()

    def close(self):
        self.db.close()
