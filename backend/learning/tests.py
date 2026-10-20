from unittest import mock

from django.test import TestCase, override_settings

from ingestion.models import ChatMessage, ChatSession, Document
from ingestion.services.answer_service import GeneratedAnswer
from ingestion.services.retrieval_service import RetrievedChunk
from ingestion.testing import client_for, grant, make_bucket, make_member, make_school

from .models import ChatFeedback, Doubt, Flashcard, FlashcardDeck
from .services.srs import next_schedule


class SchedulerTests(TestCase):
    def test_sm2_progression(self):
        s1 = next_schedule(ease=2.5, interval_days=0, repetitions=0, lapses=0, grade=4)
        self.assertEqual((s1.interval_days, s1.repetitions), (1.0, 1))
        s2 = next_schedule(ease=s1.ease, interval_days=1, repetitions=1, lapses=0, grade=4)
        self.assertEqual(s2.interval_days, 6.0)
        s3 = next_schedule(ease=s2.ease, interval_days=6, repetitions=2, lapses=0, grade=5)
        self.assertGreater(s3.interval_days, 15)
        lapse = next_schedule(ease=2.5, interval_days=20, repetitions=4, lapses=0, grade=1)
        self.assertEqual((lapse.repetitions, lapse.lapses), (0, 1))
        self.assertLess(lapse.ease, 2.5)
        self.assertGreaterEqual(next_schedule(ease=1.3, interval_days=1, repetitions=1, lapses=0, grade=0).ease, 1.3)


class FlashcardApiTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.student = make_member(self.school, "student")
        self.outsider = make_member(self.school, "student")
        for m in (self.teacher, self.student):
            grant(m, self.bucket)

    def test_shared_deck_study_and_review(self):
        res = client_for(self.teacher).post(
            "/api/learning/decks/",
            {"bucket_id": self.bucket.id, "title": "Units", "cards": [{"front": "SI unit of force", "back": "newton"}, {"front": "Power", "back": "watt"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        deck_id = res.json()["id"]
        self.assertEqual(res.json()["visibility"], "bucket")

        self.assertEqual(client_for(self.outsider).get(f"/api/learning/decks/{deck_id}/").status_code, 404)
        sc = client_for(self.student)
        queue = sc.get(f"/api/learning/study/?deck_id={deck_id}").json()
        self.assertEqual((len(queue["cards"]), queue["new_count"]), (2, 2))
        card_id = queue["cards"][0]["id"]
        review = sc.post("/api/learning/study/review/", {"card_id": card_id, "button": "good"}, format="json")
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["interval_days"], 1.0)
        self.assertEqual(len(sc.get(f"/api/learning/study/?deck_id={deck_id}").json()["cards"]), 1)
        self.assertEqual(sc.patch(f"/api/learning/decks/{deck_id}/", {"title": "x"}, format="json").status_code, 403)

    def test_student_generated_decks_are_private(self):
        fake = {"title": "Optics", "cards": [{"front": "Lens", "back": "Refracts light"}, {"front": "Lens", "back": "dup"}]}
        with mock.patch("learning.services.content.retrieve", return_value=[{"chunk_id": 3, "text": "lens"}]), \
             mock.patch("learning.services.content.llm_json", return_value=fake):
            res = client_for(self.student).post(
                "/api/learning/decks/generate/",
                {"bucket_id": self.bucket.id, "prompt": "lenses", "count": 5, "visibility": "bucket"},
                format="json",
            )
        self.assertEqual(res.status_code, 201, res.content)
        deck = FlashcardDeck.objects.get(pk=res.json()["id"])
        self.assertEqual(deck.visibility, "private")
        self.assertEqual(Flashcard.objects.filter(deck=deck).count(), 1)
        self.assertEqual(client_for(self.teacher).get(f"/api/learning/decks/{deck.id}/").status_code, 404)


class DoubtAndFeedbackTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.student = make_member(self.school, "student")
        for m in (self.teacher, self.student):
            grant(m, self.bucket)
        self.session = ChatSession.objects.create(bucket=self.bucket, member=self.student)

    def _ask(self, answer_text):
        result = GeneratedAnswer(
            answer=answer_text,
            sources=[RetrievedChunk(1, 1, "notes.pdf", ["Optics"], 3, 3, "text", 0.41)],
            model="m",
            retrieval_query="q",
        )
        with mock.patch("ingestion.views.answer_question", return_value=result) as ask, \
             override_settings(ALLOW_OPEN_ASK=False):
            res = client_for(self.student).post(
                "/api/ask/",
                {"bucket_id": self.bucket.id, "query": "What is a black hole?", "session_id": self.session.id, "language": "hi"},
                format="json",
            )
        return res, ask

    def test_unanswered_question_becomes_doubt(self):
        res, ask = self._ask("I couldn't find that in the indexed notes.")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(ask.call_args.kwargs["language"], "hi")
        body = res.json()
        self.assertIsNotNone(body["message_id"])
        self.assertEqual(body["language"], "hi")
        doubt = Doubt.objects.get(pk=body["doubt_id"])
        self.assertEqual((doubt.reason, doubt.status), ("no_answer", "open"))
        # Same question again the same day reuses the doubt.
        self.assertEqual(self._ask("I couldn't find that in the indexed notes.")[0].json()["doubt_id"], doubt.id)

    def test_answered_question_has_no_doubt(self):
        res, _ = self._ask("A black hole is…")
        self.assertIsNone(res.json()["doubt_id"])

    def test_teacher_answers_and_publishes_to_notes(self):
        doubt = Doubt.objects.create(school=self.school, bucket=self.bucket, student=self.student, question="Why is the sky blue?")
        tc = client_for(self.teacher)
        inbox = tc.get("/api/learning/doubts/?status=open").json()
        self.assertEqual((inbox["count"], inbox["open_count"]), (1, 1))
        with mock.patch("ingestion.tasks.process_document.delay") as delay:
            res = tc.post(f"/api/learning/doubts/{doubt.id}/answer/", {"answer": "Rayleigh scattering.", "add_to_notes": True}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        doubt.refresh_from_db()
        self.assertEqual(doubt.status, "answered")
        doc = Document.objects.get(pk=doubt.published_document_id)
        self.assertEqual(doc.kind, "notes")
        delay.assert_called_once_with(doc.id)
        seen = client_for(self.student).get(f"/api/learning/doubts/{doubt.id}/").json()
        self.assertIsNotNone(seen["student_seen_at"])
        other = make_member(self.school, "student")
        self.assertEqual(client_for(other).get(f"/api/learning/doubts/{doubt.id}/").status_code, 403)

    def test_feedback_and_summary(self):
        ChatMessage.objects.create(session=self.session, role="user", content="Explain lenses")
        msg = ChatMessage.objects.create(session=self.session, role="assistant", content="Lenses…", sources=[{"score": 0.3}])
        sc = client_for(self.student)
        res = sc.post(
            "/api/learning/feedback/",
            {"message_id": msg.id, "rating": -1, "reason": "incomplete", "ask_teacher": True},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIsNotNone(res.json()["doubt_id"])
        self.assertEqual(Doubt.objects.get().question, "Explain lenses")
        sc.post("/api/learning/feedback/", {"message_id": msg.id, "rating": 1}, format="json")
        self.assertEqual(ChatFeedback.objects.get().rating, 1)

        summary = client_for(self.teacher).get(f"/api/learning/feedback/summary/?bucket_id={self.bucket.id}").json()
        self.assertEqual((summary["total"], summary["helpful"]), (1, 1))
        self.assertEqual(client_for(self.student).get("/api/learning/feedback/summary/").status_code, 403)
