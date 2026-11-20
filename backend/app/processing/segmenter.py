"""Split a chapter into TTS-sized segments.

Rules, in order of preference:
1. Segments are runs of whole paragraphs, up to `target` characters.
2. A paragraph longer than `max_chars` is split between sentences.
3. Sentence splits never happen inside an open quotation.
4. A single sentence longer than `max_chars` (rare) is split at the last comma/space.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Includes the Devanagari danda (। ॥) so Hindi sentences split correctly.
_SENT_END = re.compile(r'([.!?…।॥]+[”"’\')\]]*)(\s+)')
_OPEN_Q, _CLOSE_Q = "“", "”"


@dataclass
class Segment:
    text: str
    paragraph_start: int
    paragraph_end: int  # inclusive


def split_sentences(paragraph: str) -> list[str]:
    """Sentence split that keeps quoted speech together."""
    out, start, depth_straight = [], 0, 0
    for m in _SENT_END.finditer(paragraph):
        chunk = paragraph[start:m.end(1)]
        curly_open = chunk.count(_OPEN_Q) - chunk.count(_CLOSE_Q)
        depth_straight = chunk.count('"') % 2
        if curly_open > 0 or depth_straight:
            continue  # inside a quotation — keep going
        nxt = paragraph[m.end():m.end() + 1]
        if nxt.islower():
            continue  # '"Go!" he said' — the sentence continues
        out.append(chunk.strip())
        start = m.end()
    tail = paragraph[start:].strip()
    if tail:
        out.append(tail)
    return out or [paragraph]


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    parts = []
    while len(sentence) > max_chars:
        cut = max(sentence.rfind(", ", 0, max_chars), sentence.rfind("; ", 0, max_chars))
        if cut < max_chars // 3:
            cut = sentence.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        parts.append(sentence[: cut + 1].strip())
        sentence = sentence[cut + 1:].strip()
    if sentence:
        parts.append(sentence)
    return parts


def _split_long_paragraph(p: str, target: int, max_chars: int) -> list[str]:
    pieces: list[str] = []
    for s in split_sentences(p):
        pieces.extend(_hard_split(s, max_chars) if len(s) > max_chars else [s])
    chunks, cur = [], ""
    for s in pieces:
        if cur and len(cur) + 1 + len(s) > target:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}" if cur else s
    if cur:
        chunks.append(cur)
    return chunks


def segment_paragraphs(paragraphs: list[str], target: int = 2200, max_chars: int = 4000,
                       first_target: int | None = None) -> list[Segment]:
    """`first_target` makes the opening segment short so listening can start sooner."""
    if target > max_chars:
        target = max_chars
    if first_target and len(paragraphs) > 0:
        return _with_short_head(paragraphs, first_target, target, max_chars)
    segs: list[Segment] = []
    buf: list[str] = []
    buf_start = 0

    def flush(end_idx: int):
        nonlocal buf
        if buf:
            segs.append(Segment("\n\n".join(buf), buf_start, end_idx))
            buf = []

    for i, p in enumerate(paragraphs):
        if len(p) > max_chars:
            flush(i - 1)
            for chunk in _split_long_paragraph(p, target, max_chars):
                segs.append(Segment(chunk, i, i))
            continue
        size = sum(len(b) + 2 for b in buf)
        if buf and size + len(p) > target:
            flush(i - 1)
        if not buf:
            buf_start = i
        buf.append(p)
    flush(len(paragraphs) - 1)
    return segs


def _with_short_head(paragraphs: list[str], first_target: int, target: int, max_chars: int) -> list[Segment]:
    """First segment ~first_target chars (whole sentences), the rest segmented normally."""
    p0 = paragraphs[0]
    if len(p0) > first_target:
        sents = split_sentences(p0)
        k, used = 0, 0
        while k < len(sents) and (k == 0 or used + len(sents[k]) <= first_target):
            used += len(sents[k]) + 1
            k += 1
        if k < len(sents):
            head = Segment(" ".join(sents[:k]), 0, 0)
            tail = segment_paragraphs([" ".join(sents[k:])] + paragraphs[1:], target, max_chars)
            return [head] + tail
        head_end = 0
    else:
        head_end, used = 0, len(p0)
        while head_end + 1 < len(paragraphs) and used + len(paragraphs[head_end + 1]) + 2 <= first_target:
            head_end += 1
            used += len(paragraphs[head_end]) + 2
    head = Segment("\n\n".join(paragraphs[: head_end + 1]), 0, head_end)
    tail = segment_paragraphs(paragraphs[head_end + 1:], target, max_chars)
    for t in tail:
        t.paragraph_start += head_end + 1
        t.paragraph_end += head_end + 1
    return [head] + tail
