"""Lecture recording pipeline: transcribe → index as notes → summarize → notify."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from celery import shared_task
from django.core.files.base import ContentFile
from django.utils import timezone

from ingestion.models import Document
from ingestion.services import sha256_of_uploaded_file
from ingestion.services.llm_json import LLMJSONError, llm_json
from ingestion.services.speech_service import TranscriptionError, transcribe_file

from .models import LectureRecording

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "You summarize a classroom lecture transcript for students.\n"
    'Return JSON only: {"summary":"markdown summary, 150-300 words, with headings",'
    '"key_points":["5-10 short takeaways"]}\n'
    "Use only what the teacher said. Write maths in LaTeX with $...$."
)
_SUMMARY_INPUT_CHARS = 24000


def _fmt_time(seconds: float) -> str:
    seconds = int(seconds or 0)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def transcript_markdown(rec: LectureRecording) -> str:
    lec = rec.lecture
    when = timezone.localtime(lec.starts_at).strftime("%d %b %Y")
    lines = [f"# Lecture: {lec.title} ({when})", ""]
    if rec.summary:
        lines += ["## Summary", "", rec.summary, ""]
    if rec.key_points:
        lines += ["## Key points", ""] + [f"- {p}" for p in rec.key_points] + [""]
    lines += ["## Transcript", ""]
    if rec.segments:
        # Group segments into ~2 minute paragraphs with timestamps.
        para, start = [], None
        for seg in rec.segments:
            start = seg["start"] if start is None else start
            para.append(seg["text"])
            if seg["end"] - start >= 120:
                lines += [f"**[{_fmt_time(start)}]** " + " ".join(para), ""]
                para, start = [], None
        if para:
            lines += [f"**[{_fmt_time(start or 0)}]** " + " ".join(para), ""]
    else:
        lines.append(rec.transcript)
    return "\n".join(lines)


def _summarize(rec: LectureRecording) -> None:
    text = rec.transcript
    if len(text) > _SUMMARY_INPUT_CHARS:
        # Head + tail keeps the intro and the wrap-up the teacher gave.
        half = _SUMMARY_INPUT_CHARS // 2
        text = text[:half] + "\n…\n" + text[-half:]
    try:
        data = llm_json(
            _SUMMARY_SYSTEM,
            f"Lecture title: {rec.lecture.title}\n\nTranscript:\n{text}",
            max_tokens=2000,
        )
    except LLMJSONError:
        logger.warning("lecture summary unreadable rec=%s", rec.id)
        return
    rec.summary = str(data.get("summary") or "").strip()[:8000]
    rec.key_points = [str(p).strip()[:300] for p in (data.get("key_points") or []) if str(p).strip()][:12]


def _index_transcript(rec: LectureRecording) -> Document:
    from ingestion.tasks import process_document_sync

    body = transcript_markdown(rec).encode("utf-8")
    upload = ContentFile(body, name=f"lecture-{rec.lecture_id}-recording-{rec.id}.md")
    document = Document.objects.create(
        bucket=rec.lecture.bucket,
        uploaded_by=rec.uploaded_by,
        file=upload,
        original_filename=f"Lecture – {rec.lecture.title}.md"[:500],
        file_hash=sha256_of_uploaded_file(upload),
        byte_size=len(body),
        content_type="text/markdown",
        kind=Document.KIND_NOTES,
    )
    process_document_sync(document.id)
    return document


def process_recording(recording_id: int) -> dict:
    from billing.services.usage import usage_scope

    rec = LectureRecording.objects.select_related("lecture__bucket").get(pk=recording_id)

    def set_status(value: str) -> None:
        rec.status = value
        rec.save(update_fields=["status"])

    with usage_scope(
        school_id=rec.lecture.school_id, member_id=rec.uploaded_by_id, feature="lecture_recording"
    ):
        try:
            set_status(LectureRecording.STATUS_TRANSCRIBING)
            suffix = Path(rec.file.name).suffix or ".mp3"
            with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
                with rec.file.open("rb") as src:
                    for chunk in iter(lambda: src.read(1024 * 1024), b""):
                        tmp.write(chunk)
                tmp.flush()
                result = transcribe_file(
                    tmp.name, language=rec.language or None, prompt=rec.lecture.title
                )
            if not result.text.strip():
                raise TranscriptionError("No speech was detected in this recording.")
            rec.transcript = result.text
            rec.segments = result.segments
            rec.duration_seconds = result.duration_seconds
            rec.language = rec.language or (result.language or "")[:8]
            rec.save(update_fields=["transcript", "segments", "duration_seconds", "language"])

            set_status(LectureRecording.STATUS_SUMMARIZING)
            try:
                _summarize(rec)
            except Exception:
                logger.exception("lecture summary failed rec=%s", rec.id)
            rec.save(update_fields=["summary", "key_points"])

            set_status(LectureRecording.STATUS_INDEXING)
            rec.document = _index_transcript(rec)
            rec.status = LectureRecording.STATUS_DONE
            rec.finished_at = timezone.now()
            rec.save(update_fields=["document", "status", "finished_at"])
        except TranscriptionError as exc:
            rec.status = LectureRecording.STATUS_FAILED
            rec.error_message = str(exc)
            rec.save(update_fields=["status", "error_message"])
            return {"ok": False, "error": str(exc)}
        except Exception:
            logger.exception("recording pipeline failed rec=%s", rec.id)
            rec.status = LectureRecording.STATUS_FAILED
            rec.error_message = "Could not process this recording."
            rec.save(update_fields=["status", "error_message"])
            return {"ok": False}

    _notify_students(rec)
    return {"ok": True, "document_id": rec.document_id}


def _notify_students(rec: LectureRecording) -> None:
    try:
        from engagement.services.notifications import notify_many
        from ingestion.api_utils import bucket_students

        notify_many(
            bucket_students(rec.lecture.bucket),
            kind="new_notes",
            title=f"Lecture notes ready: {rec.lecture.title}",
            body="Summary, key points, and the full transcript are now searchable in chat.",
            link_path=f"/app/lectures/{rec.lecture_id}",
            payload={"lecture_id": rec.lecture_id, "recording_id": rec.id},
            dedupe_key=f"recording:{rec.id}",
        )
    except Exception:
        logger.exception("recording notification failed")


@shared_task(name="lectures.process_recording", max_retries=0)
def process_recording_task(recording_id: int) -> dict:
    return process_recording(recording_id)
