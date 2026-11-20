import wave
from pathlib import Path

import pytest

from app.audio import ffmpeg
from app.providers.base import TTSError
from app.services import export, generation, library
from app.services.generation import Worker

from .conftest import SAMPLE_TXT


def _book_and_chapter(ctx):
    book = library.import_manuscript(ctx, "novel.txt", SAMPLE_TXT.encode())
    ch = next(c for c in book["chapters"] if c["title"].startswith("Chapter One"))
    return book, ch


def _run(ctx):
    w = Worker(ctx, sleep=lambda s: None)
    while w.run_once():
        pass


def test_segments_map_to_chapter(ctx, fake_profile):
    _, ch = _book_and_chapter(ctx)
    prep = library.prepare_chapter(ctx, ch["id"], fake_profile)
    segs = ctx.db.query("SELECT * FROM segments WHERE chapter_id=? ORDER BY position", (ch["id"],))
    assert prep["total"] == len(segs) > 1
    assert [s["position"] for s in segs] == list(range(len(segs)))
    assert segs[0]["tts_text"].startswith("Chapter One: The Ascent.")  # title is announced
    assert "<long pause>" in "".join(s["tts_text"] for s in segs)  # scene break -> documented pause tag
    assert "* * *" in "".join(s["source_text"] for s in segs)     # manuscript untouched


def test_full_generation_assembles_chapter(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    job = generation.start_job(ctx, ch["id"], fake_profile)
    assert job["status"] == "pending"
    _run(ctx)
    job = generation.get_job(ctx, job["id"])
    assert job["status"] == "completed", job["error"]
    assert job["completed_segments"] == job["total_segments"]
    st = library.chapter_status(ctx, ctx.db.one("SELECT * FROM chapters WHERE id=?", (ch["id"],)))
    assert st["audio_ready"] and st["duration_s"] > 1
    assert all(c.style for c in fake.calls)  # style instruction sent
    assert all(c.voice == "Alpha" for c in fake.calls)


def test_transient_failure_is_retried(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    fake.fail_plan = [TTSError("boom", transient=True, code="server"),
                      TTSError("rate", transient=True, code="quota")]
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    j = ctx.db.one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")
    assert j["status"] == "completed"
    assert ctx.db.one("SELECT MAX(attempts) m FROM segments WHERE chapter_id=?", (ch["id"],))["m"] == 3


def test_failed_segment_keeps_others_and_retry_only_regenerates_failed(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    fake.fail_texts["engines hummed"] = TTSError("blocked", transient=False, code="blocked")
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    j = ctx.db.one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")
    assert j["status"] == "failed" and j["failed_segments"] == 1
    assert j["completed_segments"] == j["total_segments"] - 1
    with pytest.raises(export.IncompleteAudio):
        export.chapter_file(ctx, ch["id"])

    fake.fail_texts.clear()
    calls_before = len(fake.calls)
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    assert len(fake.calls) - calls_before == 1  # only the failed one
    assert ctx.db.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")["status"] == "completed"


def test_fatal_error_stops_job(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    fake.fail_plan = [TTSError("bad key", transient=False, code="invalid_api_key")]
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    j = ctx.db.one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")
    assert j["status"] == "failed" and "bad key" in j["error"]
    assert len(fake.calls) == 1  # did not hammer the API


def test_resume_after_interruption(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    generation.start_job(ctx, ch["id"], fake_profile)
    # Simulate a crash: first segment done, second was in flight.
    w = Worker(ctx, sleep=lambda s: None)
    segs = ctx.db.query("SELECT * FROM segments WHERE chapter_id=? ORDER BY position", (ch["id"],))
    profile = ctx.db.one("SELECT * FROM narration_profiles WHERE id=?", (fake_profile,))
    w._synthesize_segment(segs[0], profile, fake, 1)
    ctx.db.execute("UPDATE segments SET status='completed' WHERE id=?", (segs[0]["id"],))
    ctx.db.execute("UPDATE segments SET status='processing' WHERE id=?", (segs[1]["id"],))
    ctx.db.execute("UPDATE jobs SET status='processing'")
    fake.calls.clear()

    generation.recover_interrupted(ctx)
    assert ctx.db.one("SELECT status FROM segments WHERE id=?", (segs[1]["id"],))["status"] == "pending"
    _run(ctx)
    assert len(fake.calls) == len(segs) - 1  # first segment not regenerated
    assert ctx.db.one("SELECT status FROM jobs").get("status") == "completed"


def test_cache_reuse_and_change_detection(ctx, fake, fake_profile):
    book, ch = _book_and_chapter(ctx)
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    n = len(fake.calls)

    # Same inputs: zero API calls.
    prep = library.prepare_chapter(ctx, ch["id"], fake_profile)
    assert prep["reused"] == prep["total"]
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    assert len(fake.calls) == n

    # Unrelated setting (export format) does not invalidate.
    ctx.db.execute("UPDATE narration_profiles SET output_format='flac' WHERE id=?", (fake_profile,))
    assert library.prepare_chapter(ctx, ch["id"], fake_profile)["reused"] == prep["total"]

    # Pronunciation entry touching one segment invalidates only that segment.
    ctx.db.execute("INSERT INTO pronunciations (book_id, term, replacement) VALUES (?,?,?)",
                   (book["id"], "Theo", "THAY-oh"))
    p2 = library.prepare_chapter(ctx, ch["id"], fake_profile)
    assert 0 < p2["total"] - p2["reused"] < p2["total"]

    # Voice change invalidates everything.
    ctx.db.execute("UPDATE narration_profiles SET voice='Beta' WHERE id=?", (fake_profile,))
    assert library.prepare_chapter(ctx, ch["id"], fake_profile)["reused"] == 0


def test_regenerate_single_segment(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    ctx.db.execute("UPDATE books SET narration_profile_id=?", (fake_profile,))
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    n = len(fake.calls)
    seg = ctx.db.one("SELECT * FROM segments WHERE chapter_id=? AND position=1", (ch["id"],))
    generation.regenerate_segment(ctx, seg["id"])
    _run(ctx)
    assert len(fake.calls) == n + 1


def test_cancel_preserves_completed(ctx, fake, fake_profile):
    _, ch = _book_and_chapter(ctx)
    job = generation.start_job(ctx, ch["id"], fake_profile)
    orig = fake.synthesize

    def synth_then_cancel(req):
        r = orig(req)
        ctx.db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job["id"],))
        return r

    fake.synthesize = synth_then_cancel
    _run(ctx)
    j = generation.get_job(ctx, job["id"])
    assert j["status"] == "cancelled"
    assert ctx.db.one("SELECT COUNT(*) n FROM segments WHERE chapter_id=? AND status='completed'",
                      (ch["id"],))["n"] == 1


def test_concat_compatible_segments(tmp_path):
    from app.providers.demo import tone_wav

    paths = []
    for i, sec in enumerate((1.0, 2.0)):
        p = tmp_path / f"{i}.wav"
        p.write_bytes(tone_wav(sec))
        paths.append(p)
    out = tmp_path / "out.wav"
    ffmpeg.concat_segments(paths, out, gap_ms=500, trim=False)
    with wave.open(str(out)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1
        assert abs(w.getnframes() / 24000 - 3.5) < 0.05


def test_incompatible_audio_is_converted(tmp_path):
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100); w.writeframes(b"\x10\x10" * 2 * 44100)
    out = ffmpeg.to_standard_wav(buf.getvalue(), "audio/wav")
    info = ffmpeg.inspect_wav(out)
    assert (info.sample_rate, info.channels) == (24000, 1)


def test_validation_rejects_silent_audio():
    from app.providers.demo import tone_wav
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\x00\x00" * 48000)
    with pytest.raises(ffmpeg.AudioError, match="silent"):
        ffmpeg.validate_speech_wav(buf.getvalue(), 20)
    ffmpeg.validate_speech_wav(tone_wav(2), 20)



def test_parallel_generation_completes_in_order(ctx, fake, fake_profile):
    import threading, time
    ctx.settings.tts_concurrency = 3
    active, peak, lock = [0], [0], threading.Lock()
    orig = fake.synthesize

    def slow(req):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        try:
            return orig(req)
        finally:
            with lock:
                active[0] -= 1

    fake.synthesize = slow
    _, ch = _book_and_chapter(ctx)
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    assert ctx.db.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")["status"] == "completed"
    assert peak[0] > 1  # really ran in parallel
    first3 = {r["tts_text"] for r in ctx.db.query(
        "SELECT tts_text FROM segments WHERE chapter_id=? ORDER BY position LIMIT 3", (ch["id"],))}
    assert {c.text for c in fake.calls[:3]} == first3  # earliest segments are generated first


def test_parallel_fatal_error_stops_job(ctx, fake, fake_profile):
    ctx.settings.tts_concurrency = 3
    _, ch = _book_and_chapter(ctx)
    fake.fail_texts[""] = TTSError("bad key", transient=False, code="invalid_api_key")
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    j = ctx.db.one("SELECT * FROM jobs ORDER BY id DESC LIMIT 1")
    assert j["status"] == "failed" and "bad key" in j["error"]
    assert len(fake.calls) <= 3
    assert not ctx.db.one("SELECT id FROM segments WHERE status='processing'")


def test_first_segment_is_short_for_fast_start(ctx, fake_profile):
    _, ch = _book_and_chapter(ctx)
    library.prepare_chapter(ctx, ch["id"], fake_profile)
    segs = ctx.db.query("SELECT source_text FROM segments WHERE chapter_id=? ORDER BY position", (ch["id"],))
    assert len(segs[0]["source_text"]) <= 120 + 80  # one sentence over is allowed
    assert "\n\n".join(s["source_text"] for s in segs).replace("\n\n", " ").split() == \
        ctx.db.one("SELECT text FROM chapters WHERE id=?", (ch["id"],))["text"].replace("\n\n", " ").split()


def test_stuck_request_is_abandoned_and_retried(ctx, fake, fake_profile):
    import time
    ctx.settings.tts_request_timeout_s = -29.8  # deadline = 0.2 s
    orig, calls = fake.synthesize, []

    def first_hangs(req):
        calls.append(1)
        if len(calls) == 1:
            time.sleep(2)
        return orig(req)

    fake.synthesize = first_hangs
    _, ch = _book_and_chapter(ctx)
    generation.start_job(ctx, ch["id"], fake_profile)
    _run(ctx)
    assert ctx.db.one("SELECT status FROM jobs ORDER BY id DESC LIMIT 1")["status"] == "completed"
    assert ctx.db.one("SELECT MAX(attempts) m FROM segments")["m"] == 2
