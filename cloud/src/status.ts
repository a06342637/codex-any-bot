import { localTime, now, type Device } from "./model";

const reasons: Record<string, string> = {
  failed: "本轮执行未成功，稍后自动重试", locked: "会话正在被占用，等待释放",
  auth: "登录或服务认证失效", permission: "权限不足，需要在电脑上处理",
  archived: "会话已归档", unknown_session: "未能确认新会话，已暂停以避免重复创建",
};

export function runtimeStatus(device: Device, current = now()) {
  const reported = device.state?.task;
  const runId = device.run_command_id || reported?.id || "idle";
  const task = reported?.id === runId ? reported : undefined;
  const pending = (device.state?.version ?? -1) < device.version;
  let phase = task?.phase || "stopped";
  if (!task && device.desired === "running") phase = "waiting";
  if (device.desired === "stopped" && pending && ["waiting", "running", "retrying", "holding"].includes(phase)) phase = "stopping";
  const attempt = Number.isSafeInteger(task?.attempts) ? task.attempts : 0;
  const attemptLabel = attempt ? `第 ${attempt} 次尝试 · ` : "";
  const labels: Record<string, string> = {
    waiting: "⏳ 启动指令已发送，等待电脑确认",
    running: `⏳ ${attemptLabel}Codex 执行中，本轮尚未确认成功`,
    retrying: `🔄 ${attemptLabel}未成功，等待重试`,
    holding: `✅ 第 ${task?.rounds || 0} 轮执行成功，等待下一轮`,
    stopping: "⏸ 停止指令已发送，等待电脑确认",
    stopped: "⏹ 已停止", paused: "⚠️ 已暂停，需要处理异常",
  };
  const lines = [labels[phase] || "待命"];
  if (task) {
    lines.push(`尝试：${attempt || "旧版未上报"} 次 · 重试：${task.retry_count ?? "旧版未上报"} 次 · 成功：${task.rounds || 0} 轮`);
    if (task.failures) lines.push(`连续失败：${task.failures} 次`);
    if (task.reason) lines.push("说明：" + (reasons[task.reason] || String(task.reason).slice(0, 180)));
    if (["retrying", "holding"].includes(phase) && task.next_at) {
      lines.push(`${phase === "retrying" ? "下次重试" : "下次发送"}：${localTime(task.next_at)}（${Math.max(0, Math.ceil(task.next_at - current))} 秒后）`);
    }
    if (task.first_success_at && !["stopped", "paused"].includes(phase)) {
      lines.push(`首次成功：${localTime(task.first_success_at)}`);
      if (task.deadline) lines.push(`剩余保持：${Math.max(0, Math.ceil((task.deadline - current) / 60))} 分钟`);
    }
  }
  if (device.state?.time) lines.push(`状态更新：${localTime(device.state.time)}`);
  return { runId, attempt, phase, lines };
}
