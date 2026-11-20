"""Provider-neutral TTS interface.

Adding a provider (ElevenLabs, OpenAI, …) means implementing `TTSProvider` and
registering it in `registry.py`. Nothing else in the app knows provider details.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Voice:
    id: str
    name: str
    description: str = ""
    gender: str | None = None
    language: str | None = None


@dataclass
class ModelInfo:
    id: str
    label: str
    description: str = ""
    max_input_tokens: int | None = None
    # USD per 1M tokens; list of (valid_until ISO date or None, input, output)
    pricing: list[tuple[str | None, float, float]] = field(default_factory=list)
    audio_tokens_per_second: float | None = None


@dataclass
class Capabilities:
    style_instructions: bool          # accepts natural-language delivery instructions
    inline_tags: bool                 # understands inline tags such as <long pause>
    speed_control: str                # "none" | "instruction" | "numeric"
    language_selection: bool
    voice_preview: bool
    multi_speaker: int                # max speakers per request (0 = unsupported)
    notes: list[str] = field(default_factory=list)


@dataclass
class SynthesisRequest:
    text: str
    voice: str
    model: str
    style: str = ""
    language: str | None = None


@dataclass
class SynthesisResult:
    audio: bytes                      # complete audio file bytes
    mime_type: str                    # e.g. audio/wav
    input_tokens: int | None = None
    output_tokens: int | None = None
    is_demo: bool = False


class TTSError(Exception):
    """Provider error with a user-facing message and retry hint."""

    def __init__(self, message: str, *, transient: bool, code: str = "error", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.transient = transient
        self.code = code
        self.detail = detail


class TTSProvider(ABC):
    id: str
    label: str
    is_demo: bool = False

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, reason if not)."""

    @abstractmethod
    def capabilities(self) -> Capabilities: ...

    @abstractmethod
    def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def voices(self) -> list[Voice]: ...

    @abstractmethod
    def synthesize(self, req: SynthesisRequest) -> SynthesisResult: ...

    def validate(self, voice: str, model: str) -> None:
        if model not in {m.id for m in self.models()}:
            raise TTSError(f"Model '{model}' is not supported by {self.label}.", transient=False,
                           code="unsupported_model")
        if voice not in {v.id for v in self.voices()}:
            raise TTSError(f"Voice '{voice}' is not available for {self.label}.", transient=False,
                           code="invalid_voice")
