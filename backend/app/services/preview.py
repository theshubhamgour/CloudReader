"""Short auditions: try a voice/style on a passage before generating a chapter."""
from __future__ import annotations

from ..audio import ffmpeg
from ..processing.narration import analyze_passage, prepare_tts_text
from ..processing.segmenter import split_sentences
from ..providers.base import SynthesisRequest, TTSError
from ..processing.styles import build_style_instruction
from .library import cache_key_for, paragraphs_of, pronunciation_rules

MAX_PREVIEW_CHARS = 1500
VOICE_SAMPLE = ("The clouds parted slowly, and for the first time in weeks, she let herself believe "
                "the storm might finally be over.")


def default_preview_text(chapter_text: str, limit: int = 700) -> str:
    """First few whole sentences of the chapter, keeping paragraph breaks."""
    paras: list[str] = []
    used = 0
    for p in paragraphs_of(chapter_text):
        kept = []
        for s in split_sentences(p):
            if used and used + len(s) + 1 > limit:
                break
            kept.append(s)
            used += len(s) + 1
        if kept:
            paras.append(" ".join(kept))
        if len(kept) < len(split_sentences(p)) or used > limit * 0.6:
            break
    return "\n\n".join(paras)


def create_preview(ctx, *, provider_id: str, model: str, voice: str, style_key: str, pace: str,
                   delivery_notes: str = "", text: str | None = None, chapter_id: int | None = None,
                   book_id: int | None = None) -> dict:
    provider = ctx.providers.get(provider_id)
    ok, why = provider.available()
    if not ok:
        raise PermissionError(why)
    if not text and chapter_id:
        ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
        if not ch:
            raise KeyError("Chapter not found")
        book_id = ch["book_id"]
        text = default_preview_text(ch["text"])
    text = (text or VOICE_SAMPLE).strip()
    if len(text) > MAX_PREVIEW_CHARS:
        raise ValueError(f"Preview text is limited to {MAX_PREVIEW_CHARS} characters to keep auditions cheap.")
    caps = provider.capabilities()
    rules = pronunciation_rules(ctx, book_id, chapter_id) if book_id else []
    tts_text, repl = prepare_tts_text(text, rules, supports_tags=caps.inline_tags)
    analysis = analyze_passage(paragraphs_of(text))
    style = build_style_instruction(style_key, pace, delivery_notes, analysis) if caps.style_instructions else ""
    key = cache_key_for(tts_text, provider_id, model, voice, style, None, 0)
    path = ctx.settings.audio_dir / "previews" / f"{key}.wav"
    cached = path.exists()
    if not cached:
        provider.validate(voice, model)
        result = provider.synthesize(SynthesisRequest(text=tts_text, voice=voice, model=model, style=style))
        try:
            wav = ffmpeg.to_standard_wav(result.audio, result.mime_type)
            info = ffmpeg.validate_speech_wav(wav, len(tts_text))
        except ffmpeg.AudioError as e:
            raise TTSError(f"The provider returned unusable audio: {e}", transient=True, code="bad_audio") from e
        path.write_bytes(wav)
        ctx.db.execute("INSERT INTO usage_log (provider, model, kind, characters, input_tokens, output_tokens, "
                       "audio_seconds) VALUES (?,?,?,?,?,?,?)",
                       (provider_id, model, "preview", len(tts_text), result.input_tokens, result.output_tokens,
                        info.duration_s))
    return {
        "key": key, "url": f"/api/previews/{key}.wav", "cached": cached, "is_demo": provider.is_demo,
        "text": text, "tts_text": tts_text, "replacements": repl, "style_instruction": style,
        "provider": provider_id, "model": model, "voice": voice,
    }
