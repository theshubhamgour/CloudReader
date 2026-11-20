"""Generation jobs: a single background worker that is resumable and cancellable.

State lives entirely in SQLite, so a crash or restart loses at most the segment that
was in flight. Completed segment audio is saved the moment it arrives.
"""
from __future__ import annotations

import logging
import random
import shutil
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from ..audio import ffmpeg
from ..providers.base import SynthesisRequest, TTSError
from .library import ConflictError, get_book, prepare_chapter, safe_filename, segments_fingerprint
from .profiles import get_profile
from .quota import active_block, record_block

log = logging.getLogger("cloudreader.worker")

MIN_FREE_BYTES = 500 * 1024 * 1024
# Errors that will fail every following segment too: stop the job instead of burning retries.
JOB_FATAL = {"missing_api_key", "invalid_api_key", "permission", "unsupported_model", "invalid_voice", "daily_limit"}


class JobCancelled(Exception):
    pass


def call_with_deadline(fn, seconds: float):
    """Run fn in a helper thread; give up after `seconds` so one stuck request can't stall a job.

    An abandoned call may still finish in the background; its result is ignored.
    """
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # re-raised in the caller's thread
            box["error"] = e

    t = threading.Thread(target=run, daemon=True, name="tts-call")
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TTSError(f"The voice service didn't answer within {int(seconds)} seconds.", transient=True, code="timeout")
    if "error" in box:
        raise box["error"]
    return box["value"]


def recover_interrupted(ctx) -> None:
    """Called at startup: anything that was mid-flight goes back to pending."""
    with ctx.db.tx() as c:
        c.execute("UPDATE segments SET status='pending' WHERE status='processing'")
        c.execute("UPDATE jobs SET status='pending' WHERE status='processing'")


def start_job(ctx, chapter_id: int, profile_id: int | None = None, retry_failed: bool = True) -> dict:
    ch = ctx.db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        raise KeyError("Chapter not found")
    if not ffmpeg.ffmpeg_available():
        raise RuntimeError("FFmpeg is not installed. Install it with: brew install ffmpeg")
    free = shutil.disk_usage(ctx.settings.data_dir).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"Not enough disk space ({free // 2**20} MB free; need at least 500 MB).")
    book = ctx.db.one("SELECT * FROM books WHERE id=?", (ch["book_id"],))
    profile = get_profile(ctx, profile_id or book["narration_profile_id"])
    provider = ctx.providers.get(profile["provider"])
    ok, why = provider.available()
    if not ok:
        raise PermissionError(why)
    if blocked := active_block(ctx, profile["provider"], profile["model"]):
        raise PermissionError(blocked)
    prep = prepare_chapter(ctx, chapter_id, profile["id"])
    with ctx.db.tx() as c:
        if retry_failed:
            c.execute("UPDATE segments SET status='pending', error=NULL WHERE chapter_id=? AND status IN ('failed','cancelled')",
                      (chapter_id,))
        job_id = c.execute(
            "INSERT INTO jobs (book_id, chapter_id, profile_id, status, total_segments, completed_segments, "
            "reused_segments) VALUES (?,?,?,?,?,?,?)",
            (ch["book_id"], chapter_id, profile["id"], "pending", prep["total"], prep["reused"], prep["reused"]),
        ).lastrowid
    if ctx.worker:
        ctx.worker.wake()
    return get_job(ctx, job_id)


def get_job(ctx, job_id: int) -> dict:
    j = ctx.db.one(
        "SELECT j.*, c.title chapter_title, b.title book_title, p.name profile_name, p.provider provider "
        "FROM jobs j JOIN chapters c ON c.id=j.chapter_id JOIN books b ON b.id=j.book_id "
        "LEFT JOIN narration_profiles p ON p.id=j.profile_id WHERE j.id=?", (job_id,))
    if not j:
        raise KeyError("Job not found")
    j["cancel_requested"] = bool(j["cancel_requested"])
    return j


def cancel_job(ctx, job_id: int) -> dict:
    j = get_job(ctx, job_id)
    if j["status"] in ("pending",):
        with ctx.db.tx() as c:
            c.execute("UPDATE jobs SET status='cancelled', finished_at=datetime('now') WHERE id=?", (job_id,))
    elif j["status"] == "processing":
        ctx.db.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
    return get_job(ctx, job_id)


def regenerate_segment(ctx, segment_id: int) -> dict:
    seg = ctx.db.one("SELECT * FROM segments WHERE id=?", (segment_id,))
    if not seg:
        raise KeyError("Segment not found")
    if ctx.db.one("SELECT id FROM jobs WHERE chapter_id=? AND status IN ('pending','processing')", (seg["chapter_id"],)):
        raise ConflictError("Wait for the current job on this chapter to finish.")
    # A new variant gives a fresh take without touching the cached original.
    ctx.db.execute("UPDATE segments SET variant=variant+1 WHERE id=?", (segment_id,))
    return start_job(ctx, seg["chapter_id"], None)


def book_plan(ctx, book_id: int, profile_id: int | None = None) -> dict:
    """What generating the rest of the book would involve. Pure: no DB writes, no API calls."""
    from .costs import estimate
    from .library import chapter_status, plan_segments

    book = ctx.db.one("SELECT * FROM books WHERE id=?", (book_id,))
    if not book:
        raise KeyError("Book not found")
    profile = get_profile(ctx, profile_id or book["narration_profile_id"])
    provider = ctx.providers.get(profile["provider"])
    todo, words, chars, total_segs, cached = [], 0, 0, 0, 0
    for ch in ctx.db.query("SELECT * FROM chapters WHERE book_id=? ORDER BY position", (book_id,)):
        if chapter_status(ctx, ch)["audio_ready"]:
            continue
        planned = plan_segments(ctx, ch, profile)
        keys = [p["cache_key"] for p in planned]
        q = ",".join("?" * len(keys))
        have = {r["cache_key"] for r in ctx.db.query(f"SELECT cache_key FROM audio_assets WHERE cache_key IN ({q})", tuple(keys))} if keys else set()
        new_chars = sum(len(p["tts_text"]) for p in planned if p["cache_key"] not in have)
        frac = new_chars / max(1, sum(len(p["tts_text"]) for p in planned))
        todo.append(ch["id"])
        words += int(ch["word_count"] * frac)
        chars += new_chars
        total_segs += len(planned)
        cached += len(have)
    return {"profile_id": profile["id"], "profile_name": profile["name"], "chapters": len(todo), "chapter_ids": todo,
            "segments": total_segs, "reused_segments": cached,
            "estimate": estimate(provider, profile["model"], words, chars),
            "large_job": words > ctx.settings.large_job_word_threshold}


def start_book(ctx, book_id: int, profile_id: int | None = None, from_chapter_id: int | None = None) -> dict:
    """Queue every unfinished chapter, starting with `from_chapter_id` so listening can begin there."""
    plan = book_plan(ctx, book_id, profile_id)
    ids = plan["chapter_ids"]
    if from_chapter_id in ids:
        i = ids.index(from_chapter_id)
        ids = ids[i:] + ids[:i]
    started, skipped = [], 0
    for cid in ids:
        try:
            started.append(start_job(ctx, cid, plan["profile_id"])["id"])
        except ConflictError:
            skipped += 1  # already generating
    return {"jobs": started, "already_running": skipped, "chapters": len(ids)}


# ---------------------------------------------------------------- worker

class Worker:
    def __init__(self, ctx, sleep=time.sleep):
        self.ctx = ctx
        self._sleep = sleep
        self._event = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="cloudreader-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def wake(self):
        self._event.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                log.exception("Worker iteration crashed")
                worked = False
            if not worked:
                self._event.wait(timeout=5)
                self._event.clear()

    # Public for tests: process the next job fully. Returns False if idle.
    def run_once(self) -> bool:
        db = self.ctx.db
        # The book you most recently pressed Play on goes first; its chapters stay in reading order.
        job = db.one(
            "SELECT j.* FROM jobs j WHERE j.status IN ('processing','pending') ORDER BY "
            "(SELECT MAX(k.id) FROM jobs k WHERE k.book_id=j.book_id AND k.status IN ('processing','pending')) DESC, "
            "j.status='processing' DESC, j.id LIMIT 1")
        if not job:
            return False
        prof = get_profile(self.ctx, job["profile_id"])
        if blocked := active_block(self.ctx, prof["provider"], prof["model"]):
            self._finish(job["id"], "failed", blocked)
            return True
        db.execute("UPDATE jobs SET status='processing', started_at=COALESCE(started_at, datetime('now')), "
                   "error=NULL WHERE id=?", (job["id"],))
        try:
            self._process(job)
        except JobCancelled:
            with db.tx() as c:
                c.execute("UPDATE jobs SET status='cancelled', finished_at=datetime('now') WHERE id=?", (job["id"],))
                c.execute("UPDATE segments SET status='pending' WHERE chapter_id=? AND status='processing'",
                          (job["chapter_id"],))
        except TTSError as e:
            log.warning("Job %s stopped: %s (%s)", job["id"], e.code, e.detail[:200])
            if e.code == "daily_limit":
                record_block(self.ctx, prof["provider"], prof["model"], e.message, e.detail)
            self._finish(job["id"], "failed", e.message)
        except Exception as e:
            log.exception("Job %s failed", job["id"])
            self._finish(job["id"], "failed", f"{type(e).__name__}: {e}")
        return True

    def _finish(self, job_id: int, status: str, error: str | None = None):
        self._update_counts(job_id)
        self.ctx.db.execute("UPDATE jobs SET status=?, error=?, finished_at=datetime('now') WHERE id=?",
                            (status, error, job_id))

    def _update_counts(self, job_id: int):
        j = self.ctx.db.one("SELECT chapter_id FROM jobs WHERE id=?", (job_id,))
        rows = self.ctx.db.query("SELECT status, COUNT(*) n FROM segments WHERE chapter_id=? GROUP BY status",
                                 (j["chapter_id"],))
        counts = {r["status"]: r["n"] for r in rows}
        self.ctx.db.execute("UPDATE jobs SET total_segments=?, completed_segments=?, failed_segments=? WHERE id=?",
                            (sum(counts.values()), counts.get("completed", 0), counts.get("failed", 0), job_id))

    def _check_cancel(self, job_id: int):
        if self.ctx.db.one("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,))["cancel_requested"]:
            raise JobCancelled()

    def _process(self, job: dict):
        """Synthesise pending segments in reading order, `tts_concurrency` at a time.

        Earlier segments are always submitted first, so listening can begin while later
        ones are still being generated.
        """
        db = self.ctx.db
        profile = get_profile(self.ctx, job["profile_id"])
        provider = self.ctx.providers.get(profile["provider"])
        workers = max(1, self.ctx.settings.tts_concurrency)
        fatal: list[BaseException] = []
        stop = threading.Event()

        def run_one(seg: dict):
            try:
                if stop.is_set():
                    db.execute("UPDATE segments SET status='pending' WHERE id=?", (seg["id"],))
                    return
                self._synthesize_segment(seg, profile, provider, job["id"])
                db.execute("UPDATE segments SET status='completed', error=NULL, updated_at=datetime('now') WHERE id=?",
                           (seg["id"],))
            except JobCancelled as e:
                db.execute("UPDATE segments SET status='pending' WHERE id=?", (seg["id"],))
                fatal.append(e)
                stop.set()
            except TTSError as e:
                db.execute("UPDATE segments SET status='failed', error=?, updated_at=datetime('now') WHERE id=?",
                           (e.message, seg["id"]))
                if e.code in JOB_FATAL or e.code == "quota":
                    fatal.append(e)
                    stop.set()
            except Exception as e:  # unexpected: keep the error visible, never mark completed
                db.execute("UPDATE segments SET status='failed', error=? WHERE id=?", (f"{type(e).__name__}: {e}", seg["id"]))
                log.exception("Segment %s crashed", seg["id"])
            finally:
                self._update_counts(job["id"])

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts") as pool:
            in_flight: set = set()
            while not stop.is_set():
                try:
                    self._check_cancel(job["id"])
                except JobCancelled as e:
                    fatal.append(e)
                    stop.set()
                    break
                while len(in_flight) < workers:
                    seg = db.one("SELECT * FROM segments WHERE chapter_id=? AND status='pending' ORDER BY position LIMIT 1",
                                 (job["chapter_id"],))
                    if not seg:
                        break
                    asset = db.one("SELECT path FROM audio_assets WHERE cache_key=?", (seg["cache_key"],))
                    if asset and Path(asset["path"]).exists():
                        db.execute("UPDATE segments SET status='completed', error=NULL WHERE id=?", (seg["id"],))
                        db.execute("UPDATE jobs SET reused_segments=reused_segments+1 WHERE id=?", (job["id"],))
                        self._update_counts(job["id"])
                        continue
                    db.execute("UPDATE segments SET status='processing', updated_at=datetime('now') WHERE id=?", (seg["id"],))
                    in_flight.add(pool.submit(run_one, seg))
                if not in_flight:
                    break
                done, in_flight = wait(in_flight, timeout=0.5, return_when=FIRST_COMPLETED)
                in_flight = set(in_flight)
            for f in in_flight:  # let requests already sent finish and be saved (they are paid for)
                f.result()
        if fatal:
            raise fatal[0]

        self._update_counts(job["id"])
        j = db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))
        if j["failed_segments"]:
            self._finish(job["id"], "failed",
                         f"{j['failed_segments']} segment(s) failed. Completed segments were kept; "
                         "use Retry to regenerate only the failed ones.")
            return
        assemble_chapter(self.ctx, job["chapter_id"])
        self._finish(job["id"], "completed")

    def _synthesize_segment(self, seg: dict, profile: dict, provider, job_id: int):
        s, db = self.ctx.settings, self.ctx.db
        req = SynthesisRequest(text=seg["tts_text"], voice=profile["voice"], model=profile["model"],
                               style=seg["style_instruction"], language=profile.get("language"))
        attempt = 0
        while True:
            attempt += 1
            db.execute("UPDATE segments SET attempts=attempts+1 WHERE id=?", (seg["id"],))
            try:
                result = call_with_deadline(lambda: provider.synthesize(req), s.tts_request_timeout_s + 30)
                wav = ffmpeg.to_standard_wav(result.audio, result.mime_type)
                info = ffmpeg.validate_speech_wav(wav, len(seg["tts_text"]))
                break
            except ffmpeg.AudioError as e:
                err = TTSError(f"Invalid audio from provider: {e}", transient=True, code="bad_audio")
            except TTSError as e:
                err = e
            if not err.transient or attempt > s.max_retries:
                raise err
            delay = min(s.retry_max_delay_s, s.retry_base_delay_s * 2 ** (attempt - 1)) * (0.8 + random.random() * 0.4)
            if err.code == "quota":
                delay = max(delay, 10.0)
            log.info("Segment %s attempt %d failed (%s); retrying in %.1fs", seg["id"], attempt, err.code, delay)
            db.execute("UPDATE segments SET error=? WHERE id=?", (f"Retrying: {err.message}", seg["id"]))
            # Sleep in small steps so cancellation stays responsive.
            end = time.monotonic() + delay
            while time.monotonic() < end:
                self._check_cancel(job_id)
                self._sleep(min(0.5, max(0.0, end - time.monotonic())))

        path = s.audio_dir / "segments" / seg["cache_key"][:2] / f"{seg['cache_key']}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(wav)
        tmp.replace(path)  # atomic: a crash never leaves a half-written "completed" file
        with db.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO audio_assets (cache_key, path, provider, model, voice, is_demo, duration_s, "
                "sample_rate, channels, input_tokens, output_tokens) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (seg["cache_key"], str(path), profile["provider"], profile["model"], profile["voice"],
                 int(result.is_demo or provider.is_demo), info.duration_s, info.sample_rate, info.channels,
                 result.input_tokens, result.output_tokens))
            c.execute("INSERT INTO usage_log (provider, model, kind, characters, input_tokens, output_tokens, "
                      "audio_seconds) VALUES (?,?,?,?,?,?,?)",
                      (profile["provider"], profile["model"], "segment", len(seg["tts_text"]),
                       result.input_tokens, result.output_tokens, info.duration_s))


# ---------------------------------------------------------------- assembly

def assemble_chapter(ctx, chapter_id: int) -> dict:
    s, db = ctx.settings, ctx.db
    ch = db.one("SELECT * FROM chapters WHERE id=?", (chapter_id,))
    segs = db.query("SELECT s.status, a.path, a.is_demo, a.voice, a.provider FROM segments s "
                    "LEFT JOIN audio_assets a ON a.cache_key=s.cache_key WHERE s.chapter_id=? ORDER BY s.position",
                    (chapter_id,))
    if not segs or any(r["status"] != "completed" or not r["path"] or not Path(r["path"]).exists() for r in segs):
        raise RuntimeError("Cannot assemble: not every segment has completed audio.")
    fp = segments_fingerprint(ctx, chapter_id)
    existing = db.one("SELECT * FROM chapter_audio WHERE chapter_id=?", (chapter_id,))
    if existing and existing["fingerprint"] == fp and Path(existing["mp3_path"]).exists():
        return existing

    book = db.one("SELECT * FROM books WHERE id=?", (ch["book_id"],))
    is_demo = any(r["is_demo"] for r in segs)
    narrator = f"{segs[0]['voice']} ({'demo' if is_demo else segs[0]['provider']})"
    out_dir = s.audio_dir / "chapters" / str(book["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{chapter_id}-{fp[:12]}"
    master, mp3 = out_dir / f"{stem}.flac", out_dir / f"{stem}.mp3"
    meta = {"title": ch["title"], "album": book["title"], "artist": book["author"] or "Unknown",
            "track": str(ch["position"] + 1), "genre": "Audiobook",
            "comment": "DEMO AUDIO - macOS system voice, not AI narration" if is_demo
                       else f"Narrated with {narrator} via CloudReader"}
    tmp_wav = s.tmp_dir / f"{stem}.wav"
    try:
        ffmpeg.concat_segments([Path(r["path"]) for r in segs], tmp_wav, s.inter_segment_silence_ms)
        ffmpeg.loudnorm_to_flac(tmp_wav, master, s.loudness_target_lufs, meta)
        ffmpeg.encode_mp3(master, mp3, s.mp3_bitrate, meta)
    finally:
        tmp_wav.unlink(missing_ok=True)
    duration = ffmpeg.probe_duration(master)
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO chapter_audio (chapter_id, fingerprint, master_path, mp3_path, duration_s, "
                  "is_demo, narrator) VALUES (?,?,?,?,?,?,?)",
                  (chapter_id, fp, str(master), str(mp3), duration, int(is_demo), narrator))
    if existing:
        for p in (existing["master_path"], existing["mp3_path"]):
            if p not in (str(master), str(mp3)):
                Path(p).unlink(missing_ok=True)
    return db.one("SELECT * FROM chapter_audio WHERE chapter_id=?", (chapter_id,))


def chapter_export_name(position: int, title: str, ext: str, is_demo: bool = False) -> str:
    return f"{'DEMO_' if is_demo else ''}{position + 1:02d}_{safe_filename(title)}.{ext}"


__all__ = ["start_job", "cancel_job", "get_job", "regenerate_segment", "Worker", "assemble_chapter",
           "recover_interrupted", "chapter_export_name", "get_book"]
