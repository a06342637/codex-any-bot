import { DurableObject } from "cloudflare:workers";
import { authorized, defaults, hash, id, localTime, now, parseSchedule, secret, settings, type Command, type Device, type Schedule, type Settings } from "./model";
import { runtimeStatus, sessionLines } from "./status";

export interface Env {
  HUB: DurableObjectNamespace<BotHub>;
  BOT_TOKEN: string;
  ALLOWED_USER_ID: string;
  CHAT_ID: string;
  WEBHOOK_SECRET: string;
  PUBLIC_BASE_URL: string;
  RELEASE_TAG: string;
}
const json = (data: unknown, status = 200) => Response.json(data, { status });
const button = (text: string, data: string) => ({ text, callback_data: data });
type Rows = ReturnType<typeof button>[][];
type Panel = { message_id: number; view: string; device_id?: string; signature: string };
type RunCard = { message_id: number; task_id: string; attempt: number; signature: string };
const legacyBatchActions = new Set(["batch", "toggle", "batchstart", "batchstop", "batchhold", "batchinterval", "stopall"]);

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") return json({ ok: true, protocol: 1 });
    if (!["/telegram/webhook", "/v1/enroll", "/v1/connect", "/v1/unenroll"].includes(url.pathname)) return json({ error: "not found" }, 404);
    if (!env.BOT_TOKEN || !env.WEBHOOK_SECRET || !env.CHAT_ID || !env.ALLOWED_USER_ID) return json({ error: "relay not configured" }, 503);
    if (url.pathname === "/telegram/webhook" && (request.method !== "POST" || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)) return json({ error: "unauthorized" }, 401);
    return env.HUB.get(env.HUB.idFromName("single-bot")).fetch(request);
  },
} satisfies ExportedHandler<Env>;

export class BotHub extends DurableObject<Env> {
  private panelQueue?: Promise<void>;
  private runQueues = new Map<string, Promise<void>>();
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.storage.sql.exec("CREATE TABLE IF NOT EXISTS records (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires REAL)");
    ctx.storage.sql.exec("CREATE INDEX IF NOT EXISTS records_expiry ON records(expires)");
  }
  get<T>(key: string): T | undefined {
    const rows = this.ctx.storage.sql.exec<{ value: string }>("SELECT value FROM records WHERE key=?", key).toArray();
    return rows.length ? JSON.parse(rows[0].value) : undefined;
  }
  put(key: string, value: unknown, expires: number | null = null) {
    this.ctx.storage.sql.exec("INSERT OR REPLACE INTO records VALUES (?,?,?)", key, JSON.stringify(value), expires);
  }
  del(key: string) { this.ctx.storage.sql.exec("DELETE FROM records WHERE key=?", key); }
  list<T>(prefix: string): T[] {
    return this.ctx.storage.sql.exec<{ value: string }>("SELECT value FROM records WHERE key LIKE ? ORDER BY key", prefix + "%").toArray().map(row => JSON.parse(row.value));
  }
  device(deviceId: string): Device {
    const device = this.get<Device>("d:" + deviceId);
    if (!device) throw new Error("机器已被移除，请刷新列表");
    return device;
  }
  socket(device: Device): WebSocket | undefined {
    return this.ctx.getWebSockets(device.id).find(ws => ws.deserializeAttachment()?.connection === device.connection && ws.readyState === WebSocket.OPEN);
  }
  online(device: Device) { return now() - device.seen < 90 && !!this.socket(device); }
  async telegram(method: string, body: any): Promise<any> {
    const response = await fetch(`https://api.telegram.org/bot${this.env.BOT_TOKEN}/${method}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(10000),
    });
    const data: any = await response.json();
    if (!data.ok) {
      if (String(data.description).includes("message is not modified")) return null;
      throw new Error(`Telegram ${data.error_code ?? response.status}`);
    }
    return data.result;
  }
  async say(text: string, rows?: Rows, silent = false): Promise<any> {
    return this.telegram("sendMessage", { chat_id: this.env.CHAT_ID, text: text.slice(0, 4000), disable_notification: silent,
      ...(rows ? { reply_markup: { inline_keyboard: rows } } : {}) });
  }
  async notify(text: string) {
    try { await this.say(text); } catch { /* A notification outage must not stop control or scheduling. */ }
  }
  async fetch(request: Request): Promise<Response> {
    try {
      const path = new URL(request.url).pathname;
      if (path === "/v1/connect") return await this.connectDevice(request);
      if (request.method !== "POST") return json({ error: "method not allowed" }, 405);
      if (Number(request.headers.get("Content-Length") ?? 0) > 65536) return json({ error: "too large" }, 413);
      const raw = await request.text();
      if (raw.length > 65536) return json({ error: "too large" }, 413);
      const body: any = JSON.parse(raw);
      if (path === "/v1/enroll") return await this.enroll(body);
      if (path === "/v1/unenroll") return await this.unenroll(request);
      if (!authorized(body, this.env.ALLOWED_USER_ID, this.env.CHAT_ID)) return json({ ok: true });
      if (!Number.isSafeInteger(body.update_id)) return json({ error: "bad update" }, 400);
      if (this.get("u:" + body.update_id)) return json({ ok: true });
      this.put("u:" + body.update_id, true, now() + 7 * 86400);
      await this.arm();
      try {
        if (body.callback_query) {
          this.ctx.waitUntil(this.telegram("answerCallbackQuery", { callback_query_id: body.callback_query.id }).catch(() => undefined));
          const messageId = body.callback_query.message?.message_id;
          await this.click(String(body.callback_query.data ?? ""), Number.isSafeInteger(messageId) ? messageId : undefined);
        } else if (body.message?.text) await this.text(String(body.message.text));
      } catch (error) {
        await this.say(error instanceof Error ? error.message : "操作失败，请重试");
      }
      return json({ ok: true });
    } catch {
      return json({ error: "request failed" }, 400);
    }
  }
  async enroll(body: any): Promise<Response> {
    if (!["win32", "darwin"].includes(body.platform)) return json({ error: "只支持 Windows 和 macOS" }, 400);
    if (body.code !== undefined) {
      // Backward compatibility for already generated v0.1.x pairing commands.
      if (typeof body.code !== "string" || !/^[a-f0-9]{64}$/.test(body.code)) return json({ error: "配对码无效" }, 401);
      const key = "enroll:" + await hash(body.code);
      const code = this.get<{ expires: number }>(key);
      if (!code || code.expires < now()) return json({ error: "配对码已过期或已使用" }, 401);
      this.del(key);
    } else {
      if (typeof body.bot_token !== "string" || typeof body.user_id !== "string" || body.user_id !== this.env.ALLOWED_USER_ID) return json({ error: "Bot Token 或用户 ID 不匹配" }, 401);
      if (await hash(body.bot_token) !== await hash(this.env.BOT_TOKEN)) return json({ error: "Bot Token 或用户 ID 不匹配" }, 401);
    }
    const token = secret();
    const device: Device = { id: id(), name: String(body.name || "新机器").slice(0, 60), platform: body.platform,
      token_hash: await hash(token), settings: settings({ ...defaults, cwd: String(body.cwd || "") }), version: 0, desired: "stopped", seen: 0 };
    this.put("d:" + device.id, device);
    await this.arm();
    this.ctx.waitUntil(this.say(`已添加 ${device.name}，等待客户端上线。`, [[button("查看机器", "d:" + device.id)]]));
    return json({ device_id: device.id, token, protocol: 1 });
  }
  async unenroll(request: Request): Promise<Response> {
    const deviceId = request.headers.get("X-Device-ID") || "";
    const token = request.headers.get("Authorization")?.replace(/^Bearer /, "") || "";
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(deviceId) || !token) return json({ error: "unauthorized" }, 401);
    const tokenHash = await hash(token);
    const device = this.get<Device>("d:" + deviceId);
    if (!device) return json({ removed: true });
    if (device.token_hash !== tokenHash) return json({ error: "unauthorized" }, 401);
    await this.eraseDevice(deviceId);
    return json({ removed: true });
  }
  async eraseDevice(deviceId: string) {
    const device = this.get<Device>("d:" + deviceId);
    for (const ws of this.ctx.getWebSockets(deviceId)) ws.close(4003, "revoked");
    for (const key of ["d:", "dirs:", "stopat:", "run:"]) this.del(key + deviceId);
    this.ctx.storage.sql.exec("DELETE FROM records WHERE json_extract(value, '$.device_id')=?", deviceId);
    this.del("batch");
    const input = this.get<any>("input");
    if (input?.ids?.includes(deviceId)) {
      input.ids = input.ids.filter((value: string) => value !== deviceId);
      if (input.ids.length) this.put("input", input, input.expires);
      else this.del("input");
    }
    if (device?.card_id) this.ctx.waitUntil(this.telegram("deleteMessage", { chat_id: this.env.CHAT_ID, message_id: device.card_id }).catch(() => undefined));
    if (this.get<Panel>("panel")?.device_id === deviceId) await this.home();
  }
  async connectDevice(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") return json({ error: "websocket required" }, 426);
    const token = request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? "";
    if (!token) return json({ error: "unauthorized" }, 401);
    const tokenHash = await hash(token);
    // Read after the await: a concurrent removal/rename must not be overwritten by stale data.
    const device = this.get<Device>("d:" + request.headers.get("X-Device-ID"));
    if (!device || tokenHash !== device.token_hash) return json({ error: "unauthorized" }, 401);
    const pair = new WebSocketPair();
    const connection = id();
    for (const old of this.ctx.getWebSockets(device.id)) old.close(4001, "replaced");
    this.ctx.acceptWebSocket(pair[1], [device.id]);
    pair[1].serializeAttachment({ device_id: device.id, connection });
    device.connection = connection;
    device.seen = now();
    device.offline_notified = false;
    this.put("d:" + device.id, device);
    await this.arm();
    return new Response(null, { status: 101, webSocket: pair[0] });
  }
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    if (typeof message !== "string" || message.length > 65536) { ws.close(1009, "invalid payload"); return; }
    const attachment = ws.deserializeAttachment();
    let device = this.get<Device>("d:" + attachment.device_id);
    if (!device || device.connection !== attachment.connection) { ws.close(4003, "revoked"); return; }
    try {
      const data = JSON.parse(message);
      if (data.protocol !== 1) { ws.close(4002, "protocol mismatch"); return; }
      device.seen = now();
      device.offline_notified = false;
      this.put("d:" + device.id, device);
      if (data.event === "hello") {
        const reboot = !!device.boot_id && device.boot_id !== data.boot_id;
        if (reboot) {
          delete device.session_delete;
          device.desired = "stopped";
          device.version++;
          for (const cmd of this.list<Command>("cmd:" + device.id + ":")) if (!cmd.result) {
            cmd.result = { ok: false, message: "客户端已重启，旧指令作废" };
            this.put("cmd:" + device.id + ":" + cmd.id, cmd, now() + 7 * 86400);
          }
        }
        device.boot_id = String(data.boot_id);
        this.put("d:" + device.id, device);
        const stopAt = this.list<Schedule>("schedule:").filter(s => s.device_id === device!.id && s.action === "stop" && s.due > now()).sort((a, b) => a.due - b.due)[0]?.due ?? null;
        ws.send(JSON.stringify({ type: "reconcile", protocol: 1, desired: device.desired, version: device.version, settings: device.settings, stop_at: stopAt }));
        for (const cmd of this.list<Command>("cmd:" + device.id + ":")) if (!cmd.result && cmd.expires_at >= now()) ws.send(JSON.stringify(cmd));
        if (reboot) await this.say(`${device.name} 已重新启动，当前待命。`);
      } else if (data.event === "status") {
        device.state = data;
        if (data.version === device.version && data.settings) device.settings = settings({ ...data.settings,
          thread_name: data.settings.thread_name ?? (data.settings.thread_id === device.settings.thread_id ? device.settings.thread_name : null) });
        if (data.version === device.version && (!data.task || ["stopped", "paused"].includes(data.task.phase))) device.desired = "stopped";
        this.put("d:" + device.id, device);
        if (data.notice && !data.task) {
          const key = `${data.task?.id}:${data.notice}`;
          if (key !== device.notice_key) {
            device.notice_key = key;
            this.put("d:" + device.id, device);
            await this.say(`${device.name}：${String(data.notice).slice(0, 300)}`);
          }
        }
        await this.runCard(device.id);
        await this.card(device.id, false);
      } else if (data.event === "ack") {
        const key = "cmd:" + device.id + ":" + data.command_id;
        const cmd = this.get<Command>(key);
        if (!cmd || cmd.result) return;
        if (cmd.action === "delete_session" && data.ok && data.deleted_thread_id !== cmd.payload.thread_id) {
          data.ok = false; data.message = "删除结果未匹配目标会话，请刷新列表核对";
        }
        cmd.result = data;
        this.put(key, cmd, now() + 7 * 86400);
        if (cmd.action === "delete_session" && device.session_delete?.command_id === cmd.id) {
          delete device.session_delete;
          if (data.ok && data.deleted_thread_id === cmd.payload.thread_id) {
            if (device.settings.thread_id === data.deleted_thread_id) device.settings = settings({ ...device.settings, thread_id: null, thread_name: null });
            if (data.cleared_task) { delete device.run_command_id; if (device.state) device.state.task = null; this.del("run:" + device.id); }
            this.ctx.storage.sql.exec("DELETE FROM records WHERE (key LIKE 'session:%' OR key LIKE 'cursor:%' OR key LIKE 'delete-session:%') AND json_extract(value, '$.device_id')=?", device.id);
          }
          this.put("d:" + device.id, device);
          if (data.ok && data.deleted_thread_id === cmd.payload.thread_id) {
            await this.say(`${device.name}：已删除会话 ${cmd.payload.thread_name || "未命名会话"}\n会话 ID：${data.deleted_thread_id}`, [[button("选择会话", "sessions:" + device.id), button("控制面板", "d:" + device.id)]], true);
            const panel = this.get<Panel>("panel");
            if (panel?.device_id === device.id && panel.view === "delete_pending") await this.card(device.id);
            return;
          }
        }
        if (!data.ok) {
          if (cmd.action === "start" && cmd.version === device.version) { device.desired = "stopped"; this.put("d:" + device.id, device); }
          await this.say(`${device.name}：${String(data.message || "操作失败").slice(0, 300)}`);
        } else if (data.sessions) await this.sessionList(device, data.sessions, data.cursor);
        else if (data.diagnostics) await this.say(`${device.name} 诊断\nCodex：${data.diagnostics.version}\n登录：${data.diagnostics.auth_detail || (data.diagnostics.logged_in ? "正常" : "需要登录")}\n路径：${data.diagnostics.codex}\n平台：${data.diagnostics.platform}`, undefined, true);
      }
    } catch {
      // Do not log tokens, prompts, or transcript contents.
    }
  }
  async webSocketClose(ws: WebSocket, code: number, reason: string, clean: boolean) {
    const info = ws.deserializeAttachment();
    const device = this.get<Device>("d:" + info?.device_id);
    if (device && device.connection === info.connection) {
      device.seen = 0;
      this.put("d:" + device.id, device);
      await this.arm();
    }
  }
  async webSocketError(ws: WebSocket) { ws.close(1011, "connection error"); }
  async arm() {
    const earliest = this.list<Schedule>("schedule:").reduce((value, item) => Math.min(value, item.due * 1000), Date.now() + 60000);
    const current = await this.ctx.storage.getAlarm();
    if (current === null || current > earliest) await this.ctx.storage.setAlarm(Math.max(Date.now() + 100, earliest));
  }
  async alarm() {
    try {
    this.ctx.storage.sql.exec("DELETE FROM records WHERE expires IS NOT NULL AND expires < ?", now());
    for (const command of this.list<Command>("cmd:")) {
      if (command.result || command.expires_at >= now()) continue;
      const device = this.get<Device>("d:" + command.device_id);
      const applied = command.action === "start" && device?.state?.task?.id === command.id;
      command.result = { ok: !!applied, message: applied ? "已由状态确认" : "指令已过期且未确认，不补执行" };
      this.put("cmd:" + command.device_id + ":" + command.id, command, now() + 7 * 86400);
      if (!device || applied) continue;
      if (command.action === "delete_session" && device.session_delete?.command_id === command.id) {
        delete device.session_delete;
        this.put("d:" + device.id, device);
      }
      if (command.action === "start" && command.version === device.version) {
        device.desired = "stopped";
        this.put("d:" + device.id, device);
        this.socket(device)?.send(JSON.stringify({ type: "reconcile", protocol: 1, desired: "stopped", version: device.version, settings: device.settings }));
      }
      if (!["stop", "settings", "deadline", "revoke"].includes(command.action)) this.ctx.waitUntil(this.notify(`${device.name}：${command.result.message}`));
    }
    for (const schedule of this.list<Schedule>("schedule:")) {
      if (schedule.due > now()) continue;
      const onTime = now() - schedule.due <= 60;
      if (schedule.kind === "daily") {
        do { schedule.due += 86400; } while (schedule.due <= now());
        this.put("schedule:" + schedule.id, schedule);
      } else this.del("schedule:" + schedule.id);
      const device = this.get<Device>("d:" + schedule.device_id);
      if (!device) continue;
      try {
        if (schedule.action === "stop") await this.issue(device.id, "stop", { reason: "定时停止" });
        else if (onTime && this.online(device)) await this.issue(device.id, "start", {});
        else this.ctx.waitUntil(this.notify(`${device.name}：错过定时启动（离线或调度延迟），不补执行。`));
      } catch (e) { this.ctx.waitUntil(this.notify(`${device.name} 定时操作：${e instanceof Error ? e.message : "失败"}`)); }
    }
    for (let device of this.list<Device>("d:")) {
      if (!this.online(device) && !device.offline_notified) {
        device.offline_notified = true;
        this.put("d:" + device.id, device);
        this.ctx.waitUntil(this.notify(`${device.name} 已离线。客户端若仍在运行，将自行按保持期限停止。`));
        this.ctx.waitUntil(this.card(device.id, false).catch(() => undefined));
      }
    }
    } finally {
      if (this.list<Device>("d:").length || this.list<Schedule>("schedule:").length) await this.arm();
    }
  }
  async issue(deviceId: string, action: string, payload: any): Promise<Command> {
    const device = this.device(deviceId);
    if (device.session_delete && ["start", "settings", "delete_session", "update", "restart"].includes(action)) throw new Error("正在删除会话，请等待完成");
    if (action === "delete_session") {
      if (!device.state?.capabilities?.includes("session_delete")) throw new Error("删除会话需要客户端 v0.2.5，请先点更新程序");
      if (device.desired === "running" || (device.state?.task && !["stopped", "paused"].includes(device.state.task.phase))) throw new Error("请先停止当前任务，再删除会话");
      if (typeof payload.thread_id !== "string" || !payload.thread_id || payload.thread_id.length > 128) throw new Error("无效的会话 ID");
    }
    if (!["stop", "settings", "deadline", "revoke"].includes(action) && !this.online(device)) throw new Error("机器离线，请上线后操作");
    if (action === "start") {
      if (device.desired === "running") throw new Error("机器已有任务，请先停止");
      const actual = settings({ ...device.settings, ...payload.settings,
        ...("thread_id" in (payload.settings || {}) && payload.settings.thread_id !== device.settings.thread_id && !("thread_name" in payload.settings) ? { thread_name: null } : {}) });
      if (!actual.cwd) throw new Error("请先设置工作目录");
      device.settings = actual;
      const nextStop = this.list<Schedule>("schedule:").filter(s => s.device_id === deviceId && s.action === "stop" && s.due > now()).sort((a, b) => a.due - b.due)[0];
      payload = { ...payload, settings: actual, stop_at: nextStop?.due ?? null };
      device.desired = "running";
    }
    if (action === "stop" || ["restart", "update", "revoke"].includes(action)) device.desired = "stopped";
    if (action === "settings") {
      if (device.desired === "running" && ("cwd" in payload || "thread_id" in payload)) throw new Error("修改目录或会话前请先停止任务");
      device.settings = settings({ ...device.settings, ...payload,
        ...("thread_id" in payload && payload.thread_id !== device.settings.thread_id && !("thread_name" in payload) ? { thread_name: null } : {}) });
    }
    device.version++;
    const command: Command = { type: "command", protocol: 1, id: id(), device_id: deviceId, version: device.version, action, payload, expires_at: now() + 60 };
    if (action === "start") device.run_command_id = command.id;
    if (action === "delete_session") device.session_delete = { command_id: command.id, thread_id: payload.thread_id };
    this.put("d:" + deviceId, device);
    this.put("cmd:" + deviceId + ":" + command.id, command, now() + 7 * 86400);
    this.socket(device)?.send(JSON.stringify(command));
    await this.arm();
    if (action === "start" || action === "stop") this.ctx.waitUntil(this.runCard(deviceId).catch(() => undefined));
    return command;
  }
  async runCard(deviceId: string, force = false, anchor?: number) {
    const work = (this.runQueues.get(deviceId) ?? Promise.resolve()).catch(() => undefined).then(async () => {
      const device = this.get<Device>("d:" + deviceId);
      if (!device || (!force && !device.state?.task && !device.run_command_id)) return;
      const status = runtimeStatus(device);
      const previous = this.get<RunCard>("run:" + deviceId);
      const nextAttempt = previous && status.attempt > previous.attempt && previous.attempt > 0;
      const fresh = !previous || previous.task_id !== status.runId || nextAttempt;
      let messageId = anchor ?? (fresh ? undefined : previous.message_id);
      const panel = this.get<Panel>("panel");
      // A user can turn this status message into a menu. Do not overwrite it.
      if (!force && panel && messageId === panel.message_id && panel.view !== "run") return;
      const text = `🖥 ${device.name}${this.online(device) ? " · 在线" : " · 离线（最近上报状态）"}\n${status.lines.join("\n")}\n保持：${device.settings.hold_minutes === null ? "不限时" : device.settings.hold_minutes + " 分钟"} · 间隔：${device.settings.interval_minutes} 分钟`;
      const rows: Rows = [
        [button("⏸ 停止", `runstop:${deviceId}:${status.runId}`), button("▶ 继续", `runcontinue:${deviceId}:${status.runId}`)],
        [button("控制面板", "d:" + deviceId), button("返回主页面", "home")],
      ];
      const signature = JSON.stringify([text, rows]);
      if (messageId === previous?.message_id && previous?.signature === signature && (panel?.message_id !== messageId || panel?.view === "run")) return;
      if (messageId) {
        try { await this.telegram("editMessageText", { chat_id: this.env.CHAT_ID, message_id: messageId, text, reply_markup: { inline_keyboard: rows } }); }
        catch { messageId = undefined; }
      }
      if (!messageId) messageId = (await this.say(text, rows, true)).message_id;
      this.put("run:" + deviceId, { message_id: messageId, task_id: status.runId, attempt: status.attempt, signature });
      if (panel?.message_id === messageId) this.put("panel", { message_id: messageId, view: "run", device_id: deviceId, signature });
    });
    this.runQueues.set(deviceId, work);
    try { await work; }
    finally { if (this.runQueues.get(deviceId) === work) this.runQueues.delete(deviceId); }
  }
  async renderPanel(view: string, deviceId: string | undefined, text: string, rows: Rows, background = false, fresh = false, anchor?: number) {
    const work = (this.panelQueue ?? Promise.resolve()).catch(() => undefined).then(async () => {
      const previous = fresh ? undefined : this.get<Panel>("panel");
      // A status from another machine must never replace the panel being used.
      if (background && (previous?.view !== "device" || previous.device_id !== deviceId)) return;
      const signature = JSON.stringify([text, rows]);
      if ((!anchor || previous?.message_id === anchor) && previous?.signature === signature && previous.view === view && previous.device_id === deviceId) return;
      let messageId = anchor ?? previous?.message_id;
      if (messageId) {
        try {
          await this.telegram("editMessageText", { chat_id: this.env.CHAT_ID, message_id: messageId, text, reply_markup: { inline_keyboard: rows } });
        } catch { messageId = undefined; }
      }
      if (!messageId) messageId = (await this.say(text, rows, true)).message_id;
      this.put("panel", { message_id: messageId, view, device_id: deviceId, signature });
    });
    this.panelQueue = work;
    try { await work; }
    finally { if (this.panelQueue === work) this.panelQueue = undefined; }
  }
  async home(fresh = false, messageId?: number) {
    this.del("input");
    this.cancelDeletionConfirmation();
    this.del("batch");
    const devices = this.list<Device>("d:");
    const rows: Rows = devices.map(d => [button(`${this.online(d) ? "🟢" : "⚫"} ${d.name} · ${d.desired === "running" ? "运行中" : "待命"}`, "d:" + d.id)]);
    rows.push([button("添加机器", "add"), button("刷新机器", "home")]);
    await this.renderPanel("machines", undefined, `机器管理 · ${devices.filter(d => this.online(d)).length}/${devices.length} 台在线\n点击机器名称，控制这台机器。`, rows, false, fresh, messageId);
  }
  async card(deviceId: string, create = true, messageId?: number) {
    const device = this.device(deviceId);
    const runtime = runtimeStatus(device);
    const text = `${this.online(device) ? "🟢" : "⚫"} ${device.name}\n${sessionLines(device.settings, "当前选择").join("\n")}\n客户端：${device.state?.agent_version || "等待上报"}\n${runtime.lines.join("\n")}\n目录：${device.settings.cwd || "未设置"}\n保持：${device.settings.hold_minutes === null ? "不限时" : device.settings.hold_minutes + " 分钟"}\n成功后发送间隔：${device.settings.interval_minutes} 分钟`;
    const rows: Rows = [
      [button("开始", "start:" + deviceId), button("立即停止", "stop:" + deviceId)],
      [button("选择会话", "sessions:" + deviceId), button("新建并开始", "new:" + deviceId)],
      [button("删除当前会话", "deletecurrent:" + deviceId)],
      [button(`保持：${device.settings.hold_minutes === null ? "不限时" : device.settings.hold_minutes + " 分钟"}`, "hold:" + deviceId), button(`间隔：${device.settings.interval_minutes} 分钟`, "interval:" + deviceId)],
      [button("发送内容", "prompt:" + deviceId), button("工作目录", "cwd:" + deviceId)],
      [button("重命名", "rename:" + deviceId), button("更新程序", "update:" + deviceId)],
      [button("定时任务", "schedule:" + deviceId), button("更多设置", "manage:" + deviceId)],
      [button("运行状态", "status:" + deviceId), button("刷新状态", "d:" + deviceId)],
      [button("返回主页面 / 机器管理", "home")],
    ];
    await this.renderPanel("device", deviceId, text, rows, !create, false, messageId);
  }
  async ask(type: string, ids: string[], prompt: string, extra = {}, messageId?: number) {
    if (ids.length !== 1) throw new Error("请先选择一台机器");
    this.put("input", { type, ids, ...extra, scope: "device", expires: now() + 600 }, now() + 600);
    await this.renderPanel("input", ids[0], this.device(ids[0]).name + "\n" + prompt + "\n输入 /cancel 取消。", [[button("返回机器", "d:" + ids[0]), button("返回主页面", "home")]], false, false, messageId);
  }
  async sessionList(device: Device, sessions: any[], cursor: string | null) {
    const rows: Rows = [];
    for (const session of sessions.slice(0, 8)) {
      const token = id();
      this.put("session:" + token, { device_id: device.id, ...session }, now() + 600);
      const name = String(session.name || session.preview || session.id).replaceAll("\n", " ").slice(0, 28);
      rows.push([button(`${session.id === device.settings.thread_id ? "✓ " : ""}${name}`, "select:" + token), button("删除", "deletesession:" + token)]);
    }
    if (cursor) {
      const token = id(); this.put("cursor:" + token, { device_id: device.id, cursor }, now() + 600);
      rows.push([button("下一页", "page:" + token)]);
    }
    rows.push([button("新建并开始", "new:" + device.id), button("返回", "d:" + device.id)]);
    await this.say(`${device.name} 的会话\n${sessionLines(device.settings, "当前选择").join("\n")}\n选择后查看详情，再点开始。删除前需确认。`, rows, true);
  }
  async confirmSessionDeletion(deviceId: string, threadId: string, name: string | null, messageId?: number) {
    const device = this.device(deviceId);
    if (!device.state?.capabilities?.includes("session_delete")) throw new Error("删除会话需要客户端 v0.2.5，请先点更新程序");
    if (device.session_delete || device.desired === "running" || (device.state?.task && !["stopped", "paused"].includes(device.state.task.phase))) throw new Error("请先停止当前任务，再删除会话");
    const token = id();
    this.put("delete-session:" + token, { device_id: deviceId, thread_id: threadId, thread_name: name, expires: now() + 600 }, now() + 600);
    this.put("active-delete-confirm", { token, device_id: deviceId }, now() + 600);
    await this.renderPanel("delete_confirm", deviceId,
      `${device.name}\n确认永久删除会话？\n名称：${name || "未命名会话"}\n会话 ID：${threadId}\n将通过 Codex 删除此会话及其派生子会话，无法在本程序恢复。`,
      [[button("确认永久删除", "confirmdelete:" + token)], [button("取消", "d:" + deviceId)]], false, false, messageId);
  }
  cancelDeletionConfirmation(keep?: string) {
    const pending = this.get<{ token: string }>("active-delete-confirm");
    if (pending && pending.token !== keep) { this.del("delete-session:" + pending.token); this.del("active-delete-confirm"); }
  }
  async click(data: string, messageId?: number) {
    const [action, deviceId, arg] = data.split(":");
    this.del("input");
    this.cancelDeletionConfirmation(action === "confirmdelete" ? deviceId : undefined);
    if (action === "home" || legacyBatchActions.has(action)) return this.home(false, messageId);
    if (action === "add") {
      const release = `https://github.com/a06342637/codex-any-bot/releases/download/${this.env.RELEASE_TAG}`;
      const server = this.env.PUBLIC_BASE_URL.replace(/\/$/, "");
      if (!/^https:\/\/[a-zA-Z0-9.-]+$/.test(server) || !/^v\d+\.\d+\.\d+$/.test(this.env.RELEASE_TAG)) throw new Error("托管端地址或发布版本配置无效");
      const win = `powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:TEMP ('anybot-'+[guid]::NewGuid()+'.ps1'); try { Invoke-WebRequest '${release}/install.ps1' -OutFile $p; & $p -Server '${server}' } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }"`;
      const mac = `(p=$(mktemp -t anybot-bootstrap); trap 'rm -f "$p"' EXIT; curl -fLsS '${release}/install.sh' -o "$p" && bash "$p" --server '${server}')`;
      await this.say("在要接入的电脑运行后，输入本机器人的 Bot Token 和你的数字用户 ID。CF 地址已填好；Token 只作绑定校验，不保存在电脑。此命令可用于多台电脑。\n\nWindows（请在 CMD 执行）：\n" + win);
      return this.say("Mac 终端：\n" + mac);
    }
    if (action === "select") {
      const session = this.get<any>("session:" + deviceId);
      if (!session) throw new Error("会话按钮已过期，请重新获取列表");
      const d = this.device(session.device_id);
      if (d.desired === "running") throw new Error("请先停止当前任务，再选择会话");
      const title = String(session.name || session.preview || "").replaceAll("\n", " ").trim().slice(0, 160) || null;
      await this.issue(d.id, "settings", { thread_id: session.id, thread_name: title, cwd: session.cwd || d.settings.cwd });
      await this.say(`已选择会话\n${title || "未命名会话"}\n会话 ID：${session.id}\n目录：${session.cwd}\n更新时间：${session.updatedAt ? localTime(session.updatedAt > 1e12 ? session.updatedAt / 1000 : session.updatedAt) : "未知"}`, undefined, true);
      return this.card(d.id, true, messageId);
    }
    if (action === "deletesession") {
      const session = this.get<any>("session:" + deviceId);
      if (!session) throw new Error("会话列表已过期，请刷新后重试");
      const name = String(session.name || session.preview || "").replaceAll("\n", " ").trim().slice(0, 160) || null;
      return this.confirmSessionDeletion(session.device_id, session.id, name, messageId);
    }
    if (action === "confirmdelete") {
      const target = this.get<any>("delete-session:" + deviceId);
      this.del("delete-session:" + deviceId);
      this.del("active-delete-confirm");
      if (!target || target.expires < now()) throw new Error("删除确认已过期或已使用，请重新选择会话");
      await this.renderPanel("delete_pending", target.device_id, `正在删除：${target.thread_name || "未命名会话"}\n会话 ID：${target.thread_id}\n等待电脑返回删除结果。`, [[button("返回主页面", "home")]], false, false, messageId);
      return this.issue(target.device_id, "delete_session", { thread_id: target.thread_id, thread_name: target.thread_name });
    }
    if (action === "page") {
      const page = this.get<any>("cursor:" + deviceId);
      if (!page) throw new Error("分页已过期，请重新获取列表");
      return this.issue(page.device_id, "sessions", { cursor: page.cursor });
    }
    if (action === "delschedule") {
      const schedule = this.get<Schedule>("schedule:" + deviceId);
      this.del("schedule:" + deviceId);
      if (schedule) await this.syncStopAt(schedule.device_id);
      return this.say("定时任务已取消");
    }
    const device = this.device(deviceId);
    if (action === "deletecurrent") {
      if (!device.settings.thread_id) throw new Error("请先选择要删除的会话");
      return this.confirmSessionDeletion(deviceId, device.settings.thread_id, device.settings.thread_name, messageId);
    }
    if (action === "d") { this.del("input"); return this.card(deviceId, true, messageId); }
    if (action === "status") return this.runCard(deviceId, true, messageId);
    if (action === "runstop" || action === "runcontinue") {
      const status = runtimeStatus(device);
      if (arg !== status.runId) {
        await this.say("这是历史任务记录，请使用最新运行状态卡。", [[button("当前运行状态", "status:" + deviceId)]], true);
        return;
      }
      if (action === "runstop") await this.issue(deviceId, "stop", {});
      else if (status.phase === "stopping") throw new Error("正在停止上一轮，请稍后再点继续");
      else if (device.desired !== "running") await this.issue(deviceId, "start", {});
      return this.runCard(deviceId, true, messageId);
    }
    if (action === "start" || action === "stop") {
      await this.issue(deviceId, action, {});
      await this.runCard(deviceId);
      return this.card(deviceId, true, messageId);
    }
    if (["sessions", "diagnose", "restart", "update"].includes(action)) {
      await this.issue(deviceId, action, {});
      return this.say(`${device.name}：${{ sessions: "正在读取会话", diagnose: "正在诊断", restart: "正在重启客户端", update: "正在更新程序" }[action]}`, undefined, true);
    }
    if (action === "new") {
      if (device.desired === "running") throw new Error("请先停止当前任务");
      const dirs = this.get<string[]>("dirs:" + deviceId) || [];
      this.put("input", { type: "new", scope: "device", ids: [deviceId], expires: now() + 600 }, now() + 600);
      return this.say(`新会话目录：输入本机绝对路径，或选择常用目录。\n当前目录：${device.settings.cwd || "未设置"}\n/cancel 取消`, [
        ...(device.settings.cwd ? [[button("使用当前目录并开始", "newhere:" + deviceId)]] : []),
        ...dirs.map((dir, i) => [button(dir.slice(-40), `newdir:${deviceId}:${i}`)]),
      ], true);
    }
    if (["newhere", "newdir"].includes(action)) {
      this.del("input");
      const cwd = action === "newhere" ? device.settings.cwd : (this.get<string[]>("dirs:" + deviceId) || [])[Number(arg)];
      if (!cwd) throw new Error("目录已失效，请重新选择");
      await this.issue(deviceId, "start", { settings: { thread_id: null, cwd } });
      return this.card(deviceId, true, messageId);
    }
    if (action === "hold" || action === "interval") {
      const values = action === "hold" ? [10, 30, 60, 120] : [1, 2, 5, 10];
      const current = action === "hold" ? device.settings.hold_minutes : device.settings.interval_minutes;
      const rows = values.map(value => [button(`${current === value ? "✓ " : ""}${value} 分钟`, `set${action}:${deviceId}:${value}`)]);
      if (action === "hold") rows.push([button(`${current === null ? "✓ " : ""}不限时`, `sethold:${deviceId}:none`)]);
      rows.push([button("自定义分钟", `custom${action}:${deviceId}`)]);
      rows.push([button("返回机器", "d:" + deviceId), button("切换机器", "home")]);
      return this.renderPanel(action, deviceId, `${device.name} · ${action === "hold" ? "保持时长（从首次成功开始）" : "发送间隔（仅在成功后等待）"}\n当前：${current === null ? "不限时" : current + " 分钟"}`, rows, false, false, messageId);
    }
    if (action === "sethold" || action === "setinterval") {
      await this.issue(deviceId, "settings", { [action === "sethold" ? "hold_minutes" : "interval_minutes"]: arg === "none" ? null : Number(arg) });
      return this.card(deviceId, true, messageId);
    }
    if (["customhold", "custominterval", "prompt", "cwd", "rename"].includes(action)) {
      const type = action.replace("custom", "");
      const prompts: Record<string, string> = { hold: "请输入保持分钟数，或 不限时", interval: "请输入发送间隔分钟数", prompt: "请输入每轮发送的内容", cwd: "请输入该机器的绝对工作目录", rename: "请输入新的机器名称" };
      if (type === "cwd" && device.desired === "running") throw new Error("修改目录前请先停止当前任务");
      return this.ask(type, [deviceId], prompts[type], {}, messageId);
    }
    if (action === "manage") return this.renderPanel("manage", deviceId, device.name + " · 更多设置", [
      [button("重命名", "rename:" + deviceId), button("更新程序", "update:" + deviceId)],
      [button("诊断", "diagnose:" + deviceId), button("重启客户端", "restart:" + deviceId)],
      [button("移除绑定", "remove:" + deviceId), button("返回机器", "d:" + deviceId)],
      [button("返回主页面", "home")],
    ], false, false, messageId);
    if (action === "remove") return this.say(`移除 ${device.name} 后凭据失效；若在线将停止客户端，离线时无法立即中断已在执行的一轮。`, [[button("确认移除", "confirmremove:" + deviceId), button("取消", "d:" + deviceId)]]);
    if (action === "confirmremove") {
      await this.issue(deviceId, "revoke", {});
      await this.eraseDevice(deviceId);
      return this.say(`${device.name} 的绑定、参数和定时记录已移除。电脑上的文件请使用本机卸载命令清理。`);
    }
    if (action === "schedule") {
      const rows: Rows = [[button("添加定时启动", "schedstart:" + deviceId), button("添加定时停止", "schedstop:" + deviceId)]];
      for (const item of this.list<Schedule>("schedule:").filter(s => s.device_id === deviceId)) rows.push([button(`取消 ${item.action === "start" ? "启动" : "停止"} ${item.kind === "daily" ? "每天 " + item.time : localTime(item.due)}`, "delschedule:" + item.id)]);
      return this.say(`${device.name} · 定时任务（北京时间）`, rows, true);
    }
    if (action === "schedstart" || action === "schedstop") return this.ask(action, [deviceId], "请输入 YYYY-MM-DD HH:MM 或 每天 HH:MM，时间使用北京时间", {}, messageId);
    throw new Error("按钮已失效，请刷新机器列表");
  }
  async syncStopAt(deviceId: string) {
    const device = this.device(deviceId);
    const next = this.list<Schedule>("schedule:").filter(s => s.device_id === deviceId && s.action === "stop" && s.due > now()).sort((a, b) => a.due - b.due)[0];
    // A dedicated command updates the active task's local deadline, including offline recovery.
    this.put("stopat:" + deviceId, next?.due ?? null);
    if (device.desired === "running") await this.issue(deviceId, "deadline", { stop_at: next?.due ?? null });
  }
  async text(input: string) {
    input = input.trim();
    if (["/start", "/machines", "/menu"].includes(input.split("@")[0])) return this.home(true);
    if (input === "/cancel") {
      const deviceId = this.get<Panel>("panel")?.device_id;
      this.del("input");
      this.cancelDeletionConfirmation();
      return deviceId && this.get("d:" + deviceId) ? this.card(deviceId) : this.home();
    }
    if (input === "/stopall") return this.home();
    const context = this.get<any>("input");
    if (!context || context.expires < now()) return this.say("使用 /start 打开机器面板。", undefined, true);
    if (context.scope !== "device" || !Array.isArray(context.ids) || context.ids.length !== 1) return this.home();
    if (context.type === "hold") settings({ hold_minutes: input === "不限时" ? null : Number(input) });
    if (context.type === "interval") settings({ interval_minutes: Number(input) });
    const results = [];
    for (const did of context.ids as string[]) {
      try {
      const device = this.device(did);
      if (context.type === "rename") {
        if (!input || input.length > 60) throw new Error("名称须为 1–60 字符");
        device.name = input; this.put("d:" + did, device);
      } else if (context.type === "new") {
        await this.issue(did, "start", { settings: { thread_id: null, cwd: input } });
        this.rememberDir(did, input);
      } else if (context.type.startsWith("sched")) {
        const schedule: Schedule = { id: id(), device_id: did, action: context.type === "schedstart" ? "start" : "stop", ...parseSchedule(input) };
        this.put("schedule:" + schedule.id, schedule);
        await this.arm();
        if (schedule.action === "stop") await this.syncStopAt(did);
      } else {
        const key = ({ hold: "hold_minutes", interval: "interval_minutes", cwd: "cwd", prompt: "prompt" } as Record<string, string>)[context.type];
        if (!key) throw new Error("输入已失效");
        const value = context.type === "hold" && input === "不限时" ? null : ["hold", "interval"].includes(context.type) ? Number(input) : input;
        await this.issue(did, "settings", { [key]: value });
        if (context.type === "cwd") this.rememberDir(did, input);
      }
      results.push(`${device.name}：已保存`);
      await this.card(did);
      } catch (error) {
        results.push(`${this.get<Device>("d:" + did)?.name || did}：${error instanceof Error ? error.message : "失败"}`);
      }
    }
    this.del("input");
    return this.say(results.join("\n"), undefined, true);
  }
  rememberDir(deviceId: string, path: string) {
    const dirs = this.get<string[]>("dirs:" + deviceId) || [];
    this.put("dirs:" + deviceId, [path, ...dirs.filter(d => d !== path)].slice(0, 5));
  }
}
