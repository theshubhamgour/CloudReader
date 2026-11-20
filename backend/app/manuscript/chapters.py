"""Chapter detection from extracted blocks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .importers import Block

WORDS_PER_MINUTE = 155  # typical audiobook narration pace

_NUM_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
    "eighty|ninety|hundred"
)
CHAPTER_RE = re.compile(
    rf"^(chapter|ch\.|part|book)\s+([0-9]+|[ivxlcdm]+|(?:{_NUM_WORDS})(?:[-\s](?:{_NUM_WORDS}))*)\b"
    r"|^(prologue|epilogue|interlude|introduction|preface|foreword|afterword|acknowledg(e)?ments)\b"
    r"|^([0-9]{1,3}|[IVXLC]{1,7})\.?$",
    re.IGNORECASE,
)


@dataclass
class DetectedChapter:
    title: str
    paragraphs: list[str] = field(default_factory=list)


def count_words(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def estimate_minutes(words: int) -> float:
    return round(words / WORDS_PER_MINUTE, 1)


def _is_chapter_heading(text: str) -> bool:
    return len(text) <= 80 and bool(CHAPTER_RE.match(text.strip()))


def _looks_like_subtitle(text: str) -> bool:
    return len(text) <= 60 and not re.search(r"[.!?…\"”]$", text) and count_words(text) <= 8


def _looks_like_title(text: str) -> bool:
    t = text.strip()
    return 0 < len(t) <= 80 and len(t.split()) <= 12 and t[-1] not in ".!?:;,\"'”’"


def detect_chapters(blocks: list[Block]) -> tuple[str | None, list[DetectedChapter]]:
    """Returns (detected book title, chapters). Never drops text."""
    title = next((b.text for b in blocks if b.kind == "title"), None)
    headings = [b for b in blocks if b.kind == "heading"]

    # Choose what counts as a chapter boundary.
    if headings:
        chapterish = [h for h in headings if _is_chapter_heading(h.text)]
        if chapterish:
            level = min(h.level for h in chapterish)
        else:
            levels = sorted({h.level for h in headings})
            level = next((lv for lv in levels if sum(h.level == lv for h in headings) >= 2), levels[0])
        # A single level-1 heading above repeated level-2 headings is the book title.
        top = [h for h in headings if h.level == level]
        if len(top) == 1 and any(h.level > level for h in headings) and not _is_chapter_heading(top[0].text):
            title = title or top[0].text
            top[0].kind = "title"
            level = min(h.level for h in headings if h.kind == "heading" and h.level > level)
        # A lone heading above the chapter level, before the first chapter, is the book title.
        above = [h for h in headings if h.kind == "heading" and h.level < level]
        if len(above) == 1 and headings.index(above[0]) == 0:
            title = title or above[0].text
            above[0].kind = "title"
        is_boundary = lambda b: b.kind == "heading" and b.level == level
    else:
        is_boundary = lambda b: b.kind == "paragraph" and _is_chapter_heading(b.text)

    chapters: list[DetectedChapter] = []
    front = DetectedChapter("Front Matter")
    current = front
    pending_subtitle = False
    for b in blocks:
        if b.kind == "title":
            continue
        if is_boundary(b):
            current = DetectedChapter(b.text)
            chapters.append(current)
            pending_subtitle = True
            continue
        if pending_subtitle and current is not front and not current.paragraphs:
            pending_subtitle = False
            if (b.kind == "heading" or _looks_like_subtitle(b.text)) and _is_chapter_heading(current.title):
                current.title = f"{current.title}: {b.text}"
                continue
        pending_subtitle = False
        current.paragraphs.append(b.text)

    # A lone short line before the first chapter (e.g. the title at the top of a .txt file)
    # is the book's title, not a chapter of its own.
    if chapters and len(front.paragraphs) == 1 and _looks_like_title(front.paragraphs[0]):
        title = title or front.paragraphs[0]
        front.paragraphs = []
    if front.paragraphs:
        if not chapters:
            front.title = "Full Text"  # no chapter headings: the whole document is one part
        chapters.insert(0, front)
    if not chapters:
        chapters = [DetectedChapter("Full Text", [b.text for b in blocks if b.kind != "title"])]
    return title, chapters
