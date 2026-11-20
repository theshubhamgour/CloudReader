from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services import library
from ..services.costs import estimate
from ..services.profiles import get_profile
from .deps import get_ctx

router = APIRouter(prefix="/api", tags=["books"])

IMAGE_MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}


@router.get("/books")
def list_books(ctx=Depends(get_ctx)):
    ids = [r["id"] for r in ctx.db.query("SELECT id FROM books ORDER BY updated_at DESC, id DESC")]
    return [library.get_book(ctx, i, with_chapters=False) for i in ids]


@router.post("/books/import")
async def import_book(file: UploadFile = File(...), title: str | None = Form(None), author: str = Form(""),
                      ctx=Depends(get_ctx)):
    limit = ctx.settings.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {ctx.settings.max_upload_mb} MB.")
    return library.import_manuscript(ctx, file.filename or "", data, title, author)


@router.get("/books/{book_id}")
def get_book(book_id: int, ctx=Depends(get_ctx)):
    return library.get_book(ctx, book_id)


class BookPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    author: str | None = Field(None, max_length=200)
    narration_profile_id: int | None = None


@router.patch("/books/{book_id}")
def patch_book(book_id: int, body: BookPatch, ctx=Depends(get_ctx)):
    library.get_book(ctx, book_id, with_chapters=False)
    fields = body.model_dump(exclude_unset=True)
    if "title" in fields and not (fields["title"] or "").strip():
        raise HTTPException(400, "Title cannot be empty.")
    if fields.get("narration_profile_id") and not ctx.db.one(
            "SELECT id FROM narration_profiles WHERE id=?", (fields["narration_profile_id"],)):
        raise HTTPException(404, "Narration profile not found.")
    for k, v in fields.items():
        ctx.db.execute(f"UPDATE books SET {k}=?, updated_at=datetime('now') WHERE id=?", (v, book_id))
    return library.get_book(ctx, book_id)


@router.delete("/books/{book_id}")
def delete_book(book_id: int, ctx=Depends(get_ctx)):
    if ctx.db.one("SELECT id FROM jobs WHERE book_id=? AND status IN ('pending','processing')", (book_id,)):
        raise HTTPException(409, "Cancel running generation jobs for this book first.")
    ctx.db.execute("DELETE FROM books WHERE id=?", (book_id,))
    return {"ok": True}


@router.post("/books/{book_id}/cover")
async def upload_cover(book_id: int, file: UploadFile = File(...), ctx=Depends(get_ctx)):
    library.get_book(ctx, book_id, with_chapters=False)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Cover image must be under 10 MB.")
    ext = next((e for m, e in IMAGE_MAGIC.items() if data.startswith(m)), None)
    if not ext or (ext == ".webp" and data[8:12] != b"WEBP"):
        raise HTTPException(400, "Cover must be a PNG, JPEG or WebP image.")
    path = ctx.settings.data_dir / "covers" / f"book-{book_id}{ext}"
    for old in path.parent.glob(f"book-{book_id}.*"):
        old.unlink()
    path.write_bytes(data)
    ctx.db.execute("UPDATE books SET cover_path=? WHERE id=?", (str(path), book_id))
    return {"ok": True}


@router.get("/books/{book_id}/cover")
def get_cover(book_id: int, ctx=Depends(get_ctx)):
    b = ctx.db.one("SELECT cover_path FROM books WHERE id=?", (book_id,))
    if not b or not b["cover_path"]:
        raise HTTPException(404, "No cover")
    return FileResponse(b["cover_path"])


@router.get("/books/{book_id}/estimate")
def book_estimate(book_id: int, profile_id: int | None = None, ctx=Depends(get_ctx)):
    book = library.get_book(ctx, book_id, with_chapters=False)
    profile = get_profile(ctx, profile_id or book["narration_profile_id"])
    chars = ctx.db.one("SELECT SUM(LENGTH(text)) n FROM chapters WHERE book_id=?", (book_id,))["n"] or 0
    return estimate(ctx.providers.get(profile["provider"]), profile["model"], book["word_count"], chars)


# ---------------------------------------------------------------- chapters

@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: int, ctx=Depends(get_ctx)):
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise HTTPException(404, "Chapter not found")
    return library.chapter_out(ctx, ch, with_text=True)


@router.get("/chapters/{chapter_id}/segments")
def list_segments(chapter_id: int, ctx=Depends(get_ctx)):
    rows = ctx.db.query(
        "SELECT s.id, s.position, s.source_text, s.tts_text, s.replacements, s.analysis, s.style_instruction, "
        "s.paragraph_start, s.paragraph_end, s.status, s.attempts, s.error, s.variant, "
        "a.duration_s, a.is_demo FROM segments s LEFT JOIN audio_assets a ON a.cache_key=s.cache_key "
        "WHERE s.chapter_id=? ORDER BY s.position", (chapter_id,))
    for r in rows:
        r["replacements"] = json.loads(r["replacements"])
        r["analysis"] = json.loads(r["analysis"])
        r["has_audio"] = r["duration_s"] is not None and r["status"] == "completed"
    return rows


@router.post("/chapters/{chapter_id}/prepare")
def prepare(chapter_id: int, profile_id: int | None = None, ctx=Depends(get_ctx)):
    """Segment the chapter and report what generation would cost. Makes no API calls."""
    prep = library.prepare_chapter(ctx, chapter_id, profile_id)
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    provider = ctx.providers.get(prep["profile"]["provider"])
    frac = prep["pending_characters"] / max(1, prep["characters"])
    est = estimate(provider, prep["profile"]["model"], int(ch["word_count"] * frac), prep["pending_characters"])
    return {"total_segments": prep["total"], "reused_segments": prep["reused"],
            "pending_characters": prep["pending_characters"], "estimate": est,
            "large_job": ch["word_count"] * frac > ctx.settings.large_job_word_threshold,
            "profile_id": prep["profile"]["id"]}


class ChapterPatch(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


@router.patch("/chapters/{chapter_id}")
def rename(chapter_id: int, body: ChapterPatch, ctx=Depends(get_ctx)):
    library.rename_chapter(ctx, chapter_id, body.title)
    return {"ok": True}


class Reorder(BaseModel):
    chapter_ids: list[int]


@router.post("/books/{book_id}/chapters/reorder")
def reorder(book_id: int, body: Reorder, ctx=Depends(get_ctx)):
    library.reorder_chapters(ctx, book_id, body.chapter_ids)
    return library.get_book(ctx, book_id)


class Split(BaseModel):
    at_paragraph: int
    new_title: str | None = None


@router.post("/chapters/{chapter_id}/split")
def split(chapter_id: int, body: Split, ctx=Depends(get_ctx)):
    return {"new_chapter_id": library.split_chapter(ctx, chapter_id, body.at_paragraph, body.new_title)}


@router.post("/chapters/{chapter_id}/merge-next")
def merge(chapter_id: int, ctx=Depends(get_ctx)):
    library.merge_with_next(ctx, chapter_id)
    return {"ok": True}


class NewChapter(BaseModel):
    title: str = Field("New Chapter", max_length=200)
    text: str
    position: int | None = None


@router.post("/books/{book_id}/chapters")
def create_chapter(book_id: int, body: NewChapter, ctx=Depends(get_ctx)):
    library.get_book(ctx, book_id, with_chapters=False)
    return {"id": library.create_chapter(ctx, book_id, body.title, body.text, body.position)}


@router.delete("/chapters/{chapter_id}")
def delete_chapter(chapter_id: int, ctx=Depends(get_ctx)):
    library.delete_chapter(ctx, chapter_id)
    return {"ok": True}
