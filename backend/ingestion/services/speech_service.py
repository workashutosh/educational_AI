"""
Speech-to-text via an OpenAI-compatible Whisper endpoint (Groq by default).

Used for voice questions in chat and for turning lecture recordings into
indexed notes. Long recordings are split with ffmpeg when it is installed;
without ffmpeg, files must fit the provider's upload limit (25 MB on Groq's
free tier — roughly 25-50 min of compressed speech).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import requests
from django.conf import settings

from .language_service import normalize_language

logger = logging.getLogger(__name__)

_GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".oga", ".flac", ".mp4", ".mpeg", ".mpga", ".aac"}
SEGMENT_SECONDS = 20 * 60


class TranscriptionError(RuntimeError):
    """User-safe transcription failure."""


@dataclass
class Transcript:
    text: str
    duration_seconds: float = 0.0
    language: str = ""
    segments: list[dict] = field(default_factory=list)


def _config() -> tuple[str, str, str]:
    url = getattr(settings, "TRANSCRIPTION_API_URL", "") or _GROQ_URL
    key = getattr(settings, "TRANSCRIPTION_API_KEY", "") or getattr(settings, "GROQ_API_KEY", "")
    model = getattr(settings, "TRANSCRIPTION_MODEL", "") or "whisper-large-v3-turbo"
    return url, key, model


def is_configured() -> bool:
    return bool(_config()[1])


def max_upload_bytes() -> int:
    return int(getattr(settings, "TRANSCRIPTION_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))


def _post(path: Path, *, language: str | None, prompt: str | None) -> dict:
    url, key, model = _config()
    if not key:
        raise TranscriptionError("Voice transcription is not set up yet.")
    data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    lang = normalize_language(language) if language else ""
    if lang:
        data["language"] = lang
    if prompt:
        data["prompt"] = prompt[:800]
    try:
        with path.open("rb") as fh:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                data=data,
                files={"file": (path.name, fh)},
                timeout=600,
            )
    except requests.RequestException as exc:
        logger.warning("transcription request failed: %s", exc)
        raise TranscriptionError("The transcription service is unreachable. Try again.") from exc
    if resp.status_code == 413:
        raise TranscriptionError("Recording is too large to transcribe in one piece.")
    if resp.status_code == 429:
        raise TranscriptionError("The transcription service is busy. Try again in a minute.")
    if resp.status_code != 200:
        logger.warning("transcription error %s: %s", resp.status_code, resp.text[:500])
        raise TranscriptionError("Could not transcribe this audio.")
    return resp.json()


def _split_with_ffmpeg(path: Path, out_dir: Path) -> list[Path]:
    """Re-encode to 32 kbps mono MP3 in 20-minute pieces (small + Whisper-friendly)."""
    pattern = out_dir / "part%03d.mp3"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
        "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
        "-f", "segment", "-segment_time", str(SEGMENT_SECONDS), str(pattern),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=1800, capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg split failed: %s", exc)
        raise TranscriptionError("Could not read this audio file.") from exc
    return sorted(out_dir.glob("part*.mp3"))


def transcribe_file(path: str | Path, *, language: str | None = None, prompt: str | None = None) -> Transcript:
    path = Path(path)
    if path.suffix.lower() not in AUDIO_EXTS:
        raise TranscriptionError("Unsupported audio format. Use MP3, M4A, WAV, WEBM, OGG, or MP4.")

    with tempfile.TemporaryDirectory(prefix="transcribe_") as tmp:
        if shutil.which("ffmpeg"):
            parts = _split_with_ffmpeg(path, Path(tmp))
        elif path.stat().st_size <= max_upload_bytes():
            parts = [path]
        else:
            raise TranscriptionError(
                "Recording is too large. Upload a file under "
                f"{max_upload_bytes() // (1024 * 1024)} MB, or ask your admin to install ffmpeg."
            )

        texts: list[str] = []
        segments: list[dict] = []
        offset = 0.0
        detected = ""
        for part in parts:
            data = _post(part, language=language, prompt=prompt)
            texts.append((data.get("text") or "").strip())
            detected = detected or (data.get("language") or "")
            for seg in data.get("segments") or []:
                segments.append(
                    {
                        "start": round(offset + float(seg.get("start") or 0), 2),
                        "end": round(offset + float(seg.get("end") or 0), 2),
                        "text": (seg.get("text") or "").strip(),
                    }
                )
            offset += float(data.get("duration") or 0)

    transcript = Transcript(
        text="\n\n".join(t for t in texts if t),
        duration_seconds=round(offset, 1),
        language=detected,
        segments=segments,
    )
    try:
        from billing.services.usage import record_units

        record_units(kind="transcription", units=transcript.duration_seconds, provider="whisper", model=_config()[2])
    except Exception:
        logger.debug("transcription metering skipped", exc_info=True)
    return transcript
