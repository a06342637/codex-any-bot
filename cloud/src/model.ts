export interface Settings {
  hold_minutes: number | null;
  interval_minutes: number;
  prompt: string;
  cwd: string;
  thread_id: string | null;
}
export const defaults: Settings = { hold_minutes: null, interval_minutes: 1, prompt: "在", cwd: "", thread_id: null };
export function settings(input: Partial<Settings>): Settings {
  const value = { ...defaults, ...input };
  for (const key of ["hold_minutes", "interval_minutes"] as const) {
    const n = value[key];
    if (key === "hold_minutes" && n === null) continue;
    if (!Number.isInteger(n) || n! < 1 || n! > 525600) throw new Error("请输入 1–525600 的整数分钟");
  }
  if (typeof value.prompt !== "string" || !value.prompt.trim() || value.prompt.length > 4000) throw new Error("发送内容须为 1–4000 字符");
  if (typeof value.cwd !== "string" || (value.thread_id !== null && typeof value.thread_id !== "string")) throw new Error("无效的会话配置");
  return value;
}
export function authorized(update: any, user: string, chat: string): boolean {
  const source = update.callback_query ?? update.message;
  const target = update.callback_query?.message ?? update.message;
  return !!source && String(source.from?.id) === user && String(target?.chat?.id) === chat;
}
export const now = () => Date.now() / 1000;
export const id = () => crypto.randomUUID().replaceAll("-", "").slice(0, 16);
export async function hash(value: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))), x => x.toString(16).padStart(2, "0")).join("");
}
export function secret(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)), x => x.toString(16).padStart(2, "0")).join("");
}
export function localTime(value: number): string {
  return new Date(value * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
}
export function parseSchedule(input: string, current = now()): { kind: "once" | "daily"; due: number; time?: string } {
  const daily = /^每天\s+(\d{2}):(\d{2})$/.exec(input);
  if (daily) {
    if (+daily[1] > 23 || +daily[2] > 59) throw new Error("时间格式应为 每天 HH:MM");
    const date = new Date((current + 8 * 3600) * 1000).toISOString().slice(0, 10);
    let due = Date.parse(`${date}T${daily[1]}:${daily[2]}:00+08:00`) / 1000;
    if (due <= current) due += 86400;
    return { kind: "daily", due, time: `${daily[1]}:${daily[2]}` };
  }
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(input)) throw new Error("请输入 YYYY-MM-DD HH:MM 或 每天 HH:MM（北京时间）");
  const due = Date.parse(input.replace(" ", "T") + ":00+08:00") / 1000;
  if (!Number.isFinite(due) || due <= current || new Date((due + 8 * 3600) * 1000).toISOString().slice(0, 16).replace("T", " ") !== input) throw new Error("请输入有效的未来时间");
  return { kind: "once", due };
}

export interface Device {
  id: string; name: string; token_hash: string; platform: string;
  settings: Settings; version: number; desired: "running" | "stopped";
  seen: number; connection?: string; boot_id?: string; state?: any;
  card_id?: number; card_text?: string; notice_key?: string; offline_notified?: boolean;
}
export interface Command { type: "command"; protocol: 1; id: string; device_id: string; version: number; action: string; payload: any; expires_at: number; result?: any }
export interface Schedule { id: string; device_id: string; action: "start" | "stop"; kind: "once" | "daily"; due: number; time?: string }
