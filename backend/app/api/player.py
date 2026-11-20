from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..services.library import chapter_status
from .deps import get_ctx

router = APIRouter(prefix="/api", tags=["player"])


@router.get("/chapters/{chapter_id}/audio")
def chapter_audio(chapter_id: int, ctx=Depends(get_ctx)):
    """Streams the chapter MP3. Supports HTTP Range so the player can seek."""
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise HTTPException(404, "Chapter not found")
    if not chapter_status(ctx, ch)["audio_ready"]:
        raise HTTPException(409, "This chapter has no complete audio.")
    a = ctx.db.one("SELECT mp3_path FROM chapter_audio WHERE chapter_id=?", (chapter_id,))
    if not Path(a["mp3_path"]).exists():
        raise HTTPException(410, "The audio file is missing on disk. Regenerate the chapter.")
    return FileResponse(a["mp3_path"], media_type="audio/mpeg")


class Progress(BaseModel):
    chapter_id: int
    position_s: float = Field(..., ge=0)
    playback_rate: float = Field(1.0, ge=0.5, le=3.0)


@router.get("/books/{book_id}/progress")
def get_progress(book_id: int, ctx=Depends(get_ctx)):
    return ctx.db.one("SELECT * FROM listening_progress WHERE book_id=?", (book_id,)) or {}


@router.put("/books/{book_id}/progress")
def save_progress(book_id: int, body: Progress, ctx=Depends(get_ctx)):
    if not ctx.db.one("SELECT id FROM chapters WHERE id=? AND book_id=?", (body.chapter_id, book_id)):
        raise HTTPException(404, "Chapter not in this book")
    ctx.db.execute(
        "INSERT INTO listening_progress (book_id, chapter_id, position_s, playback_rate, updated_at) "
        "VALUES (?,?,?,?,datetime('now')) ON CONFLICT(book_id) DO UPDATE SET chapter_id=excluded.chapter_id, "
        "position_s=excluded.position_s, playback_rate=excluded.playback_rate, updated_at=excluded.updated_at",
        (book_id, body.chapter_id, body.position_s, body.playback_rate))
    ctx.db.execute("UPDATE books SET updated_at=datetime('now') WHERE id=?", (book_id,))
    return {"ok": True}


# sendBeacon on page unload can only POST.
@router.post("/books/{book_id}/progress")
def save_progress_beacon(book_id: int, body: Progress, ctx=Depends(get_ctx)):
    return save_progress(book_id, body, ctx)


@router.get("/progress/latest")
def latest_progress(ctx=Depends(get_ctx)):
    return ctx.db.one("SELECT * FROM listening_progress ORDER BY updated_at DESC LIMIT 1") or {}


class Bookmark(BaseModel):
    chapter_id: int
    position_s: float = Field(..., ge=0)
    label: str = Field("", max_length=200)


@router.get("/books/{book_id}/bookmarks")
def list_bookmarks(book_id: int, ctx=Depends(get_ctx)):
    return ctx.db.query("SELECT b.*, c.title chapter_title, c.position chapter_position FROM bookmarks b "
                        "JOIN chapters c ON c.id=b.chapter_id WHERE b.book_id=? ORDER BY c.position, b.position_s",
                        (book_id,))


@router.post("/books/{book_id}/bookmarks")
def add_bookmark(book_id: int, body: Bookmark, ctx=Depends(get_ctx)):
    if not ctx.db.one("SELECT id FROM chapters WHERE id=? AND book_id=?", (body.chapter_id, book_id)):
        raise HTTPException(404, "Chapter not in this book")
    bid = ctx.db.execute("INSERT INTO bookmarks (book_id, chapter_id, position_s, label) VALUES (?,?,?,?)",
                         (book_id, body.chapter_id, body.position_s, body.label))
    return ctx.db.one("SELECT * FROM bookmarks WHERE id=?", (bid,))


@router.delete("/bookmarks/{bid}")
def delete_bookmark(bid: int, ctx=Depends(get_ctx)):
    ctx.db.execute("DELETE FROM bookmarks WHERE id=?", (bid,))
    return {"ok": True}
