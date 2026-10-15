"""Exercise a bundled client, SQLite, networking import and local stop without Codex/TG."""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
if sys.platform == "win32" and not exe.suffix:
    exe = exe.with_suffix(".exe")
with tempfile.TemporaryDirectory(prefix="anybot-smoke-") as directory:
    root = Path(directory)
    (root / "config.json").write_text(json.dumps({"device_id": "smoke-test", "token": "not-a-real-token",
                                                 "server": "https://127.0.0.1:9", "cwd": directory}))
    env = {**os.environ, "ANYBOT_DATA_DIR": directory}
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    proc = subprocess.Popen([str(exe), "run"], env=env, **kwargs)
    try:
        until = time.time() + 15
        while not (root / "state.sqlite").exists() and time.time() < until:
            if proc.poll() is not None:
                raise RuntimeError("Packaged client exited before startup")
            time.sleep(0.1)
        assert (root / "state.sqlite").exists()
        subprocess.run([str(exe), "stop-local"], env=env, check=True, timeout=40, **kwargs)
        assert proc.wait(timeout=15) == 0
        with sqlite3.connect(root / "state.sqlite") as db:
            data = json.loads(db.execute("SELECT value FROM records WHERE key='last_state'").fetchone()[0])
            assert data["task"] is None
            assert data["connected"] is False and data["synced"] is False
        db.close()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
print("Frozen client starts idle and stops cleanly.")
