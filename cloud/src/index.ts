import { DurableObject } from "cloudflare:workers";
import { authorized, defaults, hash, id, localTime, now, parseSchedule, secret, settings, type Command, type Device, type Schedule, type Settings } from "./model";

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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/healthz") return json({ ok: true, protocol: 1 });
    if (!["/telegram/webhook", "/v1/enroll", "/v1/connect"].includes(url.pathname)) return json({ error: "not found" }, 404);
    if (!env.BOT_TOKEN || !env.WEBHOOK_SECRET || !env.CHAT_ID || !env.ALLOWED_USER_ID) return json({ error: "relay not configured" }, 503);
    if (url.pathname === "/telegram/webhook" && (request.method !== "POST" || request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET)) return json({ error: "unauthorized" }, 401);
    return env.HUB.get(env.HUB.idFromName("single-bot")).fetch(request);
  },
} satisfies ExportedHandler<Env>;

export class BotHub extends DurableObject<Env> {
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
      if (!authorized(body, this.env.ALLOWED_USER_ID, this.env.CHAT_ID)) return json({ ok: true });
      if (!Number.isSafeInteger(body.update_id)) return json({ error: "bad update" }, 400);
      if (this.get("u:" + body.update_id)) return json({ ok: true });
      this.put("u:" + body.update_id, true, now() + 7 * 86400);
      await this.arm();
      try {
        if (body.callback_query) {
          await this.telegram("answerCallbackQuery", { callback_query_id: body.callback_query.id });
          await this.click(String(body.callback_query.data ?? ""));
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
    if (typeof body.code !== "string" || !/^[a-f0-9]{64}$/.test(body.code)) return json({ error: "配对码无效" }, 401);
    const key = "enroll:" + await hash(body.code);
    const code = this.get<{ expires: number }>(key);
    if (!code || code.expires < now()) return json({ error: "配对码已过期或已使用" }, 401);
    if (!["win32", "darwin"].includes(body.platform)) return json({ error: "只支持 Windows 和 macOS" }, 400);
    // Consume before the first await: concurrent use cannot enroll twice.
    this.del(key);
    const token = secret();
    const device: Device = { id: id(), name: String(body.name || "新机器").slice(0, 60), platform: body.platform,
      token_hash: await hash(token), settings: settings({ ...defaults, cwd: String(body.cwd || "") }), version: 0, desired: "stopped", seen: 0 };
    this.put("d:" + device.id, device);
    await this.arm();
    this.ctx.waitUntil(this.say(`已添加 ${device.name}，等待客户端上线。`, [[button("查看机器", "d:" + device.id)]]));
    return json({ device_id: device.id, token, protocol: 1 });
  }
  async connectDevice(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") return json({ error: "websocket required" }, 426);
    const device = this.get<Device>("d:" + request.headers.get("X-Device-ID"));
    const token = request.headers.get("Authorization")?.replace(/^Bearer /, "") ?? "";
    if (!device || !token || await hash(token) !== device.token_hash) return json({ error: "unauthorized" }, 401);
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
        if (data.version === device.version && data.settings) device.settings = settings(data.settings);
        if (data.version === device.version && (!data.task || ["stopped", "paused"].includes(data.task.phase))) device.desired = "stopped";
        this.put("d:" + device.id, device);
        if (data.notice) {
          const key = `${data.task?.id}:${data.notice}`;
          if (key !== device.notice_key) {
            device.notice_key = key;
            this.put("d:" + device.id, device);
            await this.say(`${device.name}：${String(data.notice).slice(0, 300)}`);
          }
        }
        await this.card(device.id, false);
      } else if (data.event === "ack") {
        const key = "cmd:" + device.id + ":" + data.command_id;
        const cmd = this.get<Command>(key);
        if (!cmd || cmd.result) return;
        cmd.result = data;
        this.put(key, cmd, now() + 7 * 86400);
        if (!data.ok) {
          if (cmd.action === "start" && cmd.version === device.version) { device.desired = "stopped"; this.put("d:" + device.id, device); }
          await this.say(`${device.name}：${String(data.message || "操作失败").slice(0, 300)}`);
        } else if (data.sessions) await this.sessionList(device, data.sessions, data.cursor);
        else if (data.diagnostics) await this.say(`${device.name} 诊断\nCodex：${data.diagnostics.version}\n登录：${data.diagnostics.logged_in ? "正常" : "需要登录"}\n路径：${data.diagnostics.codex}\n平台：${data.diagnostics.platform}`, undefined, true);
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
    this.ctx.storage.sql.exec("DELETE FROM records WHERE expires IS NOT NULL AND expires < ?", now());
    for (const command of this.list<Command>("cmd:")) {
      if (command.result || command.expires_at >= now()) continue;
      const device = this.get<Device>("d:" + command.device_id);
      const applied = command.action === "start" && device?.state?.task?.id === command.id;
      command.result = { ok: !!applied, message: applied ? "已由状态确认" : "指令已过期且未确认，不补执行" };
      this.put("cmd:" + command.device_id + ":" + command.id, command, now() + 7 * 86400);
      if (!device || applied) continue;
      if (command.action === "start" && command.version === device.version) {
        device.desired = "stopped";
        this.put("d:" + device.id, device);
        this.socket(device)?.send(JSON.stringify({ type: "reconcile", protocol: 1, desired: "stopped", version: device.version, settings: device.settings }));
      }
      if (!["stop", "settings", "deadline", "revoke"].includes(command.action)) await this.say(`${device.name}：${command.result.message}`);
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
        else await this.say(`${device.name}：错过定时启动（离线或调度延迟），不补执行。`);
      } catch (e) { await this.say(`${device.name} 定时操作：${e instanceof Error ? e.message : "失败"}`); }
    }
    for (let device of this.list<Device>("d:")) {
      if (!this.online(device) && !device.offline_notified) {
        device.offline_notified = true;
        this.put("d:" + device.id, device);
        await this.say(`${device.name} 已离线。客户端若仍在运行，将自行按保持期限停止。`);
        await this.card(device.id, false);
      }
    }
    if (this.list<Device>("d:").length || this.list<Schedule>("schedule:").length) await this.arm();
  }
  async issue(deviceId: string, action: string, payload: any): Promise<Command> {
    const device = this.device(deviceId);
    if (!["stop", "settings", "deadline", "revoke"].includes(action) && !this.online(device)) throw new Error("机器离线，请上线后操作");
    if (action === "start") {
      if (device.desired === "running") throw new Error("机器已有任务，请先停止");
      const actual = settings({ ...device.settings, ...payload.settings });
      if (!actual.cwd) throw new Error("请先设置工作目录");
      device.settings = actual;
      const nextStop = this.list<Schedule>("schedule:").filter(s => s.device_id === deviceId && s.action === "stop" && s.due > now()).sort((a, b) => a.due - b.due)[0];
      payload = { ...payload, settings: actual, stop_at: nextStop?.due ?? null };
      device.desired = "running";
    }
    if (action === "stop" || ["restart", "update", "revoke"].includes(action)) device.desired = "stopped";
    if (action === "settings") {
      if (device.desired === "running" && ("cwd" in payload || "thread_id" in payload)) throw new Error("修改目录或会话前请先停止任务");
      device.settings = settings({ ...device.settings, ...payload });
    }
    device.version++;
    this.put("d:" + deviceId, device);
    const command: Command = { type: "command", protocol: 1, id: id(), device_id: deviceId, version: device.version, action, payload, expires_at: now() + 60 };
    this.put("cmd:" + deviceId + ":" + command.id, command, now() + 7 * 86400);
    this.socket(device)?.send(JSON.stringify(command));
    await this.arm();
    return command;
  }
  async home() {
    const devices = this.list<Device>("d:");
    const rows: Rows = devices.map(d => [button(`${this.online(d) ? "🟢" : "⚫"} ${d.name} · ${d.desired === "running" ? "运行中" : "待命"}`, "d:" + d.id)]);
    rows.push([button("添加机器", "add"), button("刷新", "home")], [button("批量操作", "batch"), button("全部停止", "stopall")]);
    await this.say(`我的机器 · ${devices.filter(d => this.online(d)).length}/${devices.length} 台在线`, rows, true);
  }
  async card(deviceId: string, create = true) {
    const device = this.device(deviceId);
    if (!create && !device.card_id) return;
    const task = device.state?.task;
    const phase: Record<string, string> = { waiting: "等待开始", running: "执行中", holding: "保持中", retrying: "等待重试", stopping: "正在停止", stopped: "已停止", paused: "异常暂停" };
    const active = task && !["stopped", "paused"].includes(task.phase);
    const text = `${this.online(device) ? "🟢" : "⚫"} ${device.name}\n状态：${phase[task?.phase] || "待命"}\n会话：${device.settings.thread_id || "新建会话"}\n目录：${device.settings.cwd || "未设置"}\n保持：${device.settings.hold_minutes === null ? "不限时" : device.settings.hold_minutes + " 分钟"}\n发送间隔：${device.settings.interval_minutes} 分钟\n已完成：${task?.rounds || 0} 轮${active && task.first_success_at ? `\n已保持：${Math.max(0, Math.floor((now() - task.first_success_at) / 60))} 分钟` : ""}${active && task.deadline ? `\n剩余：${Math.max(0, Math.ceil((task.deadline - now()) / 60))} 分钟\n停止时间：${localTime(task.deadline)}` : ""}${active && task.phase !== "running" && task.next_at ? `\n下次发送：${localTime(task.next_at)}` : ""}${task?.reason ? `\n说明：${task.reason}` : ""}`;
    const rows: Rows = [
      [button("开始", "start:" + deviceId), button("立即停止", "stop:" + deviceId)],
      [button("选择会话", "sessions:" + deviceId), button("新建并开始", "new:" + deviceId)],
      [button("保持时长", "hold:" + deviceId), button("发送间隔", "interval:" + deviceId)],
      [button("发送内容", "prompt:" + deviceId), button("工作目录", "cwd:" + deviceId)],
      [button("定时任务", "schedule:" + deviceId), button("机器设置", "manage:" + deviceId)],
      [button("刷新", "d:" + deviceId), button("机器列表", "home")],
    ];
    if (device.card_id) {
      if (!create && device.card_text === text) return;
      try {
        await this.telegram("editMessageText", { chat_id: this.env.CHAT_ID, message_id: device.card_id, text, reply_markup: { inline_keyboard: rows } });
      } catch {
        if (!create) return;
        const result = await this.say(text, rows, true);
        device.card_id = result.message_id;
      }
    } else {
      const result = await this.say(text, rows, true);
      device.card_id = result.message_id;
    }
    // Re-read after network I/O so a concurrent status cannot be overwritten.
    const fresh = this.device(deviceId);
    fresh.card_id = device.card_id; fresh.card_text = text;
    this.put("d:" + deviceId, fresh);
  }
  async ask(type: string, ids: string[], prompt: string, extra = {}) {
    this.put("input", { type, ids, ...extra, expires: now() + 600 }, now() + 600);
    await this.say(prompt + "\n输入 /cancel 取消。", undefined, true);
  }
  async sessionList(device: Device, sessions: any[], cursor: string | null) {
    const rows: Rows = [];
    for (const session of sessions.slice(0, 8)) {
      const token = id();
      this.put("session:" + token, { device_id: device.id, ...session }, now() + 600);
      const name = String(session.name || session.preview || session.id).replaceAll("\n", " ").slice(0, 28);
      rows.push([button(name, "select:" + token)]);
    }
    if (cursor) {
      const token = id(); this.put("cursor:" + token, { device_id: device.id, cursor }, now() + 600);
      rows.push([button("下一页", "page:" + token)]);
    }
    rows.push([button("新建并开始", "new:" + device.id), button("返回", "d:" + device.id)]);
    await this.say(`${device.name} 的会话（选择后查看详情，再点开始）`, rows, true);
  }
  async batch() {
    const selected = this.get<string[]>("batch") || [];
    const rows: Rows = this.list<Device>("d:").map(d => [button(`${selected.includes(d.id) ? "☑" : "☐"} ${d.name}`, "toggle:" + d.id)]);
    rows.push([button("启动选中", "batchstart"), button("停止选中", "batchstop")],
      [button("统一保持分钟", "batchhold"), button("统一间隔分钟", "batchinterval")], [button("返回", "home")]);
    await this.say("选择机器；批量启动使用每台各自保存的会话和参数。", rows, true);
  }
  async click(data: string) {
    const [action, deviceId, arg] = data.split(":");
    if (action === "home") return this.home();
    if (action === "add") {
      const code = secret();
      this.put("enroll:" + await hash(code), { expires: now() + 600 }, now() + 600);
      const release = `https://github.com/a06342637/codex-any-bot/releases/download/${this.env.RELEASE_TAG}`;
      const server = this.env.PUBLIC_BASE_URL.replace(/\/$/, "");
      if (!/^https:\/\/[a-zA-Z0-9.-]+$/.test(server) || !/^v\d+\.\d+\.\d+$/.test(this.env.RELEASE_TAG)) throw new Error("托管端地址或发布版本配置无效");
      const win = `powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:TEMP ('anybot-'+[guid]::NewGuid()+'.ps1'); Invoke-WebRequest '${release}/install.ps1' -OutFile $p; & $p -Server '${server}' -Code '${code}'"`;
      const mac = `p=$(mktemp); curl -fLsS '${release}/install.sh' -o "$p" && bash "$p" --server '${server}' --code '${code}'; rm -f "$p"`;
      await this.say("一次性配对命令：十分钟内有效，任选一台机器使用。\n\nWindows CMD / PowerShell：\n" + win);
      return this.say("Mac 终端：\n" + mac);
    }
    if (action === "batch") return this.batch();
    if (action === "toggle") {
      this.device(deviceId);
      const ids = this.get<string[]>("batch") || [];
      this.put("batch", ids.includes(deviceId) ? ids.filter(x => x !== deviceId) : [...ids, deviceId]);
      return this.batch();
    }
    if (["batchstart", "batchstop", "stopall"].includes(action)) {
      const ids = action === "stopall" ? this.list<Device>("d:").map(d => d.id) : this.get<string[]>("batch") || [];
      const results: string[] = [];
      for (const did of ids) {
        try { await this.issue(did, action === "batchstart" ? "start" : "stop", {}); results.push(`${this.device(did).name}：指令已发送${this.online(this.device(did)) ? "" : "，上线后同步停止"}`); }
        catch (e) { results.push(`${this.get<Device>("d:" + did)?.name || did}：${e instanceof Error ? e.message : "失败"}`); }
      }
      return this.say(results.join("\n") || "请先选择机器");
    }
    if (["batchhold", "batchinterval"].includes(action)) {
      const ids = this.get<string[]>("batch") || [];
      if (!ids.length) throw new Error("请先选择机器");
      return this.ask(action === "batchhold" ? "hold" : "interval", ids, "请输入整数分钟" + (action === "batchhold" ? "；不限时请输入 不限时" : ""));
    }
    if (action === "select") {
      const session = this.get<any>("session:" + deviceId);
      if (!session) throw new Error("会话按钮已过期，请重新获取列表");
      const d = this.device(session.device_id);
      if (d.desired === "running") throw new Error("请先停止当前任务，再选择会话");
      await this.issue(d.id, "settings", { thread_id: session.id, cwd: session.cwd || d.settings.cwd });
      await this.say(`已选择会话\n${session.name || session.id}\n目录：${session.cwd}\n更新时间：${session.updatedAt ? localTime(session.updatedAt > 1e12 ? session.updatedAt / 1000 : session.updatedAt) : "未知"}`, undefined, true);
      return this.card(d.id);
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
    if (action === "d") return this.card(deviceId);
    if (action === "start" || action === "stop") {
      await this.issue(deviceId, action, {});
      await this.say(`${device.name}：${action === "start" ? "启动指令已发送" : "停止指令已发送，等待客户端确认"}`, undefined, true);
      return this.card(deviceId);
    }
    if (["sessions", "diagnose", "restart", "update"].includes(action)) {
      await this.issue(deviceId, action, {});
      return this.say(`${device.name}：${{ sessions: "正在读取会话", diagnose: "正在诊断", restart: "正在重启客户端", update: "正在更新客户端" }[action]}`, undefined, true);
    }
    if (action === "new") {
      if (device.desired === "running") throw new Error("请先停止当前任务");
      const dirs = this.get<string[]>("dirs:" + deviceId) || [];
      this.put("input", { type: "new", ids: [deviceId], expires: now() + 600 }, now() + 600);
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
      return this.card(deviceId);
    }
    if (action === "hold" || action === "interval") {
      const values = action === "hold" ? [10, 30, 60, 120] : [1, 2, 5, 10];
      const rows = values.map(value => [button(`${value} 分钟`, `set${action}:${deviceId}:${value}`)]);
      if (action === "hold") rows.push([button("不限时", `sethold:${deviceId}:none`)]);
      rows.push([button("自定义分钟", `custom${action}:${deviceId}`)]);
      return this.say(`${device.name} · ${action === "hold" ? "保持时长（从首次成功开始）" : "发送间隔（上一轮结束后）"}`, rows, true);
    }
    if (action === "sethold" || action === "setinterval") {
      await this.issue(deviceId, "settings", { [action === "sethold" ? "hold_minutes" : "interval_minutes"]: arg === "none" ? null : Number(arg) });
      return this.card(deviceId);
    }
    if (["customhold", "custominterval", "prompt", "cwd", "rename"].includes(action)) {
      const type = action.replace("custom", "");
      const prompts: Record<string, string> = { hold: "请输入保持分钟数，或 不限时", interval: "请输入发送间隔分钟数", prompt: "请输入每轮发送的内容", cwd: "请输入该机器的绝对工作目录", rename: "请输入新的机器名称" };
      if (type === "cwd" && device.desired === "running") throw new Error("修改目录前请先停止当前任务");
      return this.ask(type, [deviceId], prompts[type]);
    }
    if (action === "manage") return this.say(device.name + " · 机器设置", [
      [button("重命名", "rename:" + deviceId), button("诊断", "diagnose:" + deviceId)],
      [button("重启客户端", "restart:" + deviceId), button("更新客户端", "update:" + deviceId)],
      [button("移除绑定", "remove:" + deviceId), button("返回", "d:" + deviceId)],
    ], true);
    if (action === "remove") return this.say(`移除 ${device.name} 后凭据失效；若在线将停止客户端，离线时无法立即中断已在执行的一轮。`, [[button("确认移除", "confirmremove:" + deviceId), button("取消", "d:" + deviceId)]]);
    if (action === "confirmremove") {
      await this.issue(deviceId, "revoke", {});
      for (const ws of this.ctx.getWebSockets(deviceId)) ws.close(4003, "revoked");
      this.del("d:" + deviceId);
      for (const item of this.list<Schedule>("schedule:")) if (item.device_id === deviceId) this.del("schedule:" + item.id);
      return this.say(`${device.name} 已移除。重新接入需要新配对码。`);
    }
    if (action === "schedule") {
      const rows: Rows = [[button("添加定时启动", "schedstart:" + deviceId), button("添加定时停止", "schedstop:" + deviceId)]];
      for (const item of this.list<Schedule>("schedule:").filter(s => s.device_id === deviceId)) rows.push([button(`取消 ${item.action === "start" ? "启动" : "停止"} ${item.kind === "daily" ? "每天 " + item.time : localTime(item.due)}`, "delschedule:" + item.id)]);
      return this.say(`${device.name} · 定时任务（北京时间）`, rows, true);
    }
    if (action === "schedstart" || action === "schedstop") return this.ask(action, [deviceId], "请输入 YYYY-MM-DD HH:MM 或 每天 HH:MM，时间使用北京时间");
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
    if (["/start", "/machines", "/menu"].includes(input.split("@")[0])) { this.del("input"); return this.home(); }
    if (input === "/cancel") { this.del("input"); return this.say("已取消", undefined, true); }
    if (input === "/stopall") return this.click("stopall");
    const context = this.get<any>("input");
    if (!context || context.expires < now()) return this.say("使用 /start 打开机器面板。", undefined, true);
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
