from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..services import export, generation
from ..services.costs import actual_usage
from .deps import get_ctx

router = APIRouter(prefix="/api", tags=["generation"])


class StartJob(BaseModel):
    chapter_id: int
    profile_id: int | None = None


@router.post("/jobs")
def start(body: StartJob, ctx=Depends(get_ctx)):
    return generation.start_job(ctx, body.chapter_id, body.profile_id)


class StartBook(BaseModel):
    profile_id: int | None = None
    from_chapter_id: int | None = None


@router.get("/books/{book_id}/plan")
def plan_book(book_id: int, profile_id: int | None = None, ctx=Depends(get_ctx)):
    """Cost and size of generating every unfinished chapter. Makes no API calls."""
    return generation.book_plan(ctx, book_id, profile_id)


@router.post("/books/{book_id}/generate")
def generate_book(book_id: int, body: StartBook, ctx=Depends(get_ctx)):
    if body.profile_id:
        ctx.db.execute("UPDATE books SET narration_profile_id=? WHERE id=?", (body.profile_id, book_id))
    return generation.start_book(ctx, book_id, body.profile_id, body.from_chapter_id)


@router.post("/books/{book_id}/cancel")
def cancel_book(book_id: int, ctx=Depends(get_ctx)):
    ids = [r["id"] for r in ctx.db.query("SELECT id FROM jobs WHERE book_id=? AND status IN ('pending','processing')", (book_id,))]
    for i in ids:
        generation.cancel_job(ctx, i)
    return {"cancelled": len(ids)}


@router.get("/jobs")
def list_jobs(limit: int = 50, ctx=Depends(get_ctx)):
    ids = [r["id"] for r in ctx.db.query("SELECT id FROM jobs ORDER BY id DESC LIMIT ?", (min(limit, 200),))]
    return [generation.get_job(ctx, i) for i in ids]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, ctx=Depends(get_ctx)):
    return generation.get_job(ctx, job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, ctx=Depends(get_ctx)):
    return generation.cancel_job(ctx, job_id)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, ctx=Depends(get_ctx)):
    j = generation.get_job(ctx, job_id)
    if j["status"] in ("pending", "processing"):
        raise HTTPException(409, "This job is still running.")
    return generation.start_job(ctx, j["chapter_id"], j["profile_id"])


@router.post("/segments/{segment_id}/regenerate")
def regenerate(segment_id: int, ctx=Depends(get_ctx)):
    return generation.regenerate_segment(ctx, segment_id)


@router.get("/segments/{segment_id}/audio")
def segment_audio(segment_id: int, download: bool = False, ctx=Depends(get_ctx)):
    r = ctx.db.one("SELECT s.position, s.chapter_id, s.status, a.path, a.is_demo FROM segments s "
                   "JOIN audio_assets a ON a.cache_key=s.cache_key WHERE s.id=?", (segment_id,))
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404, "This segment has no audio yet.")
    ch = ctx.db.one("SELECT position FROM chapters WHERE id=?", (r["chapter_id"],))
    name = f"{'DEMO_' if r['is_demo'] else ''}ch{ch['position'] + 1:02d}_seg{r['position'] + 1:03d}.wav"
    return FileResponse(r["path"], media_type="audio/wav", filename=name if download else None)


@router.get("/usage")
def usage(ctx=Depends(get_ctx)):
    return actual_usage(ctx)


# ---------------------------------------------------------------- export

@router.get("/chapters/{chapter_id}/export")
def export_chapter(chapter_id: int, format: str = "mp3", ctx=Depends(get_ctx)):
    path, name = export.chapter_file(ctx, chapter_id, format)
    return FileResponse(path, media_type="audio/mpeg" if format == "mp3" else "audio/flac", filename=name)


@router.get("/books/{book_id}/export")
def export_book(book_id: int, format: str = "mp3", ctx=Depends(get_ctx)):
    path, name, skipped = export.book_zip(ctx, book_id, format)
    headers = {"X-Skipped-Chapters": str(len(skipped))}
    return FileResponse(path, media_type="application/zip", filename=name, headers=headers)
