"""Codex subprocess adapter. Never changes user auth, config, or writer locks."""
import ctypes
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import tomllib
from collections import deque
from pathlib import Path

from . import __version__


def group_has_live_members(group_id: int) -> bool:
    # Darwin can report EPERM when a process group contains only exited/zombie members.
    # Inspect only IDs and states, never command lines or environment variables.
    result = subprocess.run(["ps", "-axo", "pid=,pgid=,stat="], capture_output=True,
                            text=True, timeout=3, check=True)
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[1] == str(group_id) and not fields[2].startswith("Z"):
            return True
    return False


def signal_group(group_id: int, sig: int):
    try:
        os.killpg(group_id, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        if group_has_live_members(group_id):
            raise


def find_codex() -> str:
    candidates = [os.environ.get("ANYBOT_CODEX")]
    candidates += [shutil.which("codex"), shutil.which("codex.exe")]
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        npm = Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@openai"
        candidates += [str(p) for p in sorted((local / "OpenAI/Codex/bin").glob("*/codex.exe"),
                                              key=lambda p: p.stat().st_mtime, reverse=True)]
        candidates += [str(p) for p in npm.glob("**/codex.exe")]
    else:
        candidates += [str(Path.home() / ".local/bin/codex"), "/opt/homebrew/bin/codex",
                       "/usr/local/bin/codex", "/Applications/Codex.app/Contents/Resources/codex"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and not candidate.lower().endswith((".cmd", ".bat")):
            return candidate
    raise RuntimeError("没有找到 Codex CLI；请先安装并登录 Codex，或设置 ANYBOT_CODEX 为可执行文件路径")


class ProcessTree:
    def __init__(self, args: list[str], cwd=None):
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
        self.proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, **kwargs)
        self.job = None
        if sys.platform == "win32":
            self._assign_job()

    def _assign_job(self):
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min", ctypes.c_size_t), ("max", ctypes.c_size_t),
                        ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if handle and kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) and kernel.AssignProcessToJobObject(handle, int(self.proc._handle)):
            self.job = (kernel, handle)
        elif handle:
            kernel.CloseHandle(handle)

    def stop(self):
        if self.job:
            self.job[0].TerminateJobObject(self.job[1], 1)
        elif sys.platform == "win32":
            if self.proc.poll() is None:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            try:
                signal_group(self.proc.pid, signal.SIGTERM)
                self.proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                signal_group(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def close(self):
        self.stop()
        if self.job:
            self.job[0].CloseHandle(self.job[1])
            self.job = None
        for stream in (self.proc.stdin, self.proc.stdout):
            if stream:
                stream.close()


def classify_error(text: str) -> str:
    text = text.lower()
    if "active writer" in text or "thread-store conflict" in text:
        return "locked"
    if "archived" in text:
        return "archived"
    if any(s in text for s in ("401", "unauthorized", "not logged in", "token expired", "authentication")):
        return "auth"
    if any(s in text for s in ("permission denied", "approval", "403", "forbidden")):
        return "permission"
    if any(s in text for s in ("thread not found", "session not found", "no saved session")):
        return "unknown_session"
    return "failed"


class TurnCancelled(Exception):
    pass


class RpcError(RuntimeError):
    pass


class UnknownSession(RuntimeError):
    pass


class AppServer:
    """Quiet, cancellable stdio connection; never edits the user's config."""

    def __init__(self, binary=None, cwd=None, cancel=None):
        self.cancel = cancel or threading.Event()
        self.tree = ProcessTree([binary or find_codex(), "-c", "notify=[]",
                                 "-c", "tui.notifications=false", "app-server"], cwd)
        self.replies = queue.Queue()
        self.notifications = deque()
        self.serial = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.tree.proc.stdout:
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        self.replies.put(obj)
                except ValueError:
                    pass
        finally:
            self.replies.put(None)

    def send(self, data):
        self.tree.proc.stdin.write((json.dumps(data) + "\n").encode("utf-8"))
        self.tree.proc.stdin.flush()

    def receive(self, until=None):
        while True:
            if self.cancel.is_set():
                raise TurnCancelled()
            if until is not None and time.monotonic() >= until:
                raise TimeoutError("Codex 会话接口超时")
            try:
                obj = self.replies.get(timeout=0.2)
            except queue.Empty:
                continue
            if obj is None:
                raise RuntimeError("Codex app-server 已退出")
            if "method" in obj and "id" in obj:
                # Never approve tools or wait forever for unattended user input.
                raise RpcError("approval or user input required")
            return obj

    def request(self, method, params):
        self.serial += 1
        mid = self.serial
        self.send({"id": mid, "method": method, "params": params})
        until = time.monotonic() + 30
        while True:
            obj = self.receive(until)
            if obj.get("id") == mid:
                if "error" in obj:
                    raise RpcError(json.dumps(obj["error"])[:1000])
                return obj.get("result", {})
            # Completion can arrive before turn/start's reply. Do not buffer
            # arbitrarily large output streams while waiting for that reply.
            if obj.get("method") == "turn/completed":
                self.notifications.append(obj)

    def initialize(self):
        self.request("initialize", {"clientInfo": {"name": "codex-any-bot", "version": __version__}})
        self.send({"method": "initialized", "params": {}})

    def close(self):
        self.tree.close()
        self.reader.join(timeout=2)


def visible_thread(server, settings, emit):
    """Fork legacy exec history through Codex, preserving its original record."""
    options = {"cwd": settings.cwd or None, "approvalPolicy": "never",
               "config": {"notify": [], "tui.notifications": False}}
    creating = not settings.thread_id
    if settings.thread_id:
        existing = server.request("thread/read", {"threadId": settings.thread_id, "includeTurns": False})["thread"]
        if existing.get("id") != settings.thread_id:
            raise RpcError("thread not found: mismatched session")
        creating = existing.get("source") == "exec"
        method = "thread/fork" if creating else "thread/resume"
        options["threadId"] = settings.thread_id
    else:
        method = "thread/start"
        options["ephemeral"] = False
    try:
        result = server.request(method, options)
        thread_id = result["thread"]["id"]
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("missing thread ID")
    except RpcError:
        raise
    except (RuntimeError, OSError, KeyError, TypeError, ValueError) as error:
        if creating:
            raise UnknownSession("unknown session after thread creation") from error
        raise
    # Persist the ID before naming or inference, including failed first turns.
    emit({"event": "thread", "thread_id": thread_id})
    if creating:
        label = settings.thread_name or Path(settings.cwd).name or "会话"
        try:
            server.request("thread/name/set", {"threadId": thread_id, "name": f"AnyBot · {label}"[:80]})
        except RpcError:
            pass  # Naming may be unsupported; never lose the already saved ID.
    return thread_id


def run_turn(binary: str, settings, cancel: threading.Event, emit) -> dict:
    server = AppServer(binary, settings.cwd or None, cancel)
    thread_id = settings.thread_id
    turn_id = None

    def progress(event):
        nonlocal thread_id
        thread_id = event.get("thread_id") or thread_id
        emit(event)

    try:
        server.initialize()
        thread_id = visible_thread(server, settings, progress)
        result = server.request("turn/start", {"threadId": thread_id,
            "input": [{"type": "text", "text": settings.prompt, "text_elements": []}]})
        turn_id = result["turn"]["id"]
        while True:
            obj = server.notifications.popleft() if server.notifications else server.receive()
            params = obj.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            if obj.get("method") == "turn/completed" and params.get("turn", {}).get("id") == turn_id:
                turn = params["turn"]
                status = turn.get("status")
                kind = "success" if status == "completed" else "cancelled" if status == "interrupted" else classify_error(json.dumps(turn.get("error")))
                return {"kind": kind, "thread_id": thread_id}
            if obj.get("method") == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                emit({"event": "output"})
    except TurnCancelled:
        return {"kind": "cancelled", "thread_id": thread_id}
    except UnknownSession:
        return {"kind": "unknown_session", "thread_id": thread_id}
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        kind = classify_error(str(error))
        return {"kind": "unknown_session" if not thread_id and kind == "failed" else kind, "thread_id": thread_id}
    finally:
        if cancel.is_set() and turn_id:
            try:
                server.send({"id": "interrupt", "method": "turn/interrupt", "params": {"threadId": thread_id, "turnId": turn_id}})
                until = time.monotonic() + 2
                while time.monotonic() < until:
                    try:
                        obj = server.replies.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if obj is None or (obj.get("method") == "turn/completed" and obj.get("params", {}).get("turn", {}).get("id") == turn_id):
                        break
            except OSError:
                pass
        server.close()


def rpc(method: str, params: dict, binary: str | None = None) -> dict:
    server = AppServer(binary)
    try:
        server.initialize()
        return server.request(method, params)
    finally:
        server.close()




def provider_auth_status(config_root: Path | None = None) -> dict:
    root = config_root or Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    path = root / "config.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    profile = config.get("profile")
    if isinstance(profile, str):
        config = {**config, **config.get("profiles", {}).get(profile, {})}
    provider = config.get("model_provider", "openai")
    options = config.get("model_providers", {}).get(provider, {})
    custom = provider != "openai" and bool(options) and options.get("requires_openai_auth", False) is False
    if custom:
        env_key = options.get("env_key")
        missing = isinstance(env_key, str) and not os.environ.get(env_key)
        return {"provider": provider, "requires_openai_login": False, "ready": not missing,
                "auth_detail": f"自定义服务缺少环境变量 {env_key}" if missing else "自定义服务（无需 OpenAI 登录；服务连通性尚未测试）"}
    return {"provider": provider, "requires_openai_login": True}


def thread_info(thread_id: str) -> dict:
    result = rpc("thread/read", {"threadId": thread_id, "includeTurns": False})
    thread = result.get("thread", {})
    if thread.get("id") != thread_id:
        raise RuntimeError("会话信息不匹配")
    title = str(thread.get("name") or thread.get("preview") or "").strip().splitlines()
    return {"id": thread_id, "name": title[0][:80] if title else None}


def delete_thread(thread_id: str) -> None:
    if not isinstance(thread_id, str) or not thread_id or len(thread_id) > 128:
        raise ValueError("无效的会话 ID")
    try:
        rpc("thread/delete", {"threadId": thread_id})
    except RuntimeError as error:
        if "-32601" in str(error) or "method not found" in str(error).lower():
            raise RuntimeError("当前 Codex CLI 不支持删除会话，请先更新 Codex") from None
        raise RuntimeError("删除会话未完成，请检查会话是否被占用以及 Codex 状态") from None


def diagnose() -> dict:
    binary = find_codex()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, **kwargs)
    auth = subprocess.run([binary, "login", "status"], capture_output=True, text=True, timeout=15, **kwargs)
    logged_in = auth.returncode == 0
    try:
        provider = provider_auth_status()
    except (OSError, ValueError, TypeError):
        provider = {"requires_openai_login": True, "ready": False,
                    "auth_detail": "无法读取 Codex 配置，请先修复配置文件"}
    provider.setdefault("ready", logged_in)
    provider.setdefault("auth_detail", "OpenAI 登录正常" if logged_in else "请先在本机运行 codex login 完成登录")
    return {"codex": binary, "version": version.stdout.strip()[:120],
            "logged_in": logged_in, "platform": sys.platform, **provider}
