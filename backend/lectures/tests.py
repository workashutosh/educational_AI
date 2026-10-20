from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from ingestion.models import Document
from ingestion.services.speech_service import Transcript
from ingestion.testing import client_for, grant, make_bucket, make_member, make_school

from .models import Lecture, LectureRecording

FAKE = Transcript(
    text="Today we study waves. A wave transfers energy.",
    duration_seconds=125.0,
    language="en",
    segments=[{"start": 0, "end": 60, "text": "Today we study waves."}, {"start": 60, "end": 125, "text": "A wave transfers energy."}],
)


@override_settings(GROQ_API_KEY="test-key")
class RecordingTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.student = make_member(self.school, "student")
        grant(self.teacher, self.bucket)
        grant(self.student, self.bucket)
        now = timezone.now()
        self.lecture = Lecture.objects.create(
            school=self.school, bucket=self.bucket, created_by=self.teacher, title="Waves",
            starts_at=now, ends_at=now + timedelta(hours=1),
        )

    def test_upload_transcribes_summarizes_and_indexes(self):
        audio = SimpleUploadedFile("class.mp3", b"ID3fake", content_type="audio/mpeg")
        with mock.patch("lectures.recordings.transcribe_file", return_value=FAKE), \
             mock.patch("lectures.recordings.llm_json", return_value={"summary": "## Waves\nEnergy transfer.", "key_points": ["Waves carry energy"]}), \
             mock.patch("ingestion.tasks.process_document_sync") as index:
            res = client_for(self.teacher).post(
                f"/api/lectures/{self.lecture.id}/recordings/", {"file": audio}, format="multipart"
            )
        self.assertEqual(res.status_code, 202, res.content)
        rec = LectureRecording.objects.get()
        self.assertEqual((rec.status, rec.duration_seconds), ("done", 125.0))
        self.assertEqual(rec.key_points, ["Waves carry energy"])
        doc = Document.objects.get(pk=rec.document_id)
        index.assert_called_once_with(doc.id)
        body = doc.file.read().decode()
        self.assertIn("## Key points", body)
        self.assertIn("**[00:00:00]**", body)

        detail = client_for(self.student).get(f"/api/lectures/recordings/{rec.id}/").json()
        self.assertIn("transfers energy", detail["transcript"])
        self.assertEqual(
            client_for(self.student).post(f"/api/lectures/{self.lecture.id}/recordings/", {"file": audio}, format="multipart").status_code,
            403,
        )

    def test_rejects_non_audio(self):
        bad = SimpleUploadedFile("notes.pdf", b"%PDF", content_type="application/pdf")
        res = client_for(self.teacher).post(f"/api/lectures/{self.lecture.id}/recordings/", {"file": bad}, format="multipart")
        self.assertEqual(res.status_code, 400)


@override_settings(GROQ_API_KEY="test-key")
class VoiceInputTests(TestCase):
    def test_transcribe_voice_question(self):
        school = make_school()
        student = make_member(school, "student")
        audio = SimpleUploadedFile("q.webm", b"\x1a\x45\xdf\xa3", content_type="audio/webm")
        with mock.patch("ingestion.services.speech_service._post", return_value={"text": "what is torque", "duration": 2.5, "language": "en"}):
            res = client_for(student).post("/api/speech/transcribe/", {"audio": audio, "language": "en"}, format="multipart")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["text"], "what is torque")
