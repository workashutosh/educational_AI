from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from ingestion.testing import client_for, grant, make_bucket, make_member, make_school

from .models import Assignment, Submission


class HomeworkFlowTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.s1 = make_member(self.school, "student")
        self.s2 = make_member(self.school, "student")
        for m in (self.teacher, self.s1, self.s2):
            grant(m, self.bucket)
        self.llm = mock.patch(
            "homework.services.llm_json",
            return_value={"score": 7.5, "feedback": "Good start.", "improvements": ["Add units"]},
        )
        self.llm.start()
        self.addCleanup(self.llm.stop)

    def _create(self, **extra):
        body = {
            "bucket_id": self.bucket.id,
            "title": "Ohm's law worksheet",
            "instructions": "Solve all three.",
            "max_marks": 10,
            "rubric": "3 marks per answer, 1 for units",
            "assign_all": True,
            "publish": True,
            **extra,
        }
        return client_for(self.teacher).post("/api/homework/", body, format="json")

    def test_full_cycle_after_review(self):
        res = self._create()
        self.assertEqual(res.status_code, 201, res.content)
        hw_id = res.json()["id"]
        self.assertEqual(res.json()["status"], "published")
        self.assertEqual(res.json()["assigned_count"], 2)

        sc = client_for(self.s1)
        listing = sc.get("/api/homework/").json()
        self.assertEqual(listing[0]["my_status"], "pending")
        photo = SimpleUploadedFile("page1.txt", b"V = IR so I = 2 A", content_type="text/plain")
        sub = sc.post(f"/api/homework/{hw_id}/submit/", {"text_answer": "See photo", "files": [photo]}, format="multipart")
        self.assertEqual(sub.status_code, 201, sub.content)
        sub_data = sub.json()
        # after_review: AI score hidden from the student until released
        self.assertIsNone(sub_data["ai_score"])
        stored = Submission.objects.get()
        self.assertEqual((stored.ai_status, stored.ai_score), ("done", 7.5))
        self.assertIn("I = 2 A", stored.extracted_text)

        tc = client_for(self.teacher)
        roster = tc.get(f"/api/homework/{hw_id}/submissions/").json()
        self.assertEqual(roster["counts"], {"pending": 1, "submitted": 1})
        graded = tc.post(f"/api/homework/submissions/{stored.id}/grade/", {"score": 8, "feedback": "Nice", "release": True}, format="json")
        self.assertEqual(graded.status_code, 200, graded.content)
        mine = sc.get(f"/api/homework/{hw_id}/").json()["my_submission"]
        self.assertEqual((mine["teacher_score"], mine["released"]), (8.0, True))
        again = sc.post(f"/api/homework/{hw_id}/submit/", {"text_answer": "retry"}, format="multipart")
        self.assertEqual(again.status_code, 400)

    def test_immediate_mode_shows_ai_score(self):
        hw_id = self._create(results_mode="immediate").json()["id"]
        sub = client_for(self.s1).post(f"/api/homework/{hw_id}/submit/", {"text_answer": "V=IR"}, format="multipart")
        detail = client_for(self.s1).get(f"/api/homework/submissions/{sub.json()['id']}/").json()
        self.assertEqual(detail["ai_score"], 7.5)

    def test_access_rules(self):
        hw_id = self._create(assign_all=False, student_ids=[self.s1.id], publish=True).json()["id"]
        self.assertEqual(client_for(self.s2).get(f"/api/homework/{hw_id}/").status_code, 403)
        self.assertEqual(client_for(self.s1).post("/api/homework/", {"bucket_id": self.bucket.id, "title": "x"}, format="json").status_code, 403)
        Assignment.objects.filter(pk=hw_id).update(due_at=timezone.now() - timedelta(hours=1), allow_late=False)
        late = client_for(self.s1).post(f"/api/homework/{hw_id}/submit/", {"text_answer": "x"}, format="multipart")
        self.assertEqual(late.status_code, 400)

    def test_cannot_publish_without_students(self):
        res = self._create(assign_all=False)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Assign at least one student", res.json()["detail"])
