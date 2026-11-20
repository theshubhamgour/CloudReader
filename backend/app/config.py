"""Application settings. Values come from environment variables or `backend/.env`.

Branding lives here too so the product name can be changed in one place.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_prefix="CLOUDREADER_", extra="ignore"
    )

    app_name: str = "CloudReader"
    app_tagline: str = "AI Audiobook Studio"

    data_dir: Path = PROJECT_DIR / "data"
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_origins: list[str] = ["http://127.0.0.1:3000", "http://localhost:3000"]

    # Gemini. The key is read from GEMINI_API_KEY (no prefix) as the SDK documents,
    # or CLOUDREADER_GEMINI_API_KEY. Never stored in the database.
    gemini_api_key: str | None = None
    gemini_default_model: str = "gemini-3.8-flash-tts"
    tts_request_timeout_s: float = 180.0

    # Segmentation (characters). Gemini allows 8,192 input tokens per request;
    # we stay far below that for quality and cheap retries.
    segment_target_chars: int = 2200
    segment_max_chars: int = 4000
    # The first segment of each chapter is short so playback can start within seconds.
    segment_first_chars: int = 180
    # Segments synthesised in parallel. Gemini runs ~2-3x real time per request, so 4
    # keeps generation well ahead of listening. Lower it if you hit free-tier rate limits.
    tts_concurrency: int = 4

    max_retries: int = 4
    retry_base_delay_s: float = 2.0
    retry_max_delay_s: float = 60.0

    max_upload_mb: int = 50
    large_job_word_threshold: int = 20000
    inter_segment_silence_ms: int = 450
    loudness_target_lufs: float = -18.0
    mp3_bitrate: str = "128k"

    # Run the worker thread (tests disable it and drive the worker directly).
    start_worker: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "cloudreader.db"

    @property
    def manuscripts_dir(self) -> Path:
        return self.data_dir / "manuscripts"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.manuscripts_dir, self.audio_dir, self.tmp_dir,
                  self.logs_dir, self.audio_dir / "segments", self.audio_dir / "chapters",
                  self.audio_dir / "previews", self.data_dir / "covers"):
            d.mkdir(parents=True, exist_ok=True)

    # Look up / store the API key in the macOS Keychain (tests turn this off).
    use_keychain: bool = True

    def gemini_key_source(self) -> tuple[str | None, str]:
        """(key, source) where source is 'env', 'keychain' or 'none'."""
        import os

        if key := (self.gemini_api_key or os.environ.get("GEMINI_API_KEY")):
            return key, "env"
        if self.use_keychain:
            from .secrets import GEMINI, get_secret

            if key := get_secret(GEMINI):
                return key, "keychain"
        return None, "none"

    def resolved_gemini_key(self) -> str | None:
        return self.gemini_key_source()[0]


@lru_cache
def get_settings() -> Settings:
    return Settings()
