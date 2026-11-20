"""Google Gemini TTS via the official google-genai SDK (Interactions API).

Verified against https://ai.google.dev/gemini-api/docs/speech-generation (2026-10-28)
and google-genai 2.34.0. See docs/GEMINI_TTS_NOTES.md.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading

import httpx

from .base import (Capabilities, ModelInfo, SynthesisRequest, SynthesisResult, TTSError,
                   TTSProvider, Voice)

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com"

# (name, documented descriptor)
PREBUILT_VOICES = [
    ("Zephyr", "Bright"), ("Puck", "Upbeat"), ("Charon", "Informative"), ("Kore", "Firm"),
    ("Fenrir", "Excitable"), ("Leda", "Youthful"), ("Orus", "Firm"), ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"), ("Autonoe", "Bright"), ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"), ("Umbriel", "Easy-going"), ("Algieba", "Smooth"),
    ("Despina", "Smooth"), ("Erinome", "Clear"), ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"), ("Laomedeia", "Upbeat"), ("Achernar", "Soft"),
    ("Alnilam", "Firm"), ("Schedar", "Even"), ("Gacrux", "Mature"), ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"), ("Zubenelgenubi", "Casual"), ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"), ("Sadaltager", "Knowledgeable"), ("Sulafat", "Warm"),
]

MODELS = [
    ModelInfo(
        "gemini-3.8-flash-tts", "Gemini 3.8 Flash TTS",
        "Highest fidelity and most expressive. Recommended for audiobooks.",
        max_input_tokens=8192,
        pricing=[("2026-12-31", 0.50, 9.00), (None, 1.00, 18.00)],
        audio_tokens_per_second=25,
    ),
    ModelInfo(
        "gemini-3.8-flash-lite-tts", "Gemini 3.8 Flash-Lite TTS",
        "Faster and cheaper; slightly less expressive.",
        max_input_tokens=8192,
        pricing=[("2026-12-31", 0.50, 6.00), (None, 1.00, 12.00)],
        audio_tokens_per_second=25,
    ),
]


class GeminiTTSProvider(TTSProvider):
    id = "gemini"
    label = "Google Gemini TTS"

    def __init__(self, api_key: str | None, timeout_s: float = 180.0, http_client: httpx.Client | None = None):
        self._api_key = api_key
        self._timeout = timeout_s
        self._http = http_client
        self._lock = threading.Lock()

    def available(self) -> tuple[bool, str]:
        if not self._api_key:
            return False, ("No Gemini API key configured. Add one in Settings, or set GEMINI_API_KEY in "
                           "backend/.env (see README → API key).")
        return True, ""

    def capabilities(self) -> Capabilities:
        return Capabilities(
            style_instructions=True, inline_tags=True, speed_control="instruction",
            language_selection=False, voice_preview=True, multi_speaker=2,
            notes=[
                "Delivery is guided by a natural-language style; the model usually, but not always, follows it.",
                "There is no numeric speed setting. Pace is requested in words; use the player's speed control for exact speed.",
                "Language is detected automatically from the text.",
                "Accent is a property of the voice; choose a different voice to change it.",
            ],
        )

    def models(self) -> list[ModelInfo]:
        return MODELS

    def voices(self) -> list[Voice]:
        return [Voice(n, n, d) for n, d in PREBUILT_VOICES]

    def _client(self) -> httpx.Client:
        # One shared, thread-safe HTTP client. We call the documented REST endpoint directly
        # (the same request google-genai sends) because the SDK silently retries 429s for as
        # long as the server's retry-after says — over an hour on the free tier — ignoring
        # the configured timeout. Here every request ends within `timeout_s`.
        with self._lock:
            if self._http is None:
                self._http = httpx.Client(base_url=API_BASE, timeout=httpx.Timeout(self._timeout, connect=15))
            return self._http

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        ok, why = self.available()
        if not ok:
            raise TTSError(why, transient=False, code="missing_api_key")
        self.validate(req.voice, req.model)
        content: dict = {"type": "text", "text": req.text}
        if req.style:
            content["annotations"] = [{"type": "speech_metadata", "style": req.style}]
        body = {
            "model": req.model,
            "input": [{"type": "user_input", "content": [content]}],
            "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
            "generation_config": {"speech_config": [{"voice": req.voice}]},
        }
        try:
            res = self._client().post("/v1beta/interactions", json=body, headers={"x-goog-api-key": self._api_key})
        except Exception as e:
            raise map_exception(e) from e
        if res.status_code != 200:
            raise error_from_response(res.status_code, res.text, res.headers.get("retry-after"))
        try:
            data = res.json()
        except ValueError as e:
            raise TTSError("Gemini returned a malformed response.", transient=True, code="malformed_response") from e
        audio = extract_audio(data)
        if not audio or not audio.get("data"):
            raise TTSError("Gemini returned a response without audio. The segment will be retried.",
                           transient=True, code="missing_audio")
        try:
            raw = base64.b64decode(audio["data"])
        except Exception as e:
            raise TTSError("Gemini returned malformed audio data.", transient=True, code="malformed_response") from e
        usage = data.get("usage") or {}
        return SynthesisResult(audio=raw, mime_type=str(audio.get("mime_type") or "audio/wav"),
                               input_tokens=usage.get("total_input_tokens"),
                               output_tokens=usage.get("total_output_tokens"))


def extract_audio(interaction: dict) -> dict | None:
    """Last audio item of the trailing model output — the same rule as the SDK's `output_audio`."""
    for step in reversed(interaction.get("steps") or []):
        if step.get("type") == "user_input":
            break
        if step.get("type") != "model_output":
            continue
        for item in reversed(step.get("content") or []):
            if item.get("type") == "audio":
                return item
    return None


class _HttpError(Exception):
    def __init__(self, status_code: int, body: str):
        super().__init__(body)
        self.status_code, self.body = status_code, body


def _human_wait(text: str) -> str | None:
    m = re.search(r"retry in ((?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?)", text)
    if not m or not m.group(1):
        return None
    return m.group(1).replace("h", " h ").replace("m", " min ").split(".")[0].replace("s", " s").strip()


def error_from_response(status: int, body: str, retry_after: str | None = None) -> TTSError:
    try:
        msg = json.loads(body).get("error", {}).get("message", "") or body
    except ValueError:
        msg = body
    if status == 429:
        wait = _human_wait(msg)
        if re.search(r"per day|requests per day|daily", msg, re.I):
            limit = re.search(r"limit: (\d+) requests per day", msg)
            return TTSError(
                f"Gemini's daily limit is used up{f' ({limit.group(1)} requests/day on the free tier)' if limit else ''}. "
                f"{f'It resets in about {wait}. ' if wait else ''}"
                "Narrating a book needs many requests, so enable billing on your API key's Google Cloud project "
                "(Google AI Studio → Usage & Billing) for much higher limits.",
                transient=False, code="daily_limit", detail=msg[:500])
        return TTSError("Gemini rate limit reached. CloudReader will slow down and retry. If this keeps happening, "
                        "lower parallel requests or enable billing on your key.", transient=True, code="quota", detail=msg[:500])
    return map_exception(_HttpError(status, msg))


def map_exception(e: Exception) -> TTSError:
    """Translate SDK / network exceptions into TTSError with a retry decision."""
    import httpx

    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    body = str(getattr(e, "body", "") or e)[:500]
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return TTSError("The request to Gemini timed out.", transient=True, code="timeout", detail=body)
    if isinstance(e, (httpx.NetworkError, httpx.TransportError, ConnectionError)):
        return TTSError("Network problem while contacting Gemini. Check your connection.",
                        transient=True, code="network", detail=body)
    if isinstance(status, int):
        if status == 401 or "API_KEY_INVALID" in body or "API key not valid" in body:
            return TTSError("The Gemini API key was rejected. Check the key in Settings.",
                            transient=False, code="invalid_api_key", detail=body)
        if status == 403:
            return TTSError("Gemini refused the request (permission denied). The key may not have "
                            "access to this model or region.", transient=False, code="permission", detail=body)
        if status == 429:
            return TTSError("Gemini rate limit or quota reached. Generation will back off and retry; "
                            "if it keeps failing, check your quota in Google AI Studio.",
                            transient=True, code="quota", detail=body)
        if status == 404:
            return TTSError("The selected Gemini model was not found. It may have been renamed or retired.",
                            transient=False, code="unsupported_model", detail=body)
        if status == 400:
            if "token" in body.lower() and ("exceed" in body.lower() or "too long" in body.lower()):
                return TTSError("The segment is too large for the model.", transient=False,
                                code="request_too_large", detail=body)
            if "voice" in body.lower():
                return TTSError("Gemini rejected the voice configuration.", transient=False,
                                code="invalid_voice", detail=body)
            if "safety" in body.lower() or "blocked" in body.lower():
                return TTSError("Gemini declined to synthesize this passage (content filter).",
                                transient=False, code="blocked", detail=body)
            return TTSError("Gemini rejected the request as invalid.", transient=False,
                            code="bad_request", detail=body)
        if status >= 500:
            return TTSError("Gemini had a temporary server error.", transient=True, code="server", detail=body)
    return TTSError(f"Unexpected error from Gemini: {type(e).__name__}", transient=True,
                    code="unknown", detail=body)
