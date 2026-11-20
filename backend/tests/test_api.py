"""End-to-end API tests with mocked providers (no network, no API credits)."""
import base64
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from app.providers.base import SynthesisRequest, TTSError
from app.providers.demo import tone_wav
from app.providers.gemini import GeminiTTSProvider
from app.services.generation import Worker

from .conftest import SAMPLE_TXT


def _import(client):
    r = client.post("/api/books/import", files={"file": ("novel.txt", SAMPLE_TXT.encode(), "text/plain")},
                    data={"author": "Test Author"})
    assert r.status_code == 200, r.text
    return r.json()


def _fake_profile(client):
    r = client.post("/api/profiles", json={"name": "Fake", "provider": "fake", "model": "fake-tts", "voice": "Alpha",
                                           "style_key": "cinematic", "pace": "relaxed"})
    assert r.status_code == 200, r.text
    return r.json()


def _generate(client, chapter_id, profile_id):
    r = client.post("/api/jobs", json={"chapter_id": chapter_id, "profile_id": profile_id})
    assert r.status_code == 200, r.text
    w = Worker(client.app.state.ctx, sleep=lambda s: None)
    while w.run_once():
        pass
    return client.get(f"/api/jobs/{r.json()['id']}").json()


def test_create_narration_profile_and_validation(client):
    p = _fake_profile(client)
    assert p["style_key"] == "cinematic"
    bad = client.post("/api/profiles", json={"name": "x", "provider": "fake", "model": "fake-tts", "voice": "Nope"})
    assert bad.status_code == 400 and "Voice" in bad.json()["detail"]


def test_prepare_shows_estimate_without_api_calls(client):
    book = _import(client)
    prof = _fake_profile(client)
    ch = book["chapters"][1]
    r = client.post(f"/api/chapters/{ch['id']}/prepare", params={"profile_id": prof["id"]}).json()
    assert r["estimate"]["is_estimate"] is True
    assert r["estimate"]["cost_usd"] is not None
    assert client.app.state.ctx.providers.get("fake").calls == []


def test_generate_play_export_and_progress(client):
    book = _import(client)
    prof = _fake_profile(client)
    ch = next(c for c in book["chapters"] if c["title"].startswith("Chapter One"))
    job = _generate(client, ch["id"], prof["id"])
    assert job["status"] == "completed", job

    # Streaming supports range requests (needed for seeking).
    r = client.get(f"/api/chapters/{ch['id']}/audio", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100

    # Export a completed chapter.
    r = client.get(f"/api/chapters/{ch['id']}/export", params={"format": "mp3"})
    assert r.status_code == 200
    assert 'filename="02_Chapter_One_The_Ascent.mp3"' in r.headers["content-disposition"] or \
           "Chapter_One_The_Ascent.mp3" in r.headers["content-disposition"]
    assert r.content[:3] == b"ID3"
    r = client.get(f"/api/chapters/{ch['id']}/export", params={"format": "flac"})
    assert r.content[:4] == b"fLaC"

    # Book export includes the ready chapter and lists missing ones.
    r = client.get(f"/api/books/{book['id']}/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert any(n.endswith("Chapter_One_The_Ascent.mp3") for n in names)
    assert any(n.endswith("MISSING_CHAPTERS.txt") for n in names)

    # Incomplete chapter cannot be exported as if complete.
    other = next(c for c in book["chapters"] if c["title"].startswith("Chapter Two"))
    r = client.get(f"/api/chapters/{other['id']}/export")
    assert r.status_code == 409

    # Save and resume listening progress.
    assert client.put(f"/api/books/{book['id']}/progress",
                      json={"chapter_id": ch["id"], "position_s": 4.5, "playback_rate": 1.25}).status_code == 200
    prog = client.get(f"/api/books/{book['id']}/progress").json()
    assert prog["position_s"] == 4.5 and prog["playback_rate"] == 1.25
    assert client.get("/api/progress/latest").json()["book_id"] == book["id"]
    b = client.get(f"/api/books/{book['id']}").json()
    assert b["listening_progress"] > 0 and b["progress"]["chapter_id"] == ch["id"]

    # Bookmarks.
    bm = client.post(f"/api/books/{book['id']}/bookmarks", json={"chapter_id": ch["id"], "position_s": 3}).json()
    assert client.get(f"/api/books/{book['id']}/bookmarks").json()[0]["id"] == bm["id"]


def test_progress_persists_across_restart(settings, registry):
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(settings, registry)) as c:
        book = _import(c)
        ch = book["chapters"][0]
        c.put(f"/api/books/{book['id']}/progress", json={"chapter_id": ch["id"], "position_s": 12})
    with TestClient(create_app(settings, registry)) as c:
        assert c.get(f"/api/books/{book['id']}/progress").json()["position_s"] == 12
        assert len(c.get("/api/books").json()) == 1


def test_missing_api_key_is_reported(client):
    gem = next(p for p in client.get("/api/providers").json() if p["id"] == "gemini")
    assert gem["available"] is False and "GEMINI_API_KEY" in gem["unavailable_reason"]
    book = _import(client)
    gid = next(p["id"] for p in client.get("/api/profiles").json() if p["provider"] == "gemini")
    r = client.post("/api/jobs", json={"chapter_id": book["chapters"][0]["id"], "profile_id": gid})
    assert r.status_code == 400 and "API key" in r.json()["detail"]
    r = client.post("/api/preview", json={"provider": "gemini", "model": "gemini-3.8-flash-tts", "voice": "Kore"})
    assert r.status_code == 400


def test_demo_mode_runs_and_is_labelled(client):
    demo = next(p for p in client.get("/api/providers").json() if p["id"] == "demo")
    assert demo["is_demo"] and "not AI" in demo["label"]
    r = client.post("/api/preview", json={"provider": "demo", "model": demo["models"][0]["id"],
                                          "voice": demo["voices"][0]["id"], "text": "Hello there, reader."})
    assert r.status_code == 200, r.text
    assert r.json()["is_demo"] is True
    assert client.get(r.json()["url"]).status_code == 200

    book = _import(client)
    did = next(p["id"] for p in client.get("/api/profiles").json() if p["provider"] == "demo")
    ch = book["chapters"][-1]
    job = _generate(client, ch["id"], did)
    assert job["status"] == "completed", job
    chapter = client.get(f"/api/chapters/{ch['id']}").json()
    assert chapter["status"]["is_demo"] is True
    assert "DEMO_" in client.get(f"/api/chapters/{ch['id']}/export").headers["content-disposition"]


# ---------------------------------------------------------------- Gemini provider (mocked HTTP)

import httpx  # noqa: E402

from app.providers.gemini import error_from_response  # noqa: E402


def _gemini(handler):
    seen = {}

    def wrapped(request: httpx.Request):
        seen["request"] = request
        return handler(request)

    client = httpx.Client(base_url="https://generativelanguage.googleapis.com", transport=httpx.MockTransport(wrapped))
    return GeminiTTSProvider("test-key", http_client=client), seen


def _interaction(audio_b64: str | None):
    content = [{"type": "audio", "mime_type": "audio/wav", "data": audio_b64}] if audio_b64 else [{"type": "text", "text": "hi"}]
    return {"steps": [{"type": "user_input", "content": []}, {"type": "model_output", "content": content}],
            "usage": {"total_input_tokens": 12, "total_output_tokens": 25}}


def test_gemini_request_shape_and_response_parsing():
    wav = base64.b64encode(tone_wav(1)).decode()
    prov, seen = _gemini(lambda r: httpx.Response(200, json=_interaction(wav)))
    res = prov.synthesize(SynthesisRequest("Hello.", "Kore", "gemini-3.8-flash-tts", style="warm"))
    assert res.audio[:4] == b"RIFF" and res.input_tokens == 12 and res.output_tokens == 25
    req = seen["request"]
    assert req.url.path == "/v1beta/interactions" and req.headers["x-goog-api-key"] == "test-key"
    body = json.loads(req.content)
    assert body["model"] == "gemini-3.8-flash-tts"
    assert body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert body["input"][0]["content"][0]["annotations"] == [{"type": "speech_metadata", "style": "warm"}]
    assert body["response_format"]["type"] == "audio"


def test_gemini_missing_audio_is_transient_error():
    prov, _ = _gemini(lambda r: httpx.Response(200, json=_interaction(None)))
    with pytest.raises(TTSError) as e:
        prov.synthesize(SynthesisRequest("Hello.", "Kore", "gemini-3.8-flash-tts"))
    assert e.value.code == "missing_audio" and e.value.transient


def test_gemini_rejects_unknown_voice_and_model():
    prov, _ = _gemini(lambda r: httpx.Response(500))
    with pytest.raises(TTSError, match="Voice"):
        prov.synthesize(SynthesisRequest("Hi", "NotAVoice", "gemini-3.8-flash-tts"))
    with pytest.raises(TTSError, match="Model"):
        prov.synthesize(SynthesisRequest("Hi", "Kore", "gemini-9-tts"))


def test_gemini_daily_free_tier_limit_is_explained_and_not_retried():
    # Exact message returned by the API on 2026-10-30.
    body = json.dumps({"error": {"message": "Rate limit exceeded for model gemini-3.8-flash-tts (limit: 10 requests per day "
                                            "on Free Tier). Please retry in 1h15m50s or upgrade your tier at https://ai.dev/rate-limit.",
                                 "code": "too_many_requests"}})
    prov, _ = _gemini(lambda r: httpx.Response(429, text=body))
    with pytest.raises(TTSError) as e:
        prov.synthesize(SynthesisRequest("Hi", "Kore", "gemini-3.8-flash-tts"))
    assert e.value.code == "daily_limit" and not e.value.transient
    assert "10 requests/day" in e.value.message and "1 h 15 min" in e.value.message and "billing" in e.value.message


def test_gemini_per_minute_limit_is_retried():
    err = error_from_response(429, json.dumps({"error": {"message": "Rate limit exceeded: requests per minute"}}))
    assert err.code == "quota" and err.transient


@pytest.mark.parametrize("status,body,code,transient", [
    (400, "API key not valid. Please pass a valid API key. API_KEY_INVALID", "invalid_api_key", False),
    (503, "unavailable", "server", True),
    (404, "model not found", "unsupported_model", False),
    (400, "input token count exceeds the maximum", "request_too_large", False),
])
def test_gemini_error_mapping(status, body, code, transient):
    err = error_from_response(status, json.dumps({"error": {"message": body}}))
    assert err.code == code and err.transient == transient


def test_gemini_network_error_is_transient():
    def boom(r):
        raise httpx.ConnectError("down")
    prov, _ = _gemini(boom)
    with pytest.raises(TTSError) as e:
        prov.synthesize(SynthesisRequest("Hi", "Kore", "gemini-3.8-flash-tts"))
    assert e.value.code == "network" and e.value.transient


def test_whole_book_plan_and_generate(client):
    book = _import(client)
    prof = _fake_profile(client)
    plan = client.get(f"/api/books/{book['id']}/plan", params={"profile_id": prof["id"]}).json()
    assert plan["chapters"] == len(book["chapters"]) and plan["estimate"]["is_estimate"]
    assert client.app.state.ctx.providers.get("fake").calls == []  # planning is free
    last = book["chapters"][-1]["id"]
    r = client.post(f"/api/books/{book['id']}/generate", json={"profile_id": prof["id"], "from_chapter_id": last}).json()
    assert len(r["jobs"]) == len(book["chapters"])
    first_job = client.get(f"/api/jobs/{r['jobs'][0]}").json()
    assert first_job["chapter_id"] == last  # starts where the listener is
    w = Worker(client.app.state.ctx, sleep=lambda s: None)
    while w.run_once():
        pass
    b = client.get(f"/api/books/{book['id']}").json()
    assert b["chapters_ready"] == len(book["chapters"])
    assert client.get(f"/api/books/{book['id']}/plan").json()["chapters"] == 0


def test_simple_voice_choice(client):
    v = client.get("/api/settings/voice").json()
    assert v["engine"] == "local"
    assert v["engines"]["local"]["available"] and v["engines"]["local"]["voices"]
    assert v["engines"]["gemini"]["available"] is False  # no key in tests

    # Gemini without a key is refused with a readable reason
    r = client.put("/api/settings/voice", json={"engine": "gemini"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]

    voice = v["engines"]["local"]["voices"][-1]["id"]
    v2 = client.put("/api/settings/voice", json={"engine": "local", "voice": voice}).json()
    assert v2["engine"] == "local" and v2["voice"] == voice
    profiles = client.get("/api/profiles").json()
    assert sum(1 for p in profiles if p["is_default"]) == 1
    assert client.put("/api/settings/voice", json={"engine": "local", "voice": "nope"}).status_code == 400


def test_daily_limit_fails_fast_until_reset(client, ctx):
    from app.services import quota
    from app.services.generation import start_job

    book = _import(client)
    prof = _fake_profile(client)
    quota.record_block(ctx, "fake", prof["model"], "limit", "Please retry in 2h5m3s.")
    msg = quota.active_block(ctx, "fake", prof["model"])
    assert msg and "2 h" in msg
    r = client.post("/api/jobs", json={"chapter_id": book["chapters"][0]["id"], "profile_id": prof["id"]})
    assert r.status_code == 400 and "daily limit" in r.json()["detail"]
    quota.clear(ctx, "fake")
    assert quota.active_block(ctx, "fake", prof["model"]) is None
    assert start_job(ctx, book["chapters"][0]["id"], prof["id"])["status"] == "pending"


def test_newest_book_is_generated_first(client, ctx):
    from app.services.generation import Worker

    prof = _fake_profile(client)
    a, b = _import(client), _import(client)
    client.post(f"/api/books/{a['id']}/generate", json={"profile_id": prof["id"]})
    client.post(f"/api/books/{b['id']}/generate", json={"profile_id": prof["id"]})
    Worker(ctx, sleep=lambda s: None).run_once()
    first_done = ctx.db.one("SELECT book_id FROM jobs WHERE status='completed' ORDER BY finished_at LIMIT 1")
    assert first_done["book_id"] == b["id"]
