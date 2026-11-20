"""Narration profiles: the saved narrator configuration used across chapters."""
from __future__ import annotations

from ..processing.styles import PACES, STYLES

DEFAULT_GEMINI_VOICE = "Sulafat"  # documented as "Warm"


def ensure_default_profiles(ctx) -> None:
    db = ctx.db
    if db.one("SELECT id FROM narration_profiles LIMIT 1"):
        return
    gemini = ctx.providers.get("gemini")
    demo = ctx.providers.get("demo")
    gid = db.execute(
        "INSERT INTO narration_profiles (name, provider, model, voice, style_key, pace, is_default) "
        "VALUES (?,?,?,?,?,?,?)",
        ("Warm Narrator (Gemini)", "gemini", ctx.settings.gemini_default_model, DEFAULT_GEMINI_VOICE,
         "natural", "natural", 1 if gemini.available()[0] else 0),
    )
    did = db.execute(
        "INSERT INTO narration_profiles (name, provider, model, voice, style_key, pace, is_default) "
        "VALUES (?,?,?,?,?,?,?)",
        ("Demo Narrator (not AI)", "demo", demo.models()[0].id, demo.voices()[0].id, "natural", "natural",
         0 if gemini.available()[0] else 1),
    )
    _ = (gid, did)


def get_profile(ctx, profile_id: int | None) -> dict:
    if profile_id:
        p = ctx.db.one("SELECT * FROM narration_profiles WHERE id=?", (profile_id,))
        if p:
            return p
    p = ctx.db.one("SELECT * FROM narration_profiles WHERE is_default=1 ORDER BY id LIMIT 1")
    return p or ctx.db.one("SELECT * FROM narration_profiles ORDER BY id LIMIT 1")


def profile_for_book(ctx, book: dict) -> dict:
    return get_profile(ctx, book.get("narration_profile_id"))


def validate_profile_fields(ctx, data: dict) -> None:
    from fastapi import HTTPException

    try:
        provider = ctx.providers.get(data["provider"])
    except KeyError:
        raise HTTPException(400, f"Unknown provider '{data['provider']}'.")
    if data["model"] not in {m.id for m in provider.models()}:
        raise HTTPException(400, f"Model '{data['model']}' is not offered by {provider.label}.")
    if data["voice"] not in {v.id for v in provider.voices()}:
        raise HTTPException(400, f"Voice '{data['voice']}' is not available for {provider.label}.")
    if data.get("style_key", "natural") not in STYLES:
        raise HTTPException(400, "Unknown narration style.")
    if data.get("pace", "natural") not in PACES:
        raise HTTPException(400, "Unknown pace.")
    if data.get("output_format", "mp3") not in ("mp3", "flac"):
        raise HTTPException(400, "Output format must be mp3 or flac.")
