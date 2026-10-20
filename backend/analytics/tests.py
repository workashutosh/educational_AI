from unittest import mock

from django.test import TestCase
from django.utils import timezone

from ingestion.testing import client_for, grant, make_bucket, make_member, make_school
from mock_tests.models import MockAttempt, MockQuestion, MockTest
from question_bank.models import Topic
from question_bank.services.bank import add_items


class TopicAnalyticsTests(TestCase):
    def setUp(self):
        patcher = mock.patch("question_bank.services.tagging.search_bucket", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.student = make_member(self.school, "student")
        grant(self.teacher, self.bucket)
        grant(self.student, self.bucket)
        self.optics = Topic.objects.create(school=self.school, bucket=self.bucket, name="Optics")
        self.waves = Topic.objects.create(school=self.school, bucket=self.bucket, name="Waves")

        test = MockTest.objects.create(
            school=self.school, bucket=self.bucket, created_by=self.teacher, title="Unit test",
            topic_prompt="x", status="published", results_mode="immediate",
        )
        answers = {}
        for i in range(3):  # optics: all wrong
            q = MockQuestion.objects.create(test=test, order=i, qtype="mcq", prompt=f"O{i}", options=["a", "b"], correct_indices=[0], topic=self.optics)
            answers[str(q.id)] = 1
        for i in range(3):  # waves: all right
            q = MockQuestion.objects.create(test=test, order=10 + i, qtype="mcq", prompt=f"W{i}", options=["a", "b"], correct_indices=[0], topic=self.waves)
            answers[str(q.id)] = 0
        MockAttempt.objects.create(test=test, student=self.student, answers=answers, submitted_at=timezone.now())

    def test_student_report_flags_weak_topic(self):
        data = client_for(self.student).get(f"/api/analytics/me/topics/?bucket_id={self.bucket.id}").json()
        status = {r["topic_name"]: (r["status"], r["accuracy"]) for r in data["topics"]}
        self.assertEqual(status["Optics"], ("weak", 0.0))
        self.assertEqual(status["Waves"], ("strong", 100.0))
        self.assertEqual([w["topic_name"] for w in data["weak_topics"]], ["Optics"])

    def test_heatmap_and_remediation(self):
        tc = client_for(self.teacher)
        heat = tc.get(f"/api/analytics/buckets/{self.bucket.id}/heatmap/").json()
        self.assertEqual(heat["students"][0]["weak_topics"], ["Optics"])
        self.assertEqual(client_for(self.student).get(f"/api/analytics/buckets/{self.bucket.id}/heatmap/").status_code, 403)

        add_items(
            self.bucket,
            [{"qtype": "mcq", "prompt": f"Optics practice {i}", "options": ["a", "b"], "correct_indices": [0]} for i in range(4)],
            source="manual",
            topic=self.optics,
        )
        res = tc.post("/api/analytics/remediate/", {"bucket_id": self.bucket.id, "question_count": 5}, format="json")
        self.assertEqual(res.status_code, 201, res.content)
        body = res.json()
        self.assertEqual([t["topic_name"] for t in body["topics"]], ["Optics"])
        self.assertEqual(body["question_count"], 4)  # capped to what the bank has
        practice = MockTest.objects.get(pk=body["mock_test_id"])
        self.assertEqual((practice.status, practice.assignments.count()), ("published", 1))

    def test_self_practice_without_bank_items(self):
        res = client_for(self.student).post("/api/analytics/me/practice/", {"bucket_id": self.bucket.id}, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("no practice questions", res.json()["detail"])
