import json
import logging
import queue
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import websocket
import certifi

from . import __version__
from .codex import delete_thread, diagnose, find_codex, rpc, run_turn, thread_info
from .state import Settings, Task
from .storage import Store, data_dir


class Agent:
    def __init__(self, config: dict, root=None, turn_runner=run_turn, clock=time.time):
        self.config = config
        self.root = root or data_dir()
        self.store = Store(self.root, create_directory=False)
        self.store.bind_device(config["device_id"])
        self.clock = clock
        self.turn_runner = turn_runner
        self.settings = Settings.parse(self.store.get("settings", {"cwd": config.get("cwd", "")}))
        self.version = self.store.get("version", 0)
        self.task = None
        self.events = queue.Queue()
        self.outbox = queue.Queue(maxsize=128)
        self.reconnect_requested = threading.Event()
        self.worker = None
        self.cancel = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.connected = False
        self.synced = False
        self.last_connected = 0
        self.ws = None
        self.active_socket = None
        self.shutdown = threading.Event()
        self.after_exit = None
        self.connection_id = ""
        self.last_status = 0
        self.boot_id = str(uuid.uuid4())
        self.session_operation = False
        self.metadata_requested = set()

    def send(self, message):
        if self.connected and self.ws:
            try:
                self.outbox.put_nowait((self.active_socket or self.ws, json.dumps({"protocol": 1, **message})))
            except queue.Full:
                # ACKs remain in SQLite; reconnect to reconcile rather than block the timer.
                self.reconnect_requested.set()

    def sender(self):
        while not self.shutdown.is_set():
            if self.reconnect_requested.is_set():
                self.reconnect_requested.clear()
                if self.ws:
                    self.ws.close()
            try:
                socket, message = self.outbox.get(timeout=0.2)
            except queue.Empty:
                continue
            if socket is not self.ws:
                continue
            try:
                socket.send(message)
            except Exception:
                self.events.put(("transport", (socket, "disconnected", None)))
                socket.close()

    def snapshot(self):
        return {"event": "status", "version": self.version, "boot_id": self.boot_id,
                "connected": self.connected, "synced": self.synced,
                "agent_version": __version__, "settings": self.settings.json(),
                "capabilities": ["session_delete", "session_names", "immediate_retry"],
                "task": self.task.json() if self.task else None, "time": self.clock()}

    def publish(self, notice=None):
        state = self.snapshot()
        self.store.put("last_state", state)
        if notice:
            state["notice"] = notice
        self.send(state)
        self.last_status = self.clock()

    def stop(self, reason="已停止"):
        self.cancel.set()
        if self.task:
            self.task.reason = reason
            self.task.phase = "stopping" if self.worker and self.worker.is_alive() else "stopped"
        self.publish()

    def acknowledge(self, command, result):
        self.store.complete(command["id"], result)
        self.send({"event": "ack", "command_id": command["id"], **result})

    def request_thread_info(self, thread_id):
        if not thread_id or thread_id in self.metadata_requested:
            return
        self.metadata_requested.add(thread_id)
        def read():
            try:
                self.events.put(("thread_info", thread_info(thread_id)))
            except Exception:
                pass  # An unavailable title must not block execution or hide its ID.
        self.pool.submit(read)

    def command(self, command):
        if command.get("device_id") != self.config["device_id"]:
            return
        old = self.store.claim(command["id"])
        if old is not None:
            self.send({"event": "ack", "command_id": command["id"], **old})
            return
        try:
            action = command["action"]
            payload = command.get("payload", {})
            version = command.get("version", 0)
            if command.get("expires_at", 0) < self.clock():
                raise ValueError("指令已过期，请重新操作")
            if version < self.version:
                raise ValueError("指令已被较新的操作替代")
            if self.session_operation and action in ("start", "settings", "delete_session", "restart", "update"):
                raise ValueError("正在删除会话，请等待完成")
            self.version = version
            self.store.put("version", version)
            if action == "stop":
                self.stop(payload.get("reason", "手动停止"))
            elif action == "settings":
                if self.task and self.task.phase not in ("stopped", "paused") and (
                    ("thread_id" in payload and payload["thread_id"] != self.task.settings.thread_id)
                    or ("cwd" in payload and payload["cwd"] != self.task.settings.cwd)
                ):
                    raise ValueError("修改会话或目录前请先停止任务")
                values = {**self.settings.json(), **payload}
                if "thread_id" in payload and payload["thread_id"] != self.settings.thread_id and "thread_name" not in payload:
                    values["thread_name"] = None
                self.settings = Settings.parse(values)
                self.store.put("settings", self.settings.json())
                if self.task and self.task.phase not in ("stopped", "paused"):
                    # A live task keeps its selected thread and directory.
                    values = {**self.settings.json(), "cwd": self.task.settings.cwd,
                              "thread_id": self.task.settings.thread_id}
                    self.task.settings = Settings.parse(values)
                    self.task.version = version
                    if self.task.expired(self.clock()):
                        self.stop("保持时间已到")
            elif action == "deadline":
                if self.task:
                    self.task.stop_at = payload.get("stop_at")
                    if self.task.expired(self.clock()):
                        self.stop("指定停止时间已到")
            elif action == "start":
                if self.task and self.task.phase not in ("stopped", "paused"):
                    raise ValueError("已有任务，请先停止后再启动")
                if self.worker and self.worker.is_alive():
                    raise ValueError("正在停止上一轮，请稍后再试")
                settings = Settings.parse({**self.settings.json(), **payload.get("settings", {})})
                if settings.thread_id != self.settings.thread_id and "thread_name" not in payload.get("settings", {}):
                    settings.thread_name = None
                directory = Path(settings.cwd).expanduser()
                if not settings.cwd or not directory.is_absolute() or not directory.is_dir():
                    raise ValueError("工作目录不存在，请在 TG 设置有效的绝对路径")
                settings.cwd = str(directory.resolve())
                find_codex()
                self.settings = settings
                self.store.put("settings", settings.json())
                self.task = Task(command["id"], version, Settings.parse(settings.json()), stop_at=payload.get("stop_at"))
                if not settings.thread_name:
                    self.request_thread_info(settings.thread_id)
            elif action == "delete_session":
                if (self.worker and self.worker.is_alive()) or (self.task and self.task.phase not in ("stopped", "paused")):
                    raise ValueError("请先停止当前任务，再删除会话")
                target = payload.get("thread_id")
                if not isinstance(target, str) or not target or len(target) > 128:
                    raise ValueError("无效的会话 ID")
                self.session_operation = True
                def remove():
                    try:
                        if command.get("expires_at", 0) < self.clock():
                            raise RuntimeError("删除指令已过期，请重新确认")
                        delete_thread(target)
                        result = {"ok": True, "deleted_thread_id": target}
                    except Exception as exc:
                        result = {"ok": False, "message": str(exc)[:240] if isinstance(exc, RuntimeError) else "删除会话失败"}
                    self.events.put(("session_deleted", (command, result)))
                self.pool.submit(remove)
                return
            elif action in ("sessions", "diagnose"):
                def work():
                    try:
                        if action == "sessions":
                            result = rpc("thread/list", {"limit": 8, "sortKey": "updated_at", "archived": False,
                                                         **({"cursor": payload["cursor"]} if payload.get("cursor") else {})})
                            data = [{k: t.get(k) for k in ("id", "name", "preview", "cwd", "updatedAt")} for t in result.get("data", [])]
                            for item in data:
                                item["preview"] = str(item.get("preview") or "")[:240]
                                item["name"] = str(item.get("name") or "")[:120]
                            value = {"ok": True, "sessions": data, "cursor": result.get("nextCursor")}
                        else:
                            value = {"ok": True, "diagnostics": diagnose()}
                    except Exception as exc:
                        value = {"ok": False, "message": str(exc)[:300]}
                    self.events.put(("result", (command, value)))
                self.pool.submit(work)
                return
            elif action in ("restart", "update", "revoke"):
                self.stop("客户端维护")
                self.after_exit = action
                self.shutdown.set()
            else:
                raise ValueError("未知指令")
            self.acknowledge(command, {"ok": True, "message": "已接收"})
            self.publish()
        except Exception as exc:
            self.acknowledge(command, {"ok": False, "message": str(exc)[:300]})

    def tick(self):
        if (self.root / "stop.request").exists():
            self.shutdown.set()
            self.stop("本地停止")
            return
        now = self.clock()
        task = self.task
        if task and task.phase not in ("stopped", "stopping") and task.expired(now):
            self.stop("保持时间已到" if task.first_success_at is not None else "指定停止时间已到")
        if task and task.phase == "stopping" and not (self.worker and self.worker.is_alive()):
            task.phase = "stopped"
            self.publish(task.reason)
        if task and task.phase not in ("stopped", "stopping", "paused", "running"):
            if self.worker and self.worker.is_alive():
                return
            if not self.connected and now - self.last_connected >= 60:
                return
            if self.connected and not self.synced:
                return
            if now >= task.next_at:
                self.cancel = threading.Event()
                if task.phase == "retrying":
                    task.retry_count += 1
                task.attempts += 1
                task.attempt_started_at = now
                task.reason = ""
                task.phase = "running"
                run_id = task.id
                settings = Settings.parse(task.settings.json())
                cancel = self.cancel

                def execute():
                    try:
                        result = self.turn_runner(find_codex(), settings, cancel,
                                                  lambda event: self.events.put(("progress", (run_id, event))))
                    except Exception as exc:
                        logging.warning("Codex execution failed: %s", type(exc).__name__)
                        result = {"kind": "failed" if settings.thread_id else "unknown_session", "thread_id": settings.thread_id}
                    self.events.put(("finished", (run_id, result)))
                self.worker = threading.Thread(target=execute, daemon=True)
                self.worker.start()
                self.publish()
        interval = 5 if task and task.phase not in ("stopped", "paused") else 30
        if now - self.last_status >= interval:
            self.publish()

    def event(self, kind, value):
        if kind == "transport":
            socket, action, data = value
            if action in ("connected", "revoked"):
                if socket is not self.ws:
                    return
                if action == "connected":
                    self.active_socket = socket
            elif socket is not self.active_socket:
                return
            self.event(action, data)
        elif kind == "connected":
            self.connected = True
            self.synced = False
            self.last_connected = self.clock()
            self.send({"event": "hello", "boot_id": self.boot_id, "agent_version": __version__})
            self.publish()
        elif kind == "disconnected":
            if self.connected:
                self.last_connected = self.clock()
            self.connected = False
            self.synced = False
        elif kind == "revoked":
            self.stop("设备凭据已失效")
            self.after_exit = "revoke"
            self.shutdown.set()
        elif kind == "message":
            if value.get("type") == "command":
                self.command(value)
            elif value.get("type") == "reconcile":
                self.version = max(self.version, value.get("version", 0))
                self.store.put("version", self.version)
                if value.get("settings"):
                    self.settings = Settings.parse(value["settings"])
                    if self.task and self.task.phase not in ("stopped", "paused"):
                        if self.settings.thread_id != self.task.settings.thread_id or not self.settings.thread_name:
                            self.settings.thread_name = self.task.settings.thread_name
                        self.settings.thread_id = self.task.settings.thread_id
                        self.task.settings = Settings.parse({**self.settings.json(), "cwd": self.task.settings.cwd})
                        self.task.stop_at = value.get("stop_at")
                    self.store.put("settings", self.settings.json())
                if value.get("desired") == "stopped":
                    self.stop("已同步停止状态")
                self.synced = True
                self.publish()
        elif kind == "result":
            self.acknowledge(*value)
        elif kind == "thread_info":
            changed = False
            for setting in [self.settings, self.task.settings if self.task else None]:
                if setting and setting.thread_id == value["id"] and value.get("name") and not setting.thread_name:
                    setting.thread_name = value["name"]
                    changed = True
            if changed:
                self.store.put("settings", self.settings.json())
                self.publish()
        elif kind == "session_deleted":
            command, result = value
            self.session_operation = False
            if result.get("ok"):
                target = result["deleted_thread_id"]
                if self.settings.thread_id == target:
                    self.settings.thread_id = None
                    self.settings.thread_name = None
                    self.store.put("settings", self.settings.json())
                if self.task and self.task.settings.thread_id == target:
                    self.task = None
                    result["cleared_task"] = True
                self.publish()
            self.acknowledge(command, result)
        elif kind in ("progress", "finished"):
            run_id, result = value
            if not self.task or self.task.id != run_id:
                return
            tid = result.get("thread_id")
            if tid:
                previous_tid = self.task.settings.thread_id
                if tid != self.task.settings.thread_id:
                    self.task.settings.thread_name = None
                self.task.settings.thread_id = tid
                if self.settings.thread_id in (previous_tid, tid):
                    if tid != self.settings.thread_id:
                        self.settings.thread_name = None
                    self.settings.thread_id = tid
                    self.store.put("settings", self.settings.json())
                if not self.task.settings.thread_name:
                    self.request_thread_info(tid)
            if kind == "finished":
                if self.task.phase in ("stopped", "stopping") or result["kind"] == "cancelled":
                    self.task.phase = "stopped"
                    self.publish(self.task.reason or "已停止")
                else:
                    first = self.task.finish(self.clock(), result["kind"])
                    notice = "首次成功，开始计算保持时间" if first else None
                    if self.task.phase == "paused":
                        notice = "任务已暂停：" + self.task.reason
                    elif self.task.failures == 1:
                        notice = "执行未成功，等待重试：" + self.task.reason
                    self.publish(notice)
            else:
                self.publish()

    def network(self):
        wait = 1
        websocket.setdefaulttimeout(10)
        context = ssl.create_default_context(cafile=certifi.where())
        context.load_default_certs()
        while not self.shutdown.is_set():
            url = self.config["server"].replace("https://", "wss://", 1) + "/v1/connect"
            self.ws = websocket.WebSocketApp(url, header=["Authorization: Bearer " + self.config["token"],
                                                         "X-Device-ID: " + self.config["device_id"],
                                                         "User-Agent: codex-any-bot/" + __version__],
                on_open=lambda ws: self.events.put(("transport", (ws, "connected", None))),
                on_message=lambda ws, msg: self._network_message(msg, ws),
                on_error=lambda ws, err: self.events.put(("transport", (ws, "revoked", None))) if getattr(err, "status_code", None) in (401, 403) else None,
                on_close=lambda ws, *args: self.events.put(("transport", (ws, "disconnected", None))))
            try:
                self.ws.run_forever(ping_interval=20, ping_timeout=10, sslopt={"context": context})
            except Exception:
                logging.warning("Relay disconnected")
            if self.shutdown.wait(wait):
                break
            wait = min(wait * 2, 30)

    def _network_message(self, msg, socket):
        try:
            value = json.loads(msg)
            if isinstance(value, dict):
                self.events.put(("transport", (socket, "message", value)))
        except ValueError:
            pass

    def run(self):
        sender = threading.Thread(target=self.sender, daemon=True)
        sender.start()
        network = threading.Thread(target=self.network, daemon=True)
        network.start()
        if not self.settings.thread_name:
            self.request_thread_info(self.settings.thread_id)
        try:
            while not self.shutdown.is_set():
                try:
                    kind, value = self.events.get(timeout=0.2)
                    self.event(kind, value)
                except queue.Empty:
                    pass
                self.tick()
        finally:
            self.shutdown.set()
            self.connected = False
            self.synced = False
            self.stop("客户端退出")
            if self.worker:
                self.worker.join(timeout=20)
            if self.ws:
                self.ws.close()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.store.close()
        return self.after_exit
