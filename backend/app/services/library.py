"""Books, chapters and segment preparation."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..manuscript.chapters import count_words, detect_chapters, estimate_minutes
from ..manuscript.importers import ManuscriptError, extract_blocks
from ..processing.narration import Rule, analyze_passage, prepare_tts_text
from ..processing.segmenter import segment_paragraphs
from ..processing.styles import build_style_instruction
from .profiles import get_profile

AUDIO_PIPELINE_VERSION = "1"  # bump if TTS text preparation changes in a way that needs new audio


class ConflictError(RuntimeError):
    pass


def safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r"[^\w\s'-]", "", name, flags=re.UNICODE).strip()
    name = re.sub(r"[\s']+", "_", name)
    return (name[:max_len].strip("_") or "Untitled")


def paragraphs_of(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---------------------------------------------------------------- import

def import_manuscript(ctx, filename: str, data: bytes, title: str | None = None, author: str = "") -> dict:
    s = ctx.settings
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise ManuscriptError(f"File is larger than {s.max_upload_mb} MB.")
    base = Path(filename or "").name  # strips any directory components
    if not base or base.startswith("."):
        raise ManuscriptError("Invalid file name.")
    fmt, blocks = extract_blocks(base, data)
    detected_title, chapters = detect_chapters(blocks)
    sha = hashlib.sha256(data).hexdigest()

    stored = s.manuscripts_dir / f"{sha[:16]}_{safe_filename(Path(base).stem)}{Path(base).suffix.lower()}"
    if not stored.exists():
        stored.write_bytes(data)
        stored.chmod(0o444)  # the original is read-only; CloudReader never edits it

    book_title = (title or detected_title or title_from_filename(Path(base).stem)).strip()[:200]
    with ctx.db.tx() as c:
        book_id = c.execute(
            "INSERT INTO books (title, author, source_filename, source_path, source_sha256, source_format) "
            "VALUES (?,?,?,?,?,?)",
            (book_title, author.strip()[:200], base, str(stored), sha, fmt),
        ).lastrowid
        for i, ch in enumerate(chapters):
            text = "\n\n".join(ch.paragraphs)
            c.execute(
                "INSERT INTO chapters (book_id, position, title, text, word_count) VALUES (?,?,?,?,?)",
                (book_id, i, ch.title[:200], text, count_words(text)),
            )
    return get_book(ctx, book_id)


# ---------------------------------------------------------------- read models

def title_from_filename(stem: str) -> str:
    """'github-support_request' → 'Github Support Request'."""
    import re

    t = re.sub(r"[_\-]+", " ", stem)
    t = re.sub(r"\s+", " ", t).strip()
    return t.title() if t.islower() else t


def chapter_status(ctx, chapter: dict) -> dict:
    rows = ctx.db.query("SELECT status, COUNT(*) n FROM segments WHERE chapter_id=? GROUP BY status",
                        (chapter["id"],))
    counts = {r["status"]: r["n"] for r in rows}
    total = sum(counts.values())
    audio = ctx.db.one("SELECT * FROM chapter_audio WHERE chapter_id=?", (chapter["id"],))
    fp = segments_fingerprint(ctx, chapter["id"]) if total else None
    audio_ready = bool(audio and fp and audio["fingerprint"] == fp and counts.get("completed", 0) == total)
    active = ctx.db.one("SELECT id, status FROM jobs WHERE chapter_id=? AND status IN ('pending','processing') "
                        "ORDER BY id DESC LIMIT 1", (chapter["id"],))
    if active:
        state = "generating"
    elif audio_ready:
        state = "ready"
    elif counts.get("failed"):
        state = "incomplete"
    elif audio and not audio_ready:
        state = "outdated"
    elif counts.get("completed"):
        state = "partial"
    else:
        state = "not_generated"
    return {
        "state": state,
        "segments_total": total,
        "segments_completed": counts.get("completed", 0),
        "segments_failed": counts.get("failed", 0),
        "audio_ready": audio_ready,
        "duration_s": audio["duration_s"] if audio_ready else None,
        "is_demo": bool(audio["is_demo"]) if audio_ready else None,
        "narrator": audio["narrator"] if audio_ready else None,
        "active_job_id": active["id"] if active else None,
    }


def chapter_out(ctx, ch: dict, with_text: bool = False) -> dict:
    out = {k: ch[k] for k in ("id", "book_id", "position", "title", "word_count")}
    out["estimated_minutes"] = estimate_minutes(ch["word_count"])
    out["status"] = chapter_status(ctx, ch)
    if with_text:
        out["paragraphs"] = paragraphs_of(ch["text"])
    return out


def get_book(ctx, book_id: int, with_chapters: bool = True) -> dict:
    b = ctx.db.one("SELECT * FROM books WHERE id=?", (book_id,))
    if not b:
        raise KeyError("Book not found")
    chapters = ctx.db.query("SELECT * FROM chapters WHERE book_id=? ORDER BY position", (book_id,))
    chs = [chapter_out(ctx, c) for c in chapters]
    words = sum(c["word_count"] for c in chapters)
    prog = ctx.db.one("SELECT * FROM listening_progress WHERE book_id=?", (book_id,))
    ready = [c for c in chs if c["status"]["audio_ready"]]
    total_audio = sum(c["status"]["duration_s"] or 0 for c in ready)
    listened = 0.0
    if prog and prog["chapter_id"]:
        for c in ready:
            if c["id"] == prog["chapter_id"]:
                listened += min(prog["position_s"], c["status"]["duration_s"] or 0)
                break
            listened += c["status"]["duration_s"] or 0
    profile = get_profile(ctx, b["narration_profile_id"])
    out = {
        "id": b["id"], "title": b["title"], "author": b["author"],
        "source_filename": b["source_filename"], "source_format": b["source_format"],
        "has_cover": bool(b["cover_path"]),
        "created_at": b["created_at"],
        "chapter_count": len(chapters),
        "word_count": words,
        "estimated_minutes": estimate_minutes(words),
        "chapters_ready": len(ready),
        "audio_duration_s": total_audio,
        "listening_progress": round(listened / total_audio, 3) if total_audio else 0.0,
        "progress": prog and {"chapter_id": prog["chapter_id"], "position_s": prog["position_s"],
                              "playback_rate": prog["playback_rate"], "updated_at": prog["updated_at"]},
        "narration_profile_id": profile["id"] if profile else None,
        "any_generating": any(c["status"]["state"] == "generating" for c in chs),
    }
    if with_chapters:
        out["chapters"] = chs
    return out


# ---------------------------------------------------------------- chapter editing

def _assert_no_active_job(ctx, chapter_ids: list[int]):
    q = ",".join("?" * len(chapter_ids))
    if ctx.db.one(f"SELECT id FROM jobs WHERE chapter_id IN ({q}) AND status IN ('pending','processing')",
                  tuple(chapter_ids)):
        raise ConflictError("A generation job is running for this chapter. Cancel it first.")


def _renumber(c, book_id: int):
    ids = [r[0] for r in c.execute("SELECT id FROM chapters WHERE book_id=? ORDER BY position, id", (book_id,))]
    for i, cid in enumerate(ids):
        c.execute("UPDATE chapters SET position=? WHERE id=?", (-(i + 1), cid))
    for i, cid in enumerate(ids):
        c.execute("UPDATE chapters SET position=? WHERE id=?", (i, cid))


def rename_chapter(ctx, chapter_id: int, title: str) -> None:
    title = title.strip()
    if not title:
        raise ValueError("Title cannot be empty.")
    ctx.db.execute("UPDATE chapters SET title=?, updated_at=datetime('now') WHERE id=?", (title[:200], chapter_id))


def reorder_chapters(ctx, book_id: int, ordered_ids: list[int]) -> None:
    existing = {r["id"] for r in ctx.db.query("SELECT id FROM chapters WHERE book_id=?", (book_id,))}
    if set(ordered_ids) != existing or len(ordered_ids) != len(existing):
        raise ValueError("The new order must contain every chapter exactly once.")
    with ctx.db.tx() as c:
        for i, cid in enumerate(ordered_ids):
            c.execute("UPDATE chapters SET position=? WHERE id=?", (-(i + 1), cid))
        for i, cid in enumerate(ordered_ids):
            c.execute("UPDATE chapters SET position=? WHERE id=?", (i, cid))


def split_chapter(ctx, chapter_id: int, at_paragraph: int, new_title: str | None = None) -> int:
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    _assert_no_active_job(ctx, [chapter_id])
    paras = paragraphs_of(ch["text"])
    if not 0 < at_paragraph < len(paras):
        raise ValueError("Split point must be inside the chapter.")
    first, second = "\n\n".join(paras[:at_paragraph]), "\n\n".join(paras[at_paragraph:])
    with ctx.db.tx() as c:
        c.execute("UPDATE chapters SET text=?, word_count=?, updated_at=datetime('now') WHERE id=?",
                  (first, count_words(first), chapter_id))
        c.execute("UPDATE chapters SET position=position+1 WHERE book_id=? AND position>?",
                  (ch["book_id"], ch["position"]))
        new_id = c.execute(
            "INSERT INTO chapters (book_id, position, title, text, word_count) VALUES (?,?,?,?,?)",
            (ch["book_id"], ch["position"] + 1, (new_title or f"{ch['title']} (continued)")[:200],
             second, count_words(second)),
        ).lastrowid
        c.execute("DELETE FROM segments WHERE chapter_id=?", (chapter_id,))
        _renumber(c, ch["book_id"])
    return new_id


def merge_with_next(ctx, chapter_id: int) -> None:
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    nxt = ctx.db.one("SELECT * FROM chapters WHERE book_id=? AND position>? ORDER BY position LIMIT 1",
                     (ch["book_id"], ch["position"]))
    if not nxt:
        raise ValueError("This is the last chapter; there is nothing to merge with.")
    _assert_no_active_job(ctx, [chapter_id, nxt["id"]])
    text = ch["text"] + "\n\n" + nxt["text"]
    with ctx.db.tx() as c:
        c.execute("UPDATE chapters SET text=?, word_count=?, updated_at=datetime('now') WHERE id=?",
                  (text, count_words(text), chapter_id))
        c.execute("UPDATE listening_progress SET chapter_id=?, position_s=0 WHERE chapter_id=?", (chapter_id, nxt["id"]))
        c.execute("UPDATE bookmarks SET chapter_id=? WHERE chapter_id=?", (chapter_id, nxt["id"]))
        c.execute("DELETE FROM chapters WHERE id=?", (nxt["id"],))
        c.execute("DELETE FROM segments WHERE chapter_id=?", (chapter_id,))
        _renumber(c, ch["book_id"])


def create_chapter(ctx, book_id: int, title: str, text: str, position: int | None = None) -> int:
    text = "\n\n".join(paragraphs_of(text.replace("\r\n", "\n")))
    if not text:
        raise ValueError("A chapter needs some text.")
    with ctx.db.tx() as c:
        n = c.execute("SELECT COUNT(*) FROM chapters WHERE book_id=?", (book_id,)).fetchone()[0]
        pos = n if position is None else max(0, min(position, n))
        c.execute("UPDATE chapters SET position=position+1 WHERE book_id=? AND position>=?", (book_id, pos))
        cid = c.execute("INSERT INTO chapters (book_id, position, title, text, word_count) VALUES (?,?,?,?,?)",
                        (book_id, pos, title.strip()[:200] or "New Chapter", text, count_words(text))).lastrowid
        _renumber(c, book_id)
    return cid


def delete_chapter(ctx, chapter_id: int) -> None:
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    _assert_no_active_job(ctx, [chapter_id])
    with ctx.db.tx() as c:
        c.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
        _renumber(c, ch["book_id"])


# ---------------------------------------------------------------- segment preparation

def cache_key_for(tts_text: str, provider: str, model: str, voice: str, style: str,
                  language: str | None, variant: int) -> str:
    payload = json.dumps({
        "v": AUDIO_PIPELINE_VERSION, "text": tts_text, "provider": provider, "model": model,
        "voice": voice, "style": style, "language": language or "", "variant": variant,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def pronunciation_rules(ctx, book_id: int, chapter_id: int | None) -> list[Rule]:
    rows = ctx.db.query(
        "SELECT * FROM pronunciations WHERE book_id=? AND (chapter_id IS NULL OR chapter_id=?)",
        (book_id, chapter_id or -1))
    # Chapter-specific entries override book-wide entries for the same term.
    by_term: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["chapter_id"] is not None):
        by_term[r["term"].lower()] = r
    return [Rule(r["term"], r["replacement"], bool(r["case_sensitive"])) for r in by_term.values()]


def plan_segments(ctx, chapter: dict, profile: dict, previous: dict[tuple[int, str], int] | None = None) -> list[dict]:
    """Compute the segment list for a chapter under a profile (pure, no DB writes)."""
    s = ctx.settings
    provider = ctx.providers.get(profile["provider"])
    caps = provider.capabilities()
    paras = paragraphs_of(chapter["text"])
    characters = [r["name"] for r in ctx.db.query("SELECT name FROM characters WHERE book_id=?",
                                                  (chapter["book_id"],))]
    rules = pronunciation_rules(ctx, chapter["book_id"], chapter["id"])
    out = []
    for i, seg in enumerate(segment_paragraphs(paras, s.segment_target_chars, s.segment_max_chars, s.segment_first_chars)):
        analysis = analyze_passage(seg.text.split("\n\n"), characters)
        tts_text, repl = prepare_tts_text(seg.text, rules, supports_tags=caps.inline_tags,
                                          title_prefix=chapter["title"] if i == 0 else None)
        style = build_style_instruction(profile["style_key"], profile["pace"], profile["delivery_notes"],
                                        analysis) if caps.style_instructions else ""
        variant = (previous or {}).get((i, seg.text), 0)
        out.append({
            "position": i, "source_text": seg.text, "tts_text": tts_text,
            "replacements": json.dumps(repl, ensure_ascii=False),
            "analysis": json.dumps(analysis), "style_instruction": style,
            "paragraph_start": seg.paragraph_start, "paragraph_end": seg.paragraph_end,
            "variant": variant,
            "cache_key": cache_key_for(tts_text, profile["provider"], profile["model"], profile["voice"],
                                       style, profile.get("language"), variant),
        })
    return out


def prepare_chapter(ctx, chapter_id: int, profile_id: int | None = None) -> dict:
    """Sync the chapter's segment rows with the current text and profile.

    Segments whose cache key already has audio are marked completed (no API call).
    """
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    book = ctx.db.one("SELECT * FROM books WHERE id=?", (ch["book_id"],))
    profile = get_profile(ctx, profile_id or book["narration_profile_id"])
    _assert_no_active_job(ctx, [chapter_id])
    old = ctx.db.query("SELECT position, source_text, variant FROM segments WHERE chapter_id=?", (chapter_id,))
    previous = {(r["position"], r["source_text"]): r["variant"] for r in old}
    planned = plan_segments(ctx, ch, profile, previous)
    reused = pending_chars = 0
    with ctx.db.tx() as c:
        c.execute("DELETE FROM segments WHERE chapter_id=?", (chapter_id,))
        for p in planned:
            asset = c.execute("SELECT path FROM audio_assets WHERE cache_key=?", (p["cache_key"],)).fetchone()
            done = bool(asset and Path(asset[0]).exists())
            reused += done
            pending_chars += 0 if done else len(p["tts_text"])
            c.execute(
                "INSERT INTO segments (chapter_id, position, source_text, tts_text, replacements, analysis, "
                "style_instruction, paragraph_start, paragraph_end, variant, cache_key, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (chapter_id, p["position"], p["source_text"], p["tts_text"], p["replacements"], p["analysis"],
                 p["style_instruction"], p["paragraph_start"], p["paragraph_end"], p["variant"],
                 p["cache_key"], "completed" if done else "pending"),
            )
    return {"profile": profile, "total": len(planned), "reused": reused,
            "characters": sum(len(p["tts_text"]) for p in planned), "pending_characters": pending_chars}


def segments_fingerprint(ctx, chapter_id: int) -> str:
    keys = [r["cache_key"] for r in ctx.db.query(
        "SELECT cache_key FROM segments WHERE chapter_id=? ORDER BY position", (chapter_id,))]
    s = ctx.settings
    payload = json.dumps([keys, s.inter_segment_silence_ms, s.loudness_target_lufs, s.mp3_bitrate])
    return hashlib.sha256(payload.encode()).hexdigest()
