"""Exports: chapter files and whole-book ZIPs. Incomplete audio is never passed off as complete."""
from __future__ import annotations

import zipfile
from pathlib import Path

from .generation import chapter_export_name
from .library import chapter_status, safe_filename


class IncompleteAudio(RuntimeError):
    pass


def chapter_file(ctx, chapter_id: int, fmt: str = "mp3") -> tuple[Path, str]:
    if fmt not in ("mp3", "flac"):
        raise ValueError("Format must be mp3 or flac.")
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    st = chapter_status(ctx, ch)
    if not st["audio_ready"]:
        detail = {
            "incomplete": f"{st['segments_failed']} segment(s) failed — retry them before exporting.",
            "generating": "This chapter is still generating.",
            "outdated": "The chapter text or narration settings changed since the audio was made. Regenerate it.",
        }.get(st["state"], "This chapter has no complete audio yet.")
        raise IncompleteAudio(detail)
    audio = ctx.db.one("SELECT * FROM chapter_audio WHERE chapter_id=?", (chapter_id,))
    path = Path(audio["mp3_path"] if fmt == "mp3" else audio["master_path"])
    return path, chapter_export_name(ch["position"], ch["title"], fmt, bool(audio["is_demo"]))


def book_zip(ctx, book_id: int, fmt: str = "mp3") -> tuple[Path, str, list[str]]:
    book = ctx.db.one("SELECT * FROM books WHERE id=?", (book_id,))
    if not book:
        raise KeyError("Book not found")
    folder = safe_filename(book["title"])
    chapters = ctx.db.query("SELECT * FROM chapters WHERE book_id=? ORDER BY position", (book_id,))
    included, skipped = [], []
    out = ctx.settings.tmp_dir / f"{folder}_{fmt}.zip"
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as z:  # audio is already compressed
        for ch in chapters:
            try:
                path, name = chapter_file(ctx, ch["id"], fmt)
            except IncompleteAudio:
                skipped.append(ch["title"])
                continue
            z.write(path, f"{folder}/{name}")
            included.append(name)
        if skipped:
            z.writestr(f"{folder}/MISSING_CHAPTERS.txt",
                       "These chapters were not included because their audio is not complete:\n\n"
                       + "\n".join(f"- {t}" for t in skipped) + "\n")
    if not included:
        out.unlink(missing_ok=True)
        raise IncompleteAudio("No chapter has complete audio yet.")
    return out, f"{folder}.zip", skipped
