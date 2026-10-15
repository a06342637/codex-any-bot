import argparse
import contextlib
import getpass
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import platform
import re
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
from .cleanup import cleanup_legacy
from .codex import diagnose
from .runtime import Agent
from .storage import Store, data_dir, load_config, save_config

RELEASES = "https://github.com/a06342637/codex-any-bot/releases"


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url, body=None, headers=None):
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    handlers = [urllib.request.HTTPSHandler(context=context)]
    if body is not None or headers:
        handlers.append(NoCredentialRedirect())
    with urllib.request.build_opener(*handlers).open(request, timeout=30) as response:
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
        manifest = json.loads(fetch(RELEASES + "/latest/download/manifest.json"))
        tag = manifest["version"]
        if not isinstance(tag, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            raise RuntimeError("Invalid release version")
        name = "install.ps1" if sys.platform == "win32" else "install.sh"
        script = fetch(f"{RELEASES}/download/{tag}/{name}")
        if hashlib.sha256(script).hexdigest() != manifest["files"][name]["sha256"]:
            raise RuntimeError("Installer checksum mismatch")
        cache = data_dir() / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="update-", dir=cache) as directory:
            path = Path(directory) / name
            path.write_bytes(script)
            if sys.platform == "win32":
                args = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path), "-Update"]
                options = {"creationflags": subprocess.CREATE_NO_WINDOW}
            else:
                args = ["bash", str(path), "--update"]
                options = {"start_new_session": True}
            result = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=600, **options)
            if result.returncode:
                raise RuntimeError("Update installer failed; retained previous client")
    elif action == "revoke":
        config = load_config()
        config["revoked"] = True
        save_config(config)


def validate_server(server):
    server = server.strip().rstrip("/")
    parsed = urlparse(server)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise RuntimeError("Server must be an HTTPS origin / 请填写自己的 CF HTTPS 根地址")
    return server


def bind(root, server, name, cwd, credentials):
    if sys.platform not in ("win32", "darwin"):
        raise RuntimeError("仅支持 Windows 和 macOS")
    server = validate_server(server)
    if (root / "config.json").exists() and not load_config(root).get("revoked"):
        raise RuntimeError("本机已绑定；更新请在 TG 操作，重新绑定请先卸载")
    directory = Path(cwd).expanduser().resolve()
    if not directory.is_dir():
        raise RuntimeError("工作目录不存在")
    diagnostic = diagnose()
    if not diagnostic.get("ready", diagnostic.get("logged_in", False)):
        raise RuntimeError(diagnostic.get("auth_detail") or "请先在本机运行 codex login 完成登录")
    try:
        result = json.loads(fetch(server + "/v1/enroll", {
            **credentials, "name": name, "platform": sys.platform, "cwd": str(directory),
        }))
    except (urllib.error.URLError, ValueError):
        raise RuntimeError("绑定失败：检查 CF 地址、Bot Token/用户 ID（或配对码），并确认云端已升级") from None
    if not isinstance(result, dict) or result.get("protocol") != 1 or not isinstance(result.get("device_id"), str) or not re.fullmatch(r"[a-f0-9]{64}", str(result.get("token", ""))):
        raise RuntimeError("绑定响应无效")
    store = Store(root)
    try:
        store.bind_device(result["device_id"], reset=True)
    finally:
        store.close()
    # Only retain a per-device token, never the input Bot Token.
    save_config({"device_id": result["device_id"], "token": result["token"],
                 "protocol": 1, "server": server, "cwd": str(directory)}, root)
    print("Bound successfully / 绑定成功，准备在后台上线。")


def setup(args, root):
    if sys.stdin is None or not sys.stdin.isatty():
        raise RuntimeError("请在交互终端运行安装命令，不要使用 curl | bash；Windows 请使用安装器或 console 入口")
    server = args.server or input("CF HTTPS 地址（填写你自己的服务地址）：").strip()
    server = validate_server(server)
    print("绑定服务：" + server)
    token = getpass.getpass("Bot Token（隐藏输入，仅本次校验）：").strip()
    user_id = input("你的 Telegram 数字用户 ID：").strip()
    if not token or not user_id.isdigit():
        raise RuntimeError("Bot Token 不能为空，用户 ID 必须为数字")
    bind(root, server, args.name, args.cwd, {"bot_token": token, "user_id": user_id})


def stop_local(root):
    (root / "stop.request").touch()
    until = time.monotonic() + 30
    while True:
        try:
            with single_instance(root):
                if (root / "state.sqlite").exists():
                    store = Store(root)
                    try:
                        state = store.get("last_state", {})
                        state.update(connected=False, synced=False, time=time.time())
                        store.put("last_state", state)
                    finally:
                        store.close()
                return
        except OSError:
            if time.monotonic() >= until:
                raise RuntimeError("客户端尚未停止，请稍后重试")
            time.sleep(0.2)


def forget(root):
    if not (root / "config.json").exists():
        return
    config = load_config(root)
    try:
        result = json.loads(fetch(config["server"] + "/v1/unenroll", {}, {
            "Authorization": "Bearer " + config["token"], "X-Device-ID": config["device_id"],
        }))
        if not result.get("removed"):
            raise ValueError("not removed")
    except (urllib.error.URLError, ValueError):
        raise RuntimeError("云端设备未能移除；本机仍可卸载，之后请在 TG 移除绑定或升级云端后重试") from None
    print("Cloud device binding removed / 云端设备记录已清理。")


def wait_online(root, timeout):
    store = Store(root)
    try:
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            state = store.get("last_state", {})
            if state.get("connected") and state.get("synced") and time.time() - state.get("time", 0) < 10:
                print("Online / 已连接 TG 控制服务，当前待命。")
                return True
            time.sleep(0.25)
        print("Installed; waiting for network / 已安装，尚未确认上线，请查看日志和网络。")
        return False
    finally:
        store.close()


def main(argv=None):
    if sys.platform == "win32" and sys.stdout is None:
        import ctypes
        if "run" not in (argv if argv is not None else sys.argv[1:]):
            ctypes.windll.kernel32.AttachConsole(-1)
        try:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8")
            sys.stderr = open("CONOUT$", "w", encoding="utf-8")
        except OSError:
            sys.stdout = open(os.devnull, "w")
            sys.stderr = open(os.devnull, "w")
    # Legacy Windows consoles/pipes may not support Chinese output. Keep the
    # selected encoding but escape unsupported characters instead of failing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="codex-any-bot 客户端")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ("setup", "join"):
        form = sub.add_parser(action)
        form.add_argument("--server", required=action == "join")
        if action == "join":
            form.add_argument("--code", required=True)
        form.add_argument("--name", default=platform.node())
        form.add_argument("--cwd", default=str(Path.cwd()))
    for action in ("run", "diagnose", "status", "stop-local", "forget", "clean-cache"):
        sub.add_parser(action)
    wait = sub.add_parser("wait-online")
    wait.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)
    root = data_dir()
    if args.command == "run":
        if not (root / "config.json").is_file() or (root / "stop.request").exists():
            return 0
    else:
        root.mkdir(parents=True, exist_ok=True)
    try:
        handler = RotatingFileHandler(root / "agent.log", maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    except FileNotFoundError:
        if args.command == "run":
            return 0  # Uninstall won the race; background startup must not recreate its data.
        raise
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.command == "setup":
            setup(args, root)
        elif args.command == "join":
            bind(root, args.server, args.name, args.cwd, {"code": args.code})
        elif args.command == "stop-local":
            stop_local(root)
        elif args.command == "forget":
            forget(root)
        elif args.command == "clean-cache":
            removed, failures = cleanup_legacy()
            print(f"Removed {removed} identified legacy temporary item(s).")
            if failures:
                print("仍未清理的路径：\n" + "\n".join(failures), file=sys.stderr)
                return 1
        elif args.command == "wait-online":
            return 0 if wait_online(root, max(1, min(args.timeout, 60))) else 2
        elif args.command == "diagnose":
            print(json.dumps(diagnose(), ensure_ascii=False, indent=2))
        elif args.command == "status":
            store = Store(root)
            try:
                print(json.dumps(store.get("last_state", {"status": "尚未运行"}), ensure_ascii=False, indent=2))
            finally:
                store.close()
        elif args.command == "run":
            config = load_config(root)
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
                    (root / "stop.request").unlink(missing_ok=True)
                    maintenance("restart")
                    return 1
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        logging.error("%s", message)
        print("ERROR: " + message, file=sys.stderr)
        return 1
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
