from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audio.ffmpeg import ffmpeg_available
from ..providers.gemini import GeminiTTSProvider, map_exception
from ..secrets import GEMINI, delete_secret, mask, set_secret
from .deps import get_ctx

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
def get_settings(ctx=Depends(get_ctx)):
    s = ctx.settings
    key, source = s.gemini_key_source()
    usage = shutil.disk_usage(s.data_dir)
    prefs = {r["key"]: r["value"] for r in ctx.db.query("SELECT * FROM app_settings")}
    return {
        "app_name": s.app_name, "app_tagline": s.app_tagline,
        "gemini": {"configured": bool(key), "source": source, "masked_key": mask(key),
                   "default_model": s.gemini_default_model},
        "ffmpeg_available": ffmpeg_available(),
        "data_dir": str(s.data_dir),
        "disk_free_gb": round(usage.free / 1e9, 1),
        "segment_target_chars": s.segment_target_chars,
        "large_job_word_threshold": s.large_job_word_threshold,
        "preferences": prefs,
    }


class KeyBody(BaseModel):
    api_key: str = Field(..., min_length=10, max_length=200)


def _reload_gemini(ctx):
    from ..services.quota import clear

    clear(ctx, "gemini")  # a new key has its own quota
    ctx.providers.set(GeminiTTSProvider(ctx.settings.resolved_gemini_key(), ctx.settings.tts_request_timeout_s))


@router.put("/settings/gemini-key")
def save_key(body: KeyBody, ctx=Depends(get_ctx)):
    if not ctx.settings.use_keychain:
        raise HTTPException(400, "Keychain storage is disabled; set GEMINI_API_KEY in backend/.env.")
    try:
        set_secret(GEMINI, body.api_key.strip())
    except OSError as e:
        raise HTTPException(500, f"Couldn't save the key ({type(e).__name__}). Put it in backend/.env instead.")
    _reload_gemini(ctx)
    return get_settings(ctx)


@router.delete("/settings/gemini-key")
def remove_key(ctx=Depends(get_ctx)):
    delete_secret(GEMINI)
    _reload_gemini(ctx)
    return get_settings(ctx)


@router.post("/settings/gemini-key/test")
def test_key(ctx=Depends(get_ctx)):
    """Checks the key with a free metadata request (no audio is generated, no tokens billed)."""
    key = ctx.settings.resolved_gemini_key()
    if not key:
        raise HTTPException(400, "No Gemini API key configured.")
    try:
        from google import genai

        # Keep a reference: the SDK closes its HTTP client when the Client is garbage-collected.
        client = genai.Client(api_key=key)
        m = client.models.get(model=ctx.settings.gemini_default_model)
        return {"ok": True, "model": getattr(m, "name", None), "display_name": getattr(m, "display_name", None)}
    except Exception as e:
        err = map_exception(e)
        return {"ok": False, "error": err.message, "code": err.code}


class Pref(BaseModel):
    key: str = Field(..., pattern=r"^[a-z_]{1,40}$")
    value: str = Field(..., max_length=500)


@router.put("/settings/preferences")
def set_pref(body: Pref, ctx=Depends(get_ctx)):
    ctx.db.execute("INSERT INTO app_settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (body.key, body.value))
    return {"ok": True}


# ---------------------------------------------------------------- the simple "which voice reads my books" choice

ENGINES = {
    # engine id -> (provider id, profile name used for it)
    "local": ("demo", "Local voice"),
    "gemini": ("gemini", "Gemini AI voice"),
}


def _active_profile(ctx):
    from ..services.profiles import get_profile

    return get_profile(ctx, None)


@router.get("/settings/voice")
def get_voice(ctx=Depends(get_ctx)):
    """The voice new narration uses, plus the choices for each engine."""
    from ..services.profiles import ensure_default_profiles

    ensure_default_profiles(ctx)
    from ..services.quota import active_block

    p = _active_profile(ctx)
    out = {"engine": "gemini" if p["provider"] == "gemini" else "local", "voice": p["voice"], "profile_id": p["id"],
           "engines": {}}
    for engine, (pid, label) in ENGINES.items():
        prov = ctx.providers.get(pid)
        ok, why = prov.available()
        mine = ctx.db.one("SELECT model FROM narration_profiles WHERE provider=? ORDER BY is_default DESC, id LIMIT 1", (pid,))
        model = mine["model"] if mine and mine["model"] in {m.id for m in prov.models()} else _default_model(prov)
        out["engines"][engine] = {
            "provider": pid, "available": ok, "unavailable_reason": why or None,
            "model": model, "blocked": active_block(ctx, pid, model) if ok else None,
            "models": [{"id": m.id, "label": m.label, "fast": m.id == FAST_MODEL} for m in prov.models()],
            "voices": [{"id": v.id, "name": v.name, "description": v.description} for v in prov.voices()],
        }
    return out


# Flash-Lite answers noticeably faster; it's the default "Fast" choice for Gemini.
FAST_MODEL = "gemini-3.8-flash-lite-tts"


def _default_model(prov):
    ids = [m.id for m in prov.models()]
    return FAST_MODEL if FAST_MODEL in ids else ids[0]


class VoiceChoice(BaseModel):
    engine: str = Field(..., pattern="^(local|gemini)$")
    voice: str | None = None
    model: str | None = None


@router.put("/settings/voice")
def set_voice(body: VoiceChoice, ctx=Depends(get_ctx)):
    provider_id, name = ENGINES[body.engine]
    prov = ctx.providers.get(provider_id)
    ok, why = prov.available()
    if not ok:
        raise HTTPException(400, why)
    voices = [v.id for v in prov.voices()]
    current = ctx.db.one("SELECT * FROM narration_profiles WHERE provider=? ORDER BY is_default DESC, id LIMIT 1",
                         (provider_id,))
    voice = body.voice or (current["voice"] if current and current["voice"] in voices else voices[0])
    if voice not in voices:
        raise HTTPException(400, f"Unknown voice '{voice}'.")
    models = {m.id for m in prov.models()}
    if body.model and body.model not in models:
        raise HTTPException(400, f"Unknown model '{body.model}'.")
    model = body.model or (current["model"] if current and current["model"] in models else _default_model(prov))
    with ctx.db.tx() as c:
        c.execute("UPDATE narration_profiles SET is_default=0")
        if current:
            c.execute("UPDATE narration_profiles SET voice=?, model=?, is_default=1, updated_at=datetime('now') WHERE id=?",
                      (voice, model, current["id"]))
        else:
            c.execute("INSERT INTO narration_profiles (name, provider, model, voice, style_key, pace, is_default) "
                      "VALUES (?,?,?,?,?,?,1)", (name, provider_id, model, voice, "natural", "natural"))
    return get_voice(ctx)
