"""FFmpeg helpers: validation, conversion, assembly, loudness normalisation, encoding."""
from __future__ import annotations

import array
import io
import json
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 24000  # Gemini TTS native rate; everything is kept at this rate
CHANNELS = 1


class AudioError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    if not ffmpeg_available():
        raise AudioError("FFmpeg is not installed. Install it with: brew install ffmpeg")
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise AudioError(f"{Path(args[0]).name} failed: {r.stderr.strip()[-600:]}")
    return r


@dataclass
class WavInfo:
    sample_rate: int
    channels: int
    sample_width: int
    frames: int
    peak: int

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0


def inspect_wav(data: bytes) -> WavInfo:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames = w.readframes(w.getnframes())
            info = WavInfo(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes(), 0)
    except (wave.Error, EOFError) as e:
        raise AudioError(f"Invalid WAV data: {e}") from e
    if info.sample_width == 2 and frames:
        samples = array.array("h", frames[: len(frames) - len(frames) % 2])
        info.peak = max(abs(min(samples)), abs(max(samples)))
    return info


def validate_speech_wav(data: bytes, text_chars: int) -> WavInfo:
    """Reject empty, truncated or silent audio before it is saved as 'completed'."""
    info = inspect_wav(data)
    if info.frames == 0 or info.duration_s < 0.3:
        raise AudioError("Audio is empty or too short.")
    if info.sample_width == 2 and info.peak < 200:
        raise AudioError("Audio is silent.")
    # Narration is ~12-18 chars/sec. Far too short audio usually means a truncated response.
    if text_chars > 400 and info.duration_s < text_chars / 60:
        raise AudioError(f"Audio is suspiciously short ({info.duration_s:.1f}s for {text_chars} characters).")
    return info


def to_standard_wav(data: bytes, mime_type: str) -> bytes:
    """Return 24 kHz mono 16-bit WAV. Pass through when already compliant (no re-encode)."""
    if mime_type in ("audio/wav", "audio/x-wav", "audio/wave"):
        try:
            info = inspect_wav(data)
            if (info.sample_rate, info.channels, info.sample_width) == (SAMPLE_RATE, CHANNELS, 2):
                return data
        except AudioError:
            pass
    if mime_type.startswith("audio/l16") or mime_type == "audio/pcm":
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(data)
        return buf.getvalue()
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d, "in.bin"), Path(d, "out.wav")
        src.write_bytes(data)
        _run(["ffmpeg", "-nostdin", "-y", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
              "-sample_fmt", "s16", str(dst)])
        return dst.read_bytes()


def probe_duration(path: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(r.stdout)["format"]["duration"])


def _silence_wav(path: Path, ms: int) -> None:
    n = int(SAMPLE_RATE * ms / 1000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(b"\x00\x00" * n)


TRIM = ("silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.08,"
        "areverse,silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.12,areverse")


def concat_segments(paths: list[Path], out_wav: Path, gap_ms: int = 450, trim: bool = True) -> None:
    """Concatenate segment WAVs (converted to a common format) with a consistent gap.

    Each segment's leading/trailing silence is trimmed to a short, fixed amount so the
    gap between segments is uniform — natural pauses inside the speech are untouched.
    """
    if not paths:
        raise AudioError("No segments to assemble.")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        listing, silence = [], d / "gap.wav"
        _silence_wav(silence, gap_ms)
        for i, p in enumerate(paths):
            norm = d / f"s{i:05d}.wav"
            args = ["ffmpeg", "-nostdin", "-y", "-i", str(p)]
            if trim:
                args += ["-af", TRIM]
            _run(args + ["-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(norm)])
            if i:
                listing.append(silence)
            listing.append(norm)
        lst = d / "list.txt"
        lst.write_text("".join(f"file '{x.as_posix()}'\n" for x in listing))
        _run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
              "-c", "copy", str(out_wav)])


def loudnorm_to_flac(src_wav: Path, out_flac: Path, target_lufs: float = -18.0,
                     metadata: dict[str, str] | None = None) -> None:
    """Two-pass EBU R128 normalisation (linear mode, no dynamic squashing) to FLAC."""
    flt = f"loudnorm=I={target_lufs}:TP=-2:LRA=11"
    r = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src_wav), "-af",
              flt + ":print_format=json", "-f", "null", "-"])
    try:
        js = r.stderr[r.stderr.rindex("{"): r.stderr.rindex("}") + 1]
        m = json.loads(js)
        flt = (f"{flt}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
               f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
               f"offset={m['target_offset']}:linear=true")
    except (ValueError, KeyError):
        pass  # fall back to single-pass
    args = ["ffmpeg", "-nostdin", "-y", "-i", str(src_wav), "-af", flt, "-ar", str(SAMPLE_RATE),
            "-ac", "1", "-sample_fmt", "s16"]
    for k, v in (metadata or {}).items():
        args += ["-metadata", f"{k}={v}"]
    _run(args + ["-c:a", "flac", str(out_flac)])


def encode_mp3(src: Path, out_mp3: Path, bitrate: str = "128k", metadata: dict[str, str] | None = None) -> None:
    args = ["ffmpeg", "-nostdin", "-y", "-i", str(src), "-c:a", "libmp3lame", "-b:a", bitrate,
            "-id3v2_version", "3"]
    for k, v in (metadata or {}).items():
        args += ["-metadata", f"{k}={v}"]
    _run(args + [str(out_mp3)])
