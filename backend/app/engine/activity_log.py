"""Activity log for bot operations."""

from __future__ import annotations

from app.models import BotState, utc_now_iso


def push_activity(bot: BotState, phase: str, message: str, level: str = "info") -> None:
    bot.status.phase = phase
    entry = {
        "ts": utc_now_iso(),
        "phase": phase,
        "message": message,
        "level": level,
    }
    bot.activity_log.insert(0, entry)
    bot.activity_log = bot.activity_log[:100]
