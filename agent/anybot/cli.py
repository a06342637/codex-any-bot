import argparse
import contextlib
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import certifi

from . import __version__
from .codex import diagnose
from .runtime import Agent
from .storage import data_dir, load_config, save_config

RELEASES = "https://github.com/a06342637/codex-any-bot/releases"


def fetch(url, body=None, headers=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return response.read()


@contextlib.contextmanager
def single_instance(root):
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / "agent.lock").open("a+b")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        handle.close()


def detached(args):
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if sys.platform == "win32" else {"start_new_session": True}
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)


def self_command():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "anybot"]


def maintenance(action):
    if action == "restart":
        detached(self_command() + ["run"])
    elif action == "update":
        # Download and validate an installer before launching it. It installs a new version directory.
        manifest = json.loads(fetch(RELEASES + "/latest/download/manifest.json"))
        tag = manifest["version"]
        if not isinstance(tag, str) or not __import__("re").fullmatch(r"v\d+\.\d+\.\d+", tag):
            raise RuntimeError("Invalid release version")
        name = "install.ps1" if sys.platform == "win32" else "install.sh"
        script = fetch(f"{RELEASES}/download/{tag}/{name}")
        if hashlib.sha256(script).hexdigest() != manifest["files"][name]["sha256"]:
            raise RuntimeError("Installer checksum mismatch")
        path = Path(tempfile.mkdtemp(prefix="anybot-update-")) / name
        path.write_bytes(script)
        if sys.platform == "win32":
            detached(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), "-Update"])
        else:
            detached(["bash", str(path), "--update"])
    elif action == "revoke":
        root = data_dir()
        config = load_config()
        config["revoked"] = True
        save_config(config, root)


def main(argv=None):
    if sys.platform == "win32" and sys.stdout is None:
        # A windowless binary stays invisible at login, but can write to an existing terminal.
        import ctypes
        if "run" not in (argv if argv is not None else sys.argv[1:]):
            ctypes.windll.kernel32.AttachConsole(-1)
        try:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except OSError:
            sys.stdout = open(os.devnull, "w")
            sys.stderr = open(os.devnull, "w")
    parser = argparse.ArgumentParser(description="codex-any-bot 后台客户端")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    join = sub.add_parser("join")
    join.add_argument("--server", required=True)
    join.add_argument("--code", required=True)
    join.add_argument("--name", default=platform.node())
    join.add_argument("--cwd", default=str(Path.cwd()))
    sub.add_parser("run")
    sub.add_parser("diagnose")
    sub.add_parser("status")
    sub.add_parser("stop-local")
    args = parser.parse_args(argv)
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(root / "agent.log", maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "join":
            if sys.platform not in ("win32", "darwin"):
                raise RuntimeError("仅支持 Windows 和 macOS")
            parsed = urlparse(args.server)
            if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username:
                raise RuntimeError("Server must be an HTTPS origin / 服务地址必须是 HTTPS 根地址")
            if (root / "config.json").exists() and not load_config().get("revoked"):
                raise RuntimeError("本机已绑定，请使用更新操作；重新绑定请先卸载并清理配置")
            info = diagnose()
            if not info["logged_in"]:
                raise RuntimeError("请先在本机运行 codex login 完成登录")
            try:
                result = json.loads(fetch(args.server.rstrip("/") + "/v1/enroll", {
                    "code": args.code, "name": args.name, "platform": sys.platform, "cwd": str(Path(args.cwd).resolve()),
                }))
            except urllib.error.HTTPError as exc:
                raise RuntimeError("配对失败：检查配对码是否过期，以及托管服务配置") from exc
            save_config({**result, "server": args.server.rstrip("/"), "cwd": str(Path(args.cwd).resolve())})
            print("Bound successfully / 绑定成功，客户端将上线待命。")
        elif args.command == "stop-local":
            (root / "stop.request").touch()
            until = time.monotonic() + 30
            while True:
                try:
                    with single_instance(root):
                        break
                except OSError:
                    if time.monotonic() >= until:
                        raise RuntimeError("客户端尚未停止，请稍后重试")
                    time.sleep(0.2)
        elif args.command == "diagnose":
            print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        elif args.command == "status":
            from .storage import Store
            store = Store(root)
            print(json.dumps(store.get("last_state", {"status": "尚未运行"}), ensure_ascii=False, indent=2))
            store.close()
        elif args.command == "run":
            config = load_config()
            if config.get("revoked") or (root / "stop.request").exists():
                return 0
            with single_instance(root):
                agent = Agent(config)
                signal.signal(signal.SIGTERM, lambda *_: agent.shutdown.set())
                action = agent.run()
            if action:
                try:
                    maintenance(action)
                except Exception:
                    logging.error("Maintenance failed; restarting existing version")
                    maintenance("restart")
                    return 1
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Avoid HTTP request URLs containing credentials in logs or console output.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        logging.error("%s", message)
        print("ERROR: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
