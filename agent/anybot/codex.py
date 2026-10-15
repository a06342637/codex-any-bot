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


def run_turn(binary: str, settings, cancel: threading.Event, emit) -> dict:
    args = [binary, "exec"]
    if settings.thread_id:
        args += ["resume"]
    args += ["--json", "--skip-git-repo-check"]
    if settings.thread_id:
        args.append(settings.thread_id)
    args.append("-")  # Prompt via stdin, never interpreted by a shell.
    tree = ProcessTree(args, settings.cwd or None)
    lines = queue.Queue()

    def read():
        try:
            for raw in tree.proc.stdout:
                lines.put(raw.decode("utf-8", "replace"))
        finally:
            lines.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    tree.proc.stdin.write(settings.prompt.encode("utf-8"))
    tree.proc.stdin.close()
    completed = False
    failed = False
    thread_id = settings.thread_id
    errors = []
    try:
        while True:
            if cancel.is_set():
                return {"kind": "cancelled", "thread_id": thread_id}
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                if "error" in line.lower() or "failed" in line.lower():
                    errors.append(line[:1000])
                    errors = errors[-10:]
                continue
            if not isinstance(event, dict):
                continue
            kind = event.get("type")
            if kind == "thread.started":
                thread_id = event.get("thread_id") or thread_id
                emit({"event": "thread", "thread_id": thread_id})
            elif kind == "turn.completed":
                completed = True
            elif kind in ("error", "turn.failed"):
                # Reconnecting errors may precede a later completed turn.
                failed = failed or kind == "turn.failed"
                errors.append(json.dumps(event, ensure_ascii=False)[:1000])
                errors = errors[-10:]
            elif kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                emit({"event": "output"})
        while tree.proc.poll() is None:
            if cancel.wait(0.2):
                return {"kind": "cancelled", "thread_id": thread_id}
        if completed and not failed and tree.proc.returncode == 0 and thread_id:
            return {"kind": "success", "thread_id": thread_id}
        kind = classify_error("\n".join(errors))
        if not thread_id and kind == "failed":
            kind = "unknown_session"  # Never blindly create another thread after an ambiguous start.
        return {"kind": kind, "thread_id": thread_id}
    finally:
        tree.close()
        reader.join(timeout=2)


def rpc(method: str, params: dict, binary: str | None = None) -> dict:
    tree = ProcessTree([binary or find_codex(), "app-server"])
    replies = queue.Queue()

    def read():
        for line in tree.proc.stdout:
            try:
                replies.put(json.loads(line))
            except ValueError:
                pass
        replies.put({"error": {"message": "Codex app-server 已退出"}})

    threading.Thread(target=read, daemon=True).start()

    def send(data):
        tree.proc.stdin.write((json.dumps(data) + "\n").encode())
        tree.proc.stdin.flush()

    def request(mid, name, values):
        send({"id": mid, "method": name, "params": values})
        until = time.monotonic() + 30
        while time.monotonic() < until:
            obj = replies.get(timeout=max(0.1, until - time.monotonic()))
            if obj.get("id") == mid or ("error" in obj and "id" not in obj):
                if "error" in obj:
                    raise RuntimeError(str(obj["error"])[:300])
                return obj.get("result", {})
        raise TimeoutError("Codex 会话接口超时")

    try:
        request(1, "initialize", {"clientInfo": {"name": "codex-any-bot", "version": __version__}})
        send({"method": "initialized", "params": {}})
        return request(2, method, params)
    finally:
        tree.close()


def diagnose() -> dict:
    binary = find_codex()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, **kwargs)
    auth = subprocess.run([binary, "login", "status"], capture_output=True, text=True, timeout=15, **kwargs)
    return {"codex": binary, "version": version.stdout.strip()[:120],
            "logged_in": auth.returncode == 0, "platform": sys.platform}
