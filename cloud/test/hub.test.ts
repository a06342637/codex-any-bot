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
  it("rejects bad webhook secrets and ignores unauthorized users", async () => {
    expect((await webhook({}, "wrong")).status).toBe(401);
    await webhook({ update_id: 1, message: { from: { id: 999 }, chat: { id: 42 }, text: "/start" } });
    expect(calls).toHaveLength(0);
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
  it("reports each selected machine even if one was removed during a batch edit", async () => {
    await seed("a"); await seed("b");
    await runInDurableObject(hub(), async (instance: BotHub) => {
      instance.put("input", { type: "hold", ids: ["a", "removed", "b"], expires: now() + 600 });
      await instance.text("30");
      expect(instance.device("a").settings.hold_minutes).toBe(30);
      expect(instance.device("b").settings.hold_minutes).toBe(30);
    });
    expect(calls.some(c => c.body.text?.includes("removed："))).toBe(true);
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
