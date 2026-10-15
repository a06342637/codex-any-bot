import { env, SELF, runInDurableObject, reset, evictDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defaults, hash, now, type Device } from "../src/model";
import type { Env, BotHub } from "../src/index";

const bindings = env as unknown as Env;
const hub = () => bindings.HUB.get(bindings.HUB.idFromName("single-bot"));
let calls: any[];
beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: any, init: any) => {
    if (!String(input).startsWith("https://api.telegram.org/")) throw new Error("Unexpected network access");
    calls.push({ url: String(input), body: JSON.parse(init.body) });
    return Response.json({ ok: true, result: { message_id: calls.length } });
  }));
});
afterEach(async () => { vi.unstubAllGlobals(); await reset(); });

async function seed(id = "machine1") {
  await runInDurableObject(hub(), async (instance: BotHub) => {
    const device: Device = { id, name: id, token_hash: await hash("secret-" + id), platform: "win32",
      settings: { ...defaults, cwd: "C:\\work" }, desired: "stopped", version: 0, seen: 0 };
    instance.put("d:" + id, device);
  });
}
async function webhook(update: any, token = "test-secret") {
  return SELF.fetch("https://relay.example.com/telegram/webhook", { method: "POST",
    headers: { "X-Telegram-Bot-Api-Secret-Token": token }, body: JSON.stringify(update) });
}

describe("real SQLite-backed Durable Object", () => {
  it("enrolls multiple computers with owner token and ID without persisting the bot token", async () => {
    const enroll = () => SELF.fetch("https://relay.example.com/v1/enroll", { method: "POST", body: JSON.stringify({ platform: "win32", name: "Windows", cwd: "C:\\work", bot_token: "test-token", user_id: "42" }) });
    const a: any = await (await enroll()).json();
    const b: any = await (await enroll()).json();
    expect(a.device_id).not.toBe(b.device_id);
    expect(a.token).not.toBe("test-token");
    await runInDurableObject(hub(), (instance: BotHub) => {
      expect(JSON.stringify(instance.list("d:"))).not.toContain("test-token");
      expect(instance.list("d:")).toHaveLength(2);
    });
  });
  it("rejects a wrong bot token or owner ID", async () => {
    for (const auth of [{ bot_token: "wrong", user_id: "42" }, { bot_token: "test-token", user_id: "999" }]) {
      const r = await SELF.fetch("https://relay.example.com/v1/enroll", { method: "POST", body: JSON.stringify({ ...auth, platform: "darwin" }) });
      expect(r.status).toBe(401);
    }
  });
  it("uninstall deletes device records, schedules and selections without touching another computer", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), (instance: BotHub) => {
      instance.put("dirs:a", ["C:\\work"]);
      instance.put("stopat:a", 123);
      instance.put("schedule:s", { device_id: "a", id: "s" });
      instance.put("session:s", { device_id: "a", id: "t" });
      instance.put("cmd:a:c", { device_id: "a", id: "c" });
      instance.put("batch", ["a", "b"]);
      instance.put("input", { ids: ["a", "b"], expires: now() + 60 });
    });
    const request = (token: string) => SELF.fetch("https://relay.example.com/v1/unenroll", { method: "POST", headers: { Authorization: "Bearer " + token, "X-Device-ID": "a" }, body: "{}" });
    expect((await request("wrong")).status).toBe(401);
    expect((await request("secret-a")).status).toBe(200);
    await runInDurableObject(hub(), (instance: BotHub) => {
      for (const key of ["d:a", "dirs:a", "stopat:a", "schedule:s", "session:s", "cmd:a:c"]) expect(instance.get(key)).toBeUndefined();
      expect(instance.device("b").id).toBe("b");
      expect(instance.get("batch")).toBeUndefined();
      expect(instance.get<any>("input").ids).toEqual(["b"]);
    });
  });
  it("rejects bad webhook secrets and ignores unauthorized users", async () => {
    expect((await webhook({}, "wrong")).status).toBe(401);
    await webhook({ update_id: 1, message: { from: { id: 999 }, chat: { id: 42 }, text: "/start" } });
    expect(calls).toHaveLength(0);
  });
  it("executes stop even when Telegram callback acknowledgement has expired", async () => {
    await seed();
    const realFetch = globalThis.fetch;
    vi.stubGlobal("fetch", vi.fn(async (url: any, init: any) => {
      if (String(url).endsWith("/answerCallbackQuery")) return Response.json({ ok: false, error_code: 400, description: "query is too old" });
      return realFetch(url, init);
    }));
    await webhook({ update_id: 99, callback_query: { id: "expired", from: { id: 42 }, message: { chat: { id: 42 } }, data: "stop:machine1" } });
    await runInDurableObject(hub(), (instance: BotHub) => {
      expect(instance.list<any>("cmd:machine1:").some(c => c.action === "stop")).toBe(true);
    });
  });
  it("notification failure cannot prevent the next scheduled stop", async () => {
    await seed("a"); await seed("b");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("Telegram temporarily unavailable"); }));
    await runInDurableObject(hub(), async (instance: BotHub, state) => {
      instance.put("schedule:a", { id: "a", device_id: "a", action: "start", kind: "once", due: now() - 2 });
      instance.put("schedule:b", { id: "b", device_id: "b", action: "stop", kind: "once", due: now() - 1 });
      await instance.alarm();
      expect(instance.list<any>("cmd:b:").some(c => c.action === "stop")).toBe(true);
      expect(await state.storage.getAlarm()).not.toBeNull();
    });
  });
  it("deduplicates Telegram updates", async () => {
    const update = { update_id: 2, message: { from: { id: 42 }, chat: { id: 42 }, text: "/start" } };
    await webhook(update); await webhook(update);
    expect(calls).toHaveLength(1);
  });
  it("consumes a pairing code once, also for concurrent requests", async () => {
    const code = "a".repeat(64);
    await runInDurableObject(hub(), async (instance: BotHub) => instance.put("enroll:" + await hash(code), { expires: now() + 600 }));
    const join = () => SELF.fetch("https://relay.example.com/v1/enroll", { method: "POST", body: JSON.stringify({ code, platform: "darwin", name: "Mac", cwd: "/tmp" }) });
    const results = await Promise.all([join(), join()]);
    expect(results.map(r => r.status).sort()).toEqual([200, 401]);
    const data: any = await results.find(r => r.status === 200)!.json();
    expect(data.token).toHaveLength(64);
    await runInDurableObject(hub(), (instance: BotHub) => expect(instance.device(data.device_id).token_hash).not.toBe(data.token));
  });
  it("stores independent settings and retains offline stop intent", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.issue("a", "settings", { hold_minutes: 30, interval_minutes: 1 });
      await instance.issue("b", "settings", { hold_minutes: 120, interval_minutes: 5 });
      await instance.issue("a", "stop", {});
      expect(instance.device("a").desired).toBe("stopped");
      expect(instance.device("a").settings.hold_minutes).toBe(30);
      expect(instance.device("b").settings.hold_minutes).toBe(120);
      await expect(instance.issue("a", "start", {})).rejects.toThrow("离线");
    });
  });
  it("rejects invalid minute settings without modifying saved configuration", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await expect(instance.issue("machine1", "settings", { hold_minutes: -1 })).rejects.toThrow();
      expect(instance.device("machine1").settings.hold_minutes).toBeNull();
    });
  });
  it("discards legacy batch input without changing any machine", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      instance.put("input", { type: "hold", ids: ["a", "removed", "b"], expires: now() + 600 });
      await instance.text("30");
      expect(instance.device("a").settings.hold_minutes).toBeNull();
      expect(instance.device("b").settings.hold_minutes).toBeNull();
      expect(instance.get("input")).toBeUndefined();
    });
    expect(calls.some(c => c.body.text?.includes("机器管理"))).toBe(true);
  });
  it("switches machines in one panel with direct rename and update actions", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.home();
      await instance.click("d:a");
      await instance.click("d:b");
      expect(instance.list("cmd:")).toHaveLength(0);
    });
    expect(calls.filter(c => c.url.endsWith("/sendMessage"))).toHaveLength(1);
    const edits = calls.filter(c => c.url.endsWith("/editMessageText"));
    expect(edits).toHaveLength(2);
    expect(new Set(edits.map(c => c.body.message_id)).size).toBe(1);
    const buttons = edits.at(-1).body.reply_markup.inline_keyboard.flat();
    expect(buttons).toContainEqual({ text: "重命名", callback_data: "rename:b" });
    expect(buttons).toContainEqual({ text: "更新程序", callback_data: "update:b" });
    expect(buttons.some((b: any) => b.callback_data.endsWith(":a"))).toBe(false);
    expect(JSON.stringify(calls)).not.toMatch(/批量操作|全部停止|统一保持/);
  });
  it("shows quick and custom minute changes on buttons and restores them after eviction", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.click("d:a");
      await instance.click("sethold:a:30");
      await instance.click("hold:a");
    });
    expect(calls.at(-1).body.reply_markup.inline_keyboard.flat()).toContainEqual({ text: "✓ 30 分钟", callback_data: "sethold:a:30" });
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.click("custominterval:a");
      await instance.text("3");
      expect(instance.device("b").settings).toEqual({ ...defaults, cwd: "C:\\work" });
    });
    await evictDurableObject(hub());
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.home();
      await instance.click("d:a");
    });
    const buttons = calls.at(-1).body.reply_markup.inline_keyboard.flat();
    expect(buttons).toContainEqual({ text: "保持：30 分钟", callback_data: "hold:a" });
    expect(buttons).toContainEqual({ text: "间隔：3 分钟", callback_data: "interval:a" });
  }, 20000); // Includes forced Durable Object eviction and rehydration.
  it("renames just one machine and cancels stale input when switching", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      const token = instance.device("a").token_hash;
      await instance.click("rename:a");
      await instance.text("家里 Windows");
      await instance.home();
      expect(instance.device("a").name).toBe("家里 Windows");
      expect(instance.device("a").token_hash).toBe(token);
      expect(instance.device("b").name).toBe("b");
      await instance.click("rename:a");
      await instance.click("d:b");
      await instance.text("should-not-rename");
      expect(instance.device("a").name).toBe("家里 Windows");
      expect(instance.device("b").name).toBe("b");
    });
    expect(calls.some(c => c.body.reply_markup?.inline_keyboard.flat().some((b: any) => b.text.includes("家里 Windows")))).toBe(true);
  });
  it("retires all old batch buttons without issuing machine commands", async () => {
    await seed("a"); await seed("b");
    for (const [index, data] of ["batch", "toggle:a", "batchstart", "batchstop", "batchhold", "batchinterval", "stopall"].entries()) {
      await webhook({ update_id: 1000 + index, callback_query: { id: "legacy", from: { id: 42 }, message: { message_id: 999, chat: { id: 42 } }, data } });
    }
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.text("/stopall");
      expect(instance.list("cmd:")).toHaveLength(0);
      expect(instance.get("batch")).toBeUndefined();
    });
    expect(calls.some(c => c.url.endsWith("/editMessageText") && c.body.message_id === 999 && c.body.text.startsWith("机器管理"))).toBe(true);
  });
  it("opens the control page in the exact old message the user clicked", async () => {
    await seed();
    await runInDurableObject(hub(), (instance: BotHub) => instance.home());
    await webhook({ update_id: 2111, callback_query: { id: "old-message", from: { id: 42 }, message: { message_id: 900, chat: { id: 42 } }, data: "d:machine1" } });
    const edit = calls.filter(c => c.url.endsWith("/editMessageText")).at(-1);
    expect(edit.body.message_id).toBe(900);
    expect(edit.body.reply_markup.inline_keyboard.flat()).toContainEqual({ text: "重命名", callback_data: "rename:machine1" });
    await runInDurableObject(hub(), (instance: BotHub) => {
      expect(instance.get<any>("panel").message_id).toBe(900);
    });
  });
  it("can repeatedly navigate between control and runtime pages in the clicked message", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.click("d:machine1", 900);
      await instance.click("status:machine1", 900);
      await instance.click("d:machine1", 900);
      await instance.click("status:machine1", 900);
      expect(instance.get<any>("panel").view).toBe("run");
    });
    const edits = calls.filter(c => c.url.endsWith("/editMessageText"));
    expect(edits).toHaveLength(4);
    expect(edits.every(c => c.body.message_id === 900)).toBe(true);
    expect(edits.at(-1).body.reply_markup.inline_keyboard.flat().some((b: any) => b.text === "控制面板")).toBe(true);
  });
  it("updates each attempt in place and creates a new visible card for the next attempt", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      const d = instance.device("machine1"); d.desired = "running";
      d.state = { version: 0, time: 1000, task: { id: "job", phase: "running", attempts: 1, retry_count: 0, rounds: 0 } };
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      d.state.task.phase = "retrying"; d.state.task.failures = 1; d.state.task.reason = "failed";
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      await instance.runCard(d.id);
      d.state.task.phase = "running"; d.state.task.attempts = 2; d.state.task.retry_count = 1;
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      d.state.task.phase = "holding"; d.state.task.rounds = 1; d.state.task.reason = "";
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
    });
    expect(calls.filter(c => c.url.endsWith("/sendMessage"))).toHaveLength(2);
    expect(calls.filter(c => c.url.endsWith("/editMessageText"))).toHaveLength(2);
    const buttons = calls.at(-1).body.reply_markup.inline_keyboard.flat();
    expect(buttons).toContainEqual({ text: "⏸ 停止", callback_data: "runstop:machine1:job" });
    expect(buttons).toContainEqual({ text: "▶ 继续", callback_data: "runcontinue:machine1:job" });
    expect(buttons).toContainEqual({ text: "控制面板", callback_data: "d:machine1" });
    expect(buttons).toContainEqual({ text: "返回主页面", callback_data: "home" });
  });
  it("does not overwrite a status card that the user has turned into a menu", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      const d = instance.device("machine1"); d.desired = "running";
      d.state = { version: 0, time: 1000, task: { id: "job", phase: "running", attempts: 1 } };
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      const messageId = instance.get<any>("run:machine1").message_id;
      await instance.click("home", messageId);
      d.state.time = 1005;
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      expect(instance.get<any>("panel").view).toBe("machines");
      d.state.task.attempts = 2;
      instance.put("d:machine1", d);
      await instance.runCard(d.id);
      expect(instance.get<any>("run:machine1").message_id).not.toBe(messageId);
      expect(instance.get<any>("panel").message_id).toBe(messageId);
    });
    expect(calls.filter(c => c.url.endsWith("/sendMessage"))).toHaveLength(2);
    expect(calls.filter(c => c.url.endsWith("/editMessageText"))).toHaveLength(1);
  });
  it("continues a stopped task in its selected session and ignores stale task buttons", async () => {
    await seed();
    const response = await SELF.fetch("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": "machine1", Authorization: "Bearer secret-machine1" } });
    const ws = response.webSocket!; ws.accept();
    try {
      await runInDurableObject(hub(), async (instance: BotHub) => {
        const d = instance.device("machine1");
        d.settings.thread_id = "selected-session";
        instance.put("d:machine1", d);
        const first = await instance.issue(d.id, "start", {});
        await instance.click(`runcontinue:${d.id}:${first.id}`);
        expect(instance.list("cmd:machine1:")).toHaveLength(1);
        await instance.issue(d.id, "stop", {});
        const stopped = instance.device(d.id);
        stopped.state = { version: stopped.version, task: { id: first.id, phase: "stopped", attempts: 1 } };
        instance.put("d:machine1", stopped);
        await instance.click(`runcontinue:${d.id}:${first.id}`);
        const current = instance.device(d.id);
        expect(current.run_command_id).not.toBe(first.id);
        expect(current.settings.thread_id).toBe("selected-session");
        await instance.click(`runcontinue:${d.id}:${first.id}`);
        await instance.click(`runstop:${d.id}:${first.id}`);
        expect(instance.list("cmd:machine1:")).toHaveLength(3);
      });
    } finally { ws.close(); }
  });
  it("keeps other machines and status heartbeats from taking over navigation", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.click("d:b");
      await instance.card("a", false);
      await instance.click("hold:b");
      await instance.card("b", false);
      expect(instance.get<any>("panel").view).toBe("hold");
      await instance.home();
      await instance.card("a", false);
      expect(instance.get<any>("panel").view).toBe("machines");
    });
    expect(calls.filter(c => c.body.text?.startsWith("⚫ a"))).toHaveLength(0);
    expect(calls.filter(c => c.url.endsWith("/editMessageText"))).toHaveLength(2);
  });
  it("opens a fresh start panel even when an earlier status edit is still pending", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.home();
      const telegram = instance.telegram.bind(instance);
      let release!: () => void;
      let editing!: () => void;
      const gate = new Promise<void>(resolve => { release = resolve; });
      const entered = new Promise<void>(resolve => { editing = resolve; });
      instance.telegram = async (method, body) => {
        if (method === "editMessageText") { editing(); await gate; }
        return telegram(method, body);
      };
      const status = instance.card("machine1");
      await entered;
      const fresh = instance.text("/start");
      release();
      await Promise.all([status, fresh]);
      expect(instance.get<any>("panel").view).toBe("machines");
    });
    expect(calls.filter(c => c.url.endsWith("/sendMessage"))).toHaveLength(2);
  });
  it("upgrades old keyboards even when the status text is unchanged", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.card("machine1");
      const panel = instance.get<any>("panel");
      const [text] = JSON.parse(panel.signature);
      panel.signature = JSON.stringify([text, []]);
      instance.put("panel", panel);
      await instance.card("machine1", false);
    });
    expect(calls.filter(c => c.url.endsWith("/editMessageText"))).toHaveLength(1);
    expect(calls.at(-1).body.reply_markup.inline_keyboard.flat().some((b: any) => b.text === "更新程序")).toBe(true);
  });
  it("routes the update button only to the selected connected computer", async () => {
    await seed("a"); await seed("b");
    const sockets: WebSocket[] = [];
    try {
      for (const id of ["a", "b"]) {
        const result = await SELF.fetch("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": id, Authorization: "Bearer secret-" + id } });
        const ws = result.webSocket!; ws.accept(); sockets.push(ws);
      }
      const received = new Promise<any>(resolve => sockets[1].addEventListener("message", e => resolve(JSON.parse(e.data as string)), { once: true }));
      await runInDurableObject(hub(), async (instance: BotHub) => {
        await instance.click("d:b");
        await instance.click("update:b");
        expect(instance.list("cmd:a:")).toHaveLength(0);
      });
      expect(await received).toMatchObject({ action: "update", device_id: "b" });
    } finally { sockets.forEach(s => s.close()); }
  });
  it("misses offline scheduled starts instead of queueing them", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      instance.put("schedule:s", { id: "s", device_id: "machine1", action: "start", kind: "daily", due: now() - 20 });
      await instance.alarm();
      expect(instance.list("cmd:machine1:")).toHaveLength(0);
      expect(instance.get<any>("schedule:s").due).toBeGreaterThan(now());
    });
    expect(calls.some(c => c.body.text?.includes("不补执行"))).toBe(true);
  });
  it("uses real authenticated sockets and routes commands only to the target machine", async () => {
    await seed("a"); await seed("b");
    const sockets: WebSocket[] = [];
    try {
      for (const id of ["a", "b"]) {
        const result = await SELF.fetch("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": id, Authorization: "Bearer secret-" + id } });
        expect(result.status).toBe(101);
        const socket = result.webSocket!; socket.accept(); sockets.push(socket);
      }
      const messages: any[][] = [[], []];
      sockets.forEach((s, i) => s.addEventListener("message", e => { messages[i].push(JSON.parse(e.data as string)); }));
      const received = new Promise<void>(resolve => sockets[0].addEventListener("message", () => resolve(), { once: true }));
      await runInDurableObject(hub(), (instance: BotHub) => instance.issue("a", "start", {}));
      await received;
      expect(messages[0][0].device_id).toBe("a");
      expect(messages[1]).toHaveLength(0);
      await runInDurableObject(hub(), async (instance: BotHub) => {
        await expect(instance.issue("a", "start", {})).rejects.toThrow("已有任务");
      });
    } finally { sockets.forEach(s => s.close()); }
  });
  it("rejects the wrong device credential", async () => {
    await seed();
    const result = await SELF.fetch("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": "machine1", Authorization: "Bearer wrong" } });
    expect(result.status).toBe(401);
  });
  it("cannot resurrect a device removed while connection authentication is pending", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      const digest = crypto.subtle.digest.bind(crypto.subtle);
      // Perform the removal at the authentication await boundary, within this actor's I/O context.
      const spy = vi.spyOn(crypto.subtle, "digest").mockImplementation(async (...args) => {
        const result = await digest(...args);
        instance.del("d:machine1");
        return result;
      });
      try {
        const response = await instance.connectDevice(new Request("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": "machine1", Authorization: "Bearer secret-machine1" } }));
        expect(response.status).toBe(401);
        expect(instance.get("d:machine1")).toBeUndefined();
      } finally { spy.mockRestore(); }
    });
  });
  it("keeps settings and stop intent after the Durable Object is evicted", async () => {
    await seed();
    await runInDurableObject(hub(), async (instance: BotHub) => {
      await instance.issue("machine1", "settings", { hold_minutes: 42, interval_minutes: 3 });
      await instance.issue("machine1", "stop", {});
    });
    await evictDurableObject(hub());
    await runInDurableObject(hub(), (instance: BotHub) => {
      expect(instance.device("machine1").settings.hold_minutes).toBe(42);
      expect(instance.device("machine1").desired).toBe("stopped");
    });
  });
  it("a restarted client invalidates previously queued starts and stays idle", async () => {
    await seed();
    await runInDurableObject(hub(), (instance: BotHub) => {
      const d = instance.device("machine1"); d.boot_id = "old"; d.desired = "running"; d.version = 2;
      instance.put("d:machine1", d);
      instance.put("cmd:machine1:old", { id: "old", device_id: d.id, version: 2, action: "start", expires_at: now() + 60 });
    });
    const response = await SELF.fetch("https://relay.example.com/v1/connect", { headers: { Upgrade: "websocket", "X-Device-ID": "machine1", Authorization: "Bearer secret-machine1" } });
    const ws = response.webSocket!; ws.accept();
    try {
      const received = new Promise<any>(resolve => ws.addEventListener("message", e => resolve(JSON.parse(e.data as string)), { once: true }));
      ws.send(JSON.stringify({ protocol: 1, event: "hello", boot_id: "new" }));
      expect((await received).desired).toBe("stopped");
      await runInDurableObject(hub(), (instance: BotHub) => {
        expect(instance.get<any>("cmd:machine1:old").result.ok).toBe(false);
      });
    } finally { ws.close(); }
  });
});
