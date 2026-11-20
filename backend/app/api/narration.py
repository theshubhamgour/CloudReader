from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..processing.styles import PACES, STYLES
from ..services.preview import create_preview
from ..services.profiles import validate_profile_fields
from .deps import get_ctx

router = APIRouter(prefix="/api", tags=["narration"])


@router.get("/providers")
def providers(ctx=Depends(get_ctx)):
    out = []
    for p in ctx.providers.all():
        ok, why = p.available()
        out.append({
            "id": p.id, "label": p.label, "is_demo": p.is_demo, "available": ok, "unavailable_reason": why or None,
            "capabilities": asdict(p.capabilities()),
            "models": [asdict(m) for m in p.models()],
            "voices": [asdict(v) for v in p.voices()],
        })
    return out


@router.get("/styles")
def styles():
    return {"styles": [{"key": k, **v} for k, v in STYLES.items()],
            "paces": [{"key": k, **v} for k, v in PACES.items()]}


# ---------------------------------------------------------------- profiles

class Profile(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider: str
    model: str
    voice: str
    style_key: str = "natural"
    pace: str = "natural"
    language: str | None = None
    delivery_notes: str = Field("", max_length=400)
    output_format: str = "mp3"
    is_default: bool = False


COLS = ("name", "provider", "model", "voice", "style_key", "pace", "language", "delivery_notes", "output_format",
        "is_default")


@router.get("/profiles")
def list_profiles(ctx=Depends(get_ctx)):
    return ctx.db.query("SELECT * FROM narration_profiles ORDER BY is_default DESC, id")


@router.post("/profiles")
def create_profile(body: Profile, ctx=Depends(get_ctx)):
    data = body.model_dump()
    validate_profile_fields(ctx, data)
    with ctx.db.tx() as c:
        if data["is_default"]:
            c.execute("UPDATE narration_profiles SET is_default=0")
        pid = c.execute(f"INSERT INTO narration_profiles ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})",
                        tuple(data[k] for k in COLS)).lastrowid
    return ctx.db.one("SELECT * FROM narration_profiles WHERE id=?", (pid,))


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, body: Profile, ctx=Depends(get_ctx)):
    if not ctx.db.one("SELECT id FROM narration_profiles WHERE id=?", (profile_id,)):
        raise HTTPException(404, "Profile not found")
    data = body.model_dump()
    validate_profile_fields(ctx, data)
    with ctx.db.tx() as c:
        if data["is_default"]:
            c.execute("UPDATE narration_profiles SET is_default=0")
        c.execute(f"UPDATE narration_profiles SET {', '.join(f'{k}=?' for k in COLS)}, updated_at=datetime('now') "
                  "WHERE id=?", (*[data[k] for k in COLS], profile_id))
    return ctx.db.one("SELECT * FROM narration_profiles WHERE id=?", (profile_id,))


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, ctx=Depends(get_ctx)):
    if ctx.db.one("SELECT COUNT(*) n FROM narration_profiles")["n"] <= 1:
        raise HTTPException(400, "Keep at least one narration profile.")
    ctx.db.execute("DELETE FROM narration_profiles WHERE id=?", (profile_id,))
    if not ctx.db.one("SELECT id FROM narration_profiles WHERE is_default=1"):
        ctx.db.execute("UPDATE narration_profiles SET is_default=1 WHERE id=(SELECT MIN(id) FROM narration_profiles)")
    return {"ok": True}


# ---------------------------------------------------------------- preview

class PreviewReq(BaseModel):
    provider: str
    model: str
    voice: str
    style_key: str = "natural"
    pace: str = "natural"
    delivery_notes: str = Field("", max_length=400)
    text: str | None = Field(None, max_length=1500)
    chapter_id: int | None = None
    book_id: int | None = None


@router.post("/preview")
def preview(body: PreviewReq, ctx=Depends(get_ctx)):
    return create_preview(ctx, provider_id=body.provider, model=body.model, voice=body.voice,
                          style_key=body.style_key, pace=body.pace, delivery_notes=body.delivery_notes,
                          text=body.text, chapter_id=body.chapter_id, book_id=body.book_id)


@router.get("/previews/{name}")
def preview_audio(name: str, ctx=Depends(get_ctx)):
    key = name.removesuffix(".wav")
    if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
        raise HTTPException(404, "Not found")
    path = ctx.settings.audio_dir / "previews" / f"{key}.wav"
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="audio/wav")


# ---------------------------------------------------------------- pronunciation & characters

class Pronunciation(BaseModel):
    term: str = Field(..., min_length=1, max_length=100)
    replacement: str = Field(..., min_length=1, max_length=200)
    notes: str = Field("", max_length=500)
    chapter_id: int | None = None
    case_sensitive: bool = False


@router.get("/books/{book_id}/pronunciations")
def list_pron(book_id: int, ctx=Depends(get_ctx)):
    return ctx.db.query("SELECT * FROM pronunciations WHERE book_id=? ORDER BY term COLLATE NOCASE", (book_id,))


@router.post("/books/{book_id}/pronunciations")
def add_pron(book_id: int, body: Pronunciation, ctx=Depends(get_ctx)):
    if body.chapter_id and not ctx.db.one("SELECT id FROM chapters WHERE id=? AND book_id=?", (body.chapter_id, book_id)):
        raise HTTPException(400, "That chapter does not belong to this book.")
    pid = ctx.db.execute("INSERT INTO pronunciations (book_id, chapter_id, term, replacement, notes, case_sensitive) "
                         "VALUES (?,?,?,?,?,?)", (book_id, body.chapter_id, body.term.strip(), body.replacement.strip(),
                                                  body.notes, int(body.case_sensitive)))
    return ctx.db.one("SELECT * FROM pronunciations WHERE id=?", (pid,))


@router.put("/pronunciations/{pid}")
def update_pron(pid: int, body: Pronunciation, ctx=Depends(get_ctx)):
    ctx.db.execute("UPDATE pronunciations SET chapter_id=?, term=?, replacement=?, notes=?, case_sensitive=? WHERE id=?",
                   (body.chapter_id, body.term.strip(), body.replacement.strip(), body.notes, int(body.case_sensitive), pid))
    return ctx.db.one("SELECT * FROM pronunciations WHERE id=?", (pid,))


@router.delete("/pronunciations/{pid}")
def delete_pron(pid: int, ctx=Depends(get_ctx)):
    ctx.db.execute("DELETE FROM pronunciations WHERE id=?", (pid,))
    return {"ok": True}


class Character(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=1000)


@router.get("/books/{book_id}/characters")
def list_chars(book_id: int, ctx=Depends(get_ctx)):
    return ctx.db.query("SELECT * FROM characters WHERE book_id=? ORDER BY name COLLATE NOCASE", (book_id,))


@router.post("/books/{book_id}/characters")
def add_char(book_id: int, body: Character, ctx=Depends(get_ctx)):
    cid = ctx.db.execute("INSERT INTO characters (book_id, name, description) VALUES (?,?,?)",
                         (book_id, body.name.strip(), body.description))
    return ctx.db.one("SELECT * FROM characters WHERE id=?", (cid,))


@router.put("/characters/{cid}")
def update_char(cid: int, body: Character, ctx=Depends(get_ctx)):
    ctx.db.execute("UPDATE characters SET name=?, description=? WHERE id=?", (body.name.strip(), body.description, cid))
    return ctx.db.one("SELECT * FROM characters WHERE id=?", (cid,))


@router.delete("/characters/{cid}")
def delete_char(cid: int, ctx=Depends(get_ctx)):
    ctx.db.execute("DELETE FROM characters WHERE id=?", (cid,))
    return {"ok": True}
