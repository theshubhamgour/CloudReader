"""Narration styles and pacing, expressed as natural-language `style` instructions.

Gemini TTS documents a turn-level `speech_metadata.style` string for delivery, emotion
and pace. It has no numeric speed control, so pace is expressed in words. Providers
that do not accept style text simply ignore these strings (see provider capabilities).
"""
from __future__ import annotations

STYLES: dict[str, dict[str, str]] = {
    "natural": {
        "label": "Natural Storytelling",
        "description": "Conversational, warm and clear with natural pacing.",
        "instruction": "warm, conversational audiobook storytelling; clear and natural, "
                       "relaxed pacing, minimal theatrical exaggeration",
    },
    "cinematic": {
        "label": "Cinematic Storytelling",
        "description": "Deliberate pacing, controlled suspense, dramatic emphasis where earned.",
        "instruction": "cinematic audiobook narration; deliberate pacing, controlled suspense, "
                       "stronger dramatic emphasis where the story calls for it, expressive but never exaggerated",
    },
    "calm": {
        "label": "Calm and Reflective",
        "description": "Gentle pacing, understated emotion, natural pauses.",
        "instruction": "calm, reflective narration; gentle unhurried pacing, understated emotion, "
                       "natural pauses between thoughts",
    },
    "dialogue": {
        "label": "Expressive Dialogue",
        "description": "Conversational character delivery with clear shifts between speakers.",
        "instruction": "expressive audiobook storytelling; lively conversational delivery of dialogue, "
                       "natural changes in emphasis between speakers, narration stays clear",
    },
    "neutral": {
        "label": "Neutral Narration",
        "description": "Consistent delivery, clear pronunciation, minimal emotional variation.",
        "instruction": "neutral, consistent narration; clear pronunciation, steady pace, "
                       "minimal emotional variation",
    },
}

PACES: dict[str, dict[str, str]] = {
    "slow": {"label": "Slow", "instruction": "speaking slowly"},
    "relaxed": {"label": "Relaxed", "instruction": "speaking at a slightly slower, unhurried pace"},
    "natural": {"label": "Natural", "instruction": ""},
    "brisk": {"label": "Brisk", "instruction": "speaking at a slightly brisker pace"},
    "fast": {"label": "Fast", "instruction": "speaking rapidly"},
}

DIALOGUE_HINT = "voice quoted dialogue naturally, as the characters would say it"


def build_style_instruction(style_key: str, pace: str, delivery_notes: str = "",
                            analysis: dict | None = None) -> str:
    style = STYLES.get(style_key, STYLES["natural"])
    parts = [style["instruction"]]
    if p := PACES.get(pace, PACES["natural"])["instruction"]:
        parts.append(p)
    if analysis and analysis.get("dialogue_ratio", 0) >= 0.4 and style_key in ("natural", "cinematic", "dialogue"):
        parts.append(DIALOGUE_HINT)
    if notes := delivery_notes.strip():
        parts.append(notes[:400])
    return "; ".join(parts)
