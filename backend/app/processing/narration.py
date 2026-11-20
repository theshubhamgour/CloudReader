"""Local, heuristic passage analysis and TTS text preparation.

Nothing here changes the manuscript. `prepare_tts_text` produces the text sent to the
provider plus a replacement map from that text back to the exact source text.
No network calls: analysis runs entirely on this machine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCENE_BREAK_RE = re.compile(r"^\s*([*#~•·\-–—_]\s*){1,7}$")
QUOTE_RE = re.compile(r"[“\"]([^”\"]{2,})[”\"]")
THOUGHT_RE = re.compile(
    r"\b(I|he|she|they|we)\s+(thought|wondered|mused|reflected|realized|realised)\b", re.I
)


def is_scene_break(paragraph: str) -> bool:
    return bool(SCENE_BREAK_RE.match(paragraph))


def classify_paragraph(p: str) -> str:
    if is_scene_break(p):
        return "scene_transition"
    quoted = sum(len(m) for m in QUOTE_RE.findall(p))
    if quoted and quoted >= 0.5 * len(p):
        return "dialogue"
    if THOUGHT_RE.search(p):
        return "internal_thought"
    if quoted:
        return "mixed"
    return "narration"


def analyze_passage(paragraphs: list[str], character_names: list[str] | None = None) -> dict:
    types = [classify_paragraph(p) for p in paragraphs]
    text = "\n".join(paragraphs)
    quoted = sum(len(m) for m in QUOTE_RE.findall(text))
    dialogue_ratio = round(quoted / max(1, len(text)), 2)
    exclaims = text.count("!")
    intensity = "high" if exclaims >= 4 or (exclaims / max(1, len(paragraphs))) > 0.6 else "normal"
    characters = sorted({n for n in (character_names or []) if re.search(rf"\b{re.escape(n)}\b", text)})
    counts: dict[str, int] = {}
    for t in types:
        counts[t] = counts.get(t, 0) + 1
    dominant = max(counts, key=counts.get) if counts else "narration"
    return {
        "passage_type": dominant,
        "paragraph_types": types,
        "dialogue_ratio": dialogue_ratio,
        "emotional_intensity": intensity,
        "has_scene_transition": "scene_transition" in types,
        "characters": characters,
        "suggested_pacing": "slower" if dominant in ("internal_thought", "scene_transition") else "natural",
    }


@dataclass
class Rule:
    term: str
    spoken: str
    case_sensitive: bool = False
    kind: str = "pronunciation"


def prepare_tts_text(source: str, rules: list[Rule], *, supports_tags: bool,
                     title_prefix: str | None = None) -> tuple[str, list[dict]]:
    """Build provider text from `source`. Returns (tts_text, replacements).

    Each replacement records spans in both texts so any word in the generated
    narration can be traced back to the manuscript.
    """
    out: list[str] = []
    repl: list[dict] = []
    pos_out = 0

    def emit(s: str, *, src_start: int | None = None, src_end: int | None = None,
             original: str | None = None, kind: str | None = None):
        nonlocal pos_out
        if kind is not None:
            repl.append({"kind": kind, "original": original, "spoken": s,
                         "source_start": src_start, "source_end": src_end,
                         "tts_start": pos_out, "tts_end": pos_out + len(s)})
        out.append(s)
        pos_out += len(s)

    if title_prefix:
        t = title_prefix.strip()
        spoken = t if re.search(r"[.!?…]$", t) else t + "."
        spoken += (" <long pause>" if supports_tags else "") + "\n\n"
        emit(spoken, src_start=0, src_end=0, original="", kind="chapter_title")

    # One combined regex, longest terms first, so overlapping terms behave predictably.
    patterns: list[str] = []
    lookup: list[Rule] = []
    for r in sorted(rules, key=lambda r: -len(r.term)):
        if not r.term.strip():
            continue
        patterns.append(f"(?P<r{len(lookup)}>\\b{re.escape(r.term)}\\b)")
        lookup.append(r)
    # Scene breaks (whole line) and literal angle brackets.
    patterns.append(r"(?P<scene>(?m:^[ \t]*(?:[*#~•·\-–—_][ \t]*){1,7}$))")
    if supports_tags:
        patterns.append(r"(?P<lt><)|(?P<gt>>)")
    combined = re.compile("|".join(patterns)) if patterns else None
    ci_terms = {i for i, r in enumerate(lookup) if not r.case_sensitive}

    def matcher(text: str):
        if combined is None:
            return
        # Case-insensitivity per term: run a case-insensitive scan, then filter.
        flagged = re.compile(combined.pattern, re.IGNORECASE)
        for m in flagged.finditer(text):
            name = m.lastgroup
            if name and name.startswith("r"):
                idx = int(name[1:])
                if idx not in ci_terms and m.group(0) != lookup[idx].term:
                    continue
            yield m

    last = 0
    for m in matcher(source):
        emit(source[last:m.start()])
        name = m.lastgroup
        if name == "scene":
            emit("<long pause>" if supports_tags else "", src_start=m.start(), src_end=m.end(),
                 original=m.group(0), kind="scene_break")
        elif name == "lt":
            emit("(", src_start=m.start(), src_end=m.end(), original="<", kind="escape")
        elif name == "gt":
            emit(")", src_start=m.start(), src_end=m.end(), original=">", kind="escape")
        else:
            rule = lookup[int(name[1:])]
            emit(rule.spoken, src_start=m.start(), src_end=m.end(), original=m.group(0), kind=rule.kind)
        last = m.end()
    emit(source[last:])
    return "".join(out), repl
