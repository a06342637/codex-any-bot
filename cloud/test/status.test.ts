import { describe, expect, it } from "vitest";
import { defaults, type Device } from "../src/model";
import { runtimeStatus } from "../src/status";

const device = (): Device => ({ id: "a", name: "A", token_hash: "unused", platform: "win32", settings: defaults,
  desired: "running", version: 1, seen: 1000, state: { version: 1, time: 1000, task: { id: "job", phase: "running", attempts: 3, retry_count: 2, rounds: 0 } } });

describe("live task status", () => {
  it("distinguishes an active attempt from a confirmed success", () => {
    const d = device();
    expect(runtimeStatus(d, 1000).lines.join("\n")).toContain("第 3 次尝试");
    expect(runtimeStatus(d, 1000).lines.join("\n")).toContain("本轮尚未确认成功");
    d.state.task.phase = "holding"; d.state.task.rounds = 1;
    expect(runtimeStatus(d, 1000).lines[0]).toContain("第 1 轮执行成功");
  });
  it("shows retry counts, readable reasons and the next retry", () => {
    const d = device();
    Object.assign(d.state.task, { phase: "retrying", failures: 3, reason: "locked", next_at: 1060 });
    const text = runtimeStatus(d, 1000).lines.join("\n");
    expect(text).toContain("重试：2 次");
    expect(text).toContain("连续失败：3 次");
    expect(text).toContain("会话正在被占用");
    expect(text).toContain("下次重试：");
    expect(text).toContain("60 秒后");
  });
  it("does not show a previous task as running after a new start or pending stop", () => {
    const d = device(); d.run_command_id = "new"; d.version = 2;
    expect(runtimeStatus(d).phase).toBe("waiting");
    d.run_command_id = "job"; d.desired = "stopped";
    expect(runtimeStatus(d).phase).toBe("stopping");
  });
});
