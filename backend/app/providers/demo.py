"""Demo provider — NOT AI narration.

Uses the macOS `say` command when available so the whole pipeline (segments, assembly,
player, export) can be exercised without an API key. Falls back to a quiet test tone.
Every asset it produces is flagged `is_demo` and labelled as such in the UI.
"""
from __future__ import annotations

import io
import math
import re
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from .base import (Capabilities, ModelInfo, SynthesisRequest, SynthesisResult, TTSError,
                   TTSProvider, Voice)

DEMO_VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Reed (English (US))", "Flo (English (UK))"]
TONE_VOICE = "test-tone"


def tone_wav(seconds: float, sample_rate: int = 24000, freq: float = 220.0) -> bytes:
    n = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / 2400, (n - i) / 2400)
            frames += struct.pack("<h", int(3000 * env * math.sin(2 * math.pi * freq * i / sample_rate)))
        w.writeframes(bytes(frames))
    return buf.getvalue()


class DemoProvider(TTSProvider):
    id = "demo"
    label = "Demo voice (macOS system speech — not AI)"
    is_demo = True

    def __init__(self):
        self._say = shutil.which("say")
        self._voices: list[Voice] | None = None

    def available(self) -> tuple[bool, str]:
        return True, ""

    def capabilities(self) -> Capabilities:
        return Capabilities(
            style_instructions=False, inline_tags=False, speed_control="none",
            language_selection=False, voice_preview=True, multi_speaker=0,
            notes=["Demo mode uses the built-in macOS voice so you can try the app without an API key. "
                   "It is not AI narration and ignores narration styles."],
        )

    def models(self) -> list[ModelInfo]:
        return [ModelInfo("macos-say" if self._say else "tone", "macOS speech" if self._say else "Test tone",
                          "Demo only")]

    def voices(self) -> list[Voice]:
        if self._voices is None:
            installed: set[str] = set()
            if self._say:
                try:
                    out = subprocess.run([self._say, "-v", "?"], capture_output=True, text=True, timeout=10).stdout
                    installed = {re.split(r"\s{2,}", l.strip())[0] for l in out.splitlines() if l.strip()}
                except Exception:
                    installed = set()
            vs = [Voice(v, v.split(" (")[0], "macOS system voice") for v in DEMO_VOICES if v in installed]
            self._voices = vs or [Voice(TONE_VOICE, "Test tone", "Silent-ish tone; no speech available")]
        return self._voices

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        text = req.text.strip()
        if not text:
            raise TTSError("Nothing to synthesize.", transient=False, code="empty")
        if not self._say or req.voice == TONE_VOICE:
            words = len(text.split())
            return SynthesisResult(tone_wav(max(0.5, min(words / 2.6, 600))), "audio/wav", is_demo=True)
        with tempfile.TemporaryDirectory() as d:
            src, out = Path(d, "in.txt"), Path(d, "out.wav")
            src.write_text(text, encoding="utf-8")
            r = subprocess.run(
                [self._say, "-v", req.voice, "-f", str(src), "-o", str(out),
                 "--file-format=WAVE", "--data-format=LEI16@24000"],
                capture_output=True, text=True, timeout=600,
            )
            if r.returncode != 0 or not out.exists():
                raise TTSError("The macOS demo voice failed.", transient=False, code="demo_failed",
                               detail=r.stderr[:300])
            return SynthesisResult(out.read_bytes(), "audio/wav", is_demo=True)
