import { describe, expect, it } from "vitest";
import { authorized, parseSchedule, settings } from "../src/model";

describe("configuration and time", () => {
  it("requires both the permitted user and chat", () => {
    expect(authorized({ callback_query: { from: { id: 42 }, message: { chat: { id: 42 } } } }, "42", "42")).toBe(true);
    expect(authorized({ callback_query: { from: { id: 43 }, message: { chat: { id: 42 } } } }, "42", "42")).toBe(false);
    expect(authorized({ message: { from: { id: 42 }, chat: { id: -42 } } }, "42", "42")).toBe(false);
  });
  it("keeps machine settings independent", () => {
    const a = settings({ hold_minutes: 30, interval_minutes: 1 });
    const b = settings({ hold_minutes: 120, interval_minutes: 5 });
    a.hold_minutes = 10;
    expect(b.hold_minutes).toBe(120);
    expect(settings({}).interval_minutes).toBe(1);
    expect(() => settings({ interval_minutes: 0 })).toThrow();
    expect(() => settings({ hold_minutes: 0.5 })).toThrow();
  });
  it("interprets schedules in Beijing time and skips previous daily slots", () => {
    const current = Date.parse("2026-10-15T10:00:00+08:00") / 1000;
    expect(parseSchedule("每天 09:00", current).due).toBe(Date.parse("2026-10-16T09:00:00+08:00") / 1000);
    expect(parseSchedule("2026-10-15 11:00", current).due).toBe(current + 3600);
    expect(() => parseSchedule("2026-02-30 11:00", current)).toThrow();
    expect(() => parseSchedule("每天 25:99", current)).toThrow();
    expect(() => parseSchedule("2026-10-15 09:00", current)).toThrow();
  });
});
