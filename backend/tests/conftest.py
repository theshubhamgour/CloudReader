from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.context import AppContext
from app.main import create_app
from app.providers.base import (Capabilities, ModelInfo, SynthesisRequest, SynthesisResult, TTSError,
                                TTSProvider, Voice)
from app.providers.demo import DemoProvider, tone_wav
from app.providers.registry import ProviderRegistry

SAMPLE_TXT = """Punching Through the Clouds

Chapter One: The Ascent

Mara pressed her palm against the cold glass. Below, the city vanished into grey.

"We're above it now," Theo said. "Nothing can reach us here."

She did not answer. She was counting the seconds between the lightning and the thunder.

* * *

The engines hummed. Somewhere behind them, the storm was turning.

Chapter Two: Static

The radio crackled at dawn. Mara wondered whether anyone was still listening.

"Say something," Theo whispered. "Anything."
"""


class FakeProvider(TTSProvider):
    """Mock Gemini-like provider: deterministic tone audio, scriptable failures."""

    id = "fake"
    label = "Fake TTS"

    def __init__(self):
        self.calls: list[SynthesisRequest] = []
        self.fail_plan: list[TTSError | None] = []   # consumed one per call
        self.fail_texts: dict[str, TTSError] = {}    # always fail when text contains key

    def available(self):
        return True, ""

    def capabilities(self):
        return Capabilities(True, True, "instruction", False, True, 2)

    def models(self):
        return [ModelInfo("fake-tts", "Fake", pricing=[(None, 1.0, 10.0)], audio_tokens_per_second=25)]

    def voices(self):
        return [Voice("Alpha", "Alpha"), Voice("Beta", "Beta")]

    def synthesize(self, req):
        self.calls.append(req)
        for key, err in self.fail_texts.items():
            if key in req.text:
                raise err
        if self.fail_plan:
            err = self.fail_plan.pop(0)
            if err:
                raise err
        seconds = max(1.0, len(req.text) / 15)
        return SynthesisResult(tone_wav(seconds), "audio/wav", input_tokens=len(req.text) // 4,
                               output_tokens=int(seconds * 25))


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", start_worker=False, use_keychain=False, gemini_api_key=None,
                    retry_base_delay_s=0.0, retry_max_delay_s=0.0, segment_target_chars=200,
                    segment_max_chars=400, segment_first_chars=120, tts_concurrency=1)


@pytest.fixture
def fake():
    return FakeProvider()


@pytest.fixture
def registry(settings, fake):
    reg = ProviderRegistry.from_settings(settings)
    reg.set(fake)
    return reg


@pytest.fixture
def ctx(settings, registry):
    return AppContext.create(settings, registry)


@pytest.fixture
def client(settings, registry):
    app = create_app(settings, registry)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_profile(ctx):
    return ctx.db.execute(
        "INSERT INTO narration_profiles (name, provider, model, voice, style_key, pace, is_default) "
        "VALUES ('Fake','fake','fake-tts','Alpha','natural','natural',0)")


def make_docx(paragraphs: list[tuple[str, str | None]]) -> bytes:
    import docx

    d = docx.Document()
    for text, style in paragraphs:
        if style == "Title":
            d.add_heading(text, level=0)
        elif style and style.startswith("Heading"):
            d.add_heading(text, level=int(style[-1]))
        else:
            d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
