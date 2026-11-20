"""Usage and cost estimates. Every figure produced here is an estimate."""
from __future__ import annotations

from datetime import date

from ..manuscript.chapters import WORDS_PER_MINUTE

CHARS_PER_TOKEN = 4.0  # rough English average; the API reports exact counts after the fact


def price_for(model_info, on: date | None = None) -> tuple[float, float] | None:
    """(input $/1M, output $/1M) valid on `on`, or None when unknown."""
    on = on or date.today()
    for until, inp, out in model_info.pricing:
        if until is None or on <= date.fromisoformat(until):
            return inp, out
    return None


def estimate(provider, model_id: str, words: int, characters: int, style_chars: int = 0) -> dict:
    seconds = words / WORDS_PER_MINUTE * 60
    result = {
        "words": words, "characters": characters,
        "estimated_audio_minutes": round(seconds / 60, 1),
        "is_estimate": True,
        "cost_usd": None, "input_tokens": None, "output_tokens": None,
        "pricing_note": None,
    }
    if provider.is_demo:
        result["pricing_note"] = "Demo mode is free and runs locally."
        result["cost_usd"] = 0.0
        return result
    info = next((m for m in provider.models() if m.id == model_id), None)
    price = price_for(info) if info else None
    if not info or not price or not info.audio_tokens_per_second:
        result["pricing_note"] = "Pricing for this model is unknown; no cost estimate is shown."
        return result
    in_tok = int((characters + style_chars) / CHARS_PER_TOKEN)
    out_tok = int(seconds * info.audio_tokens_per_second)
    result.update({
        "input_tokens": in_tok, "output_tokens": out_tok,
        "cost_usd": round(in_tok / 1e6 * price[0] + out_tok / 1e6 * price[1], 4),
        "pricing_note": (f"Estimate at ${price[0]:.2f}/1M input and ${price[1]:.2f}/1M audio tokens "
                         f"(paid tier, {info.audio_tokens_per_second:g} audio tokens/s). Actual audio length "
                         "varies with pacing. Free-tier usage is not billed but is rate-limited."),
    })
    return result


def actual_usage(ctx) -> dict:
    rows = ctx.db.query(
        "SELECT provider, model, kind, COUNT(*) requests, SUM(characters) characters, "
        "SUM(input_tokens) input_tokens, SUM(output_tokens) output_tokens, SUM(audio_seconds) audio_seconds "
        "FROM usage_log GROUP BY provider, model, kind ORDER BY provider, model, kind")
    for r in rows:
        r["cost_usd"] = None
        try:
            prov = ctx.providers.get(r["provider"])
        except KeyError:
            continue
        info = next((m for m in prov.models() if m.id == r["model"]), None)
        price = price_for(info) if info else None
        if price and r["input_tokens"] is not None and r["output_tokens"] is not None:
            r["cost_usd"] = round(r["input_tokens"] / 1e6 * price[0] + r["output_tokens"] / 1e6 * price[1], 4)
    return {"rows": rows, "note": "Costs use today's list price applied to token counts reported by the API. "
                                  "They are estimates; your Google Cloud billing is authoritative."}
