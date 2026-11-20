from __future__ import annotations

from ..config import Settings
from .base import TTSProvider
from .demo import DemoProvider
from .gemini import GeminiTTSProvider


class ProviderRegistry:
    def __init__(self, providers: dict[str, TTSProvider]):
        self._providers = providers

    @classmethod
    def from_settings(cls, s: Settings) -> "ProviderRegistry":
        return cls({
            "gemini": GeminiTTSProvider(s.resolved_gemini_key(), s.tts_request_timeout_s),
            "demo": DemoProvider(),
        })

    def get(self, provider_id: str) -> TTSProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unknown provider '{provider_id}'")
        return self._providers[provider_id]

    def all(self) -> list[TTSProvider]:
        return list(self._providers.values())

    def set(self, provider: TTSProvider) -> None:
        self._providers[provider.id] = provider
