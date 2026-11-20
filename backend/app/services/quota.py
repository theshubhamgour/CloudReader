"""Remembers when a provider's daily quota is used up, so we fail instantly instead of
sending requests that are certain to be refused (and waiting on retries)."""
from __future__ import annotations

import re
import time

PREFIX = "quota_block:"


def _seconds(text: str) -> int | None:
    m = re.search(r"retry in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", text or "")
    if not m or not m.group(1):
        return None
    total = 0.0
    for n, unit in re.findall(r"([\d.]+)([hms])", m.group(1)):
        total += float(n) * {"h": 3600, "m": 60, "s": 1}[unit]
    return int(total) or None


def record_block(ctx, provider: str, model: str, message: str, detail: str) -> None:
    until = time.time() + (_seconds(detail) or 3600)
    ctx.db.execute("INSERT INTO app_settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (f"{PREFIX}{provider}:{model}", f"{int(until)}|{message}"))


def active_block(ctx, provider: str, model: str) -> str | None:
    """The user-facing message if this provider+model is blocked right now."""
    row = ctx.db.one("SELECT value FROM app_settings WHERE key=?", (f"{PREFIX}{provider}:{model}",))
    if not row:
        return None
    until, _, message = row["value"].partition("|")
    left = int(until) - time.time()
    if left <= 0:
        clear(ctx, provider, model)
        return None
    h, m = int(left // 3600), int(left % 3600 // 60)
    when = f"{h} h {m} min" if h else f"{max(m, 1)} min"
    return (f"Gemini's free daily limit is used up (resets in about {when}). "
            "Switch to the free local voice in Settings, or enable billing on your Gemini key for higher limits.")


def clear(ctx, provider: str | None = None, model: str | None = None) -> None:
    pattern = f"{PREFIX}{provider or ''}{':' + model if model else ''}%"
    ctx.db.execute("DELETE FROM app_settings WHERE key LIKE ?", (pattern,))
