"""Deterministic task timing; all timestamps are UTC epoch seconds."""
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Settings:
    hold_minutes: int | None = None
    interval_minutes: int = 1
    prompt: str = "在"
    cwd: str = ""
    thread_id: str | None = None

    @classmethod
    def parse(cls, data: dict[str, Any]) -> "Settings":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        for key in ("hold_minutes", "interval_minutes"):
            value = getattr(obj, key)
            if key == "hold_minutes" and value is None:
                continue
            if type(value) is not int or not 1 <= value <= 525600:
                raise ValueError(f"{key} 必须是 1–525600 的整数分钟")
        if not isinstance(obj.prompt, str) or not obj.prompt.strip() or len(obj.prompt) > 4000:
            raise ValueError("发送内容须为 1–4000 字符")
        if not isinstance(obj.cwd, str):
            raise ValueError("工作目录必须为字符串")
        if obj.thread_id is not None and not isinstance(obj.thread_id, str):
            raise ValueError("会话 ID 必须为字符串")
        return obj

    def json(self) -> dict:
        return asdict(self)


@dataclass
class Task:
    id: str
    version: int
    settings: Settings
    first_success_at: float | None = None
    last_finished_at: float | None = None
    stop_at: float | None = None
    retry_at: float | None = None
    failures: int = 0
    rounds: int = 0
    phase: str = "waiting"
    reason: str = ""

    @property
    def deadline(self) -> float | None:
        dates = [self.stop_at] if self.stop_at is not None else []
        if self.first_success_at is not None and self.settings.hold_minutes is not None:
            dates.append(self.first_success_at + self.settings.hold_minutes * 60)
        return min(dates) if dates else None

    def expired(self, now: float) -> bool:
        return self.deadline is not None and now >= self.deadline

    @property
    def next_at(self) -> float:
        if self.retry_at is not None:
            return self.retry_at
        if self.last_finished_at is None:
            return 0
        return self.last_finished_at + self.settings.interval_minutes * 60

    def finish(self, now: float, kind: str) -> bool:
        """Return True only for the first confirmed success."""
        self.last_finished_at = now
        first = False
        if kind == "success":
            first = self.first_success_at is None
            if first:
                self.first_success_at = now
            self.rounds += 1
            self.failures = 0
            self.retry_at = None
            self.phase = "holding"
        elif kind in ("auth", "permission", "archived", "unknown_session"):
            self.phase = "paused"
            self.reason = kind
        else:
            self.failures += 1
            delay = 60 if kind == "locked" else min(60, 5 * 2 ** min(self.failures - 1, 4))
            self.retry_at = now + delay
            self.phase = "retrying"
            self.reason = kind
        return first

    def json(self) -> dict:
        data = asdict(self)
        data.update(deadline=self.deadline, next_at=self.next_at)
        return data
