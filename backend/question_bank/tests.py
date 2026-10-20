from unittest import mock

from django.test import TestCase

from ingestion.testing import client_for, grant, make_bucket, make_member, make_school
from mock_tests.models import MockQuestion, MockTest

from .models import QuestionItem, QuestionPaper, Topic
from .services.bank import add_items, normalize_item, pick_items, split_by_mix

class NoTagMixin:
    """Topic tagging hits local embeddings; tests stub it out."""

    def setUp(self):
        patcher = mock.patch("question_bank.services.tagging.search_bucket", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()


def mcq(prompt, difficulty="medium", **kw):
    return {
        "qtype": "mcq",
        "prompt": prompt,
        "options": ["a", "b", "c", "d"],
        "correct_indices": [1],
        "difficulty": difficulty,
        **kw,
    }


class BankServiceTests(NoTagMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.topic = Topic.objects.create(school=self.school, bucket=self.bucket, name="Optics")

    def test_normalize_rejects_and_fixes(self):
        self.assertIsNone(normalize_item({"qtype": "mcq", "prompt": "What?", "options": ["x"], "correct_indices": [0]}))
        multi_one = normalize_item({"qtype": "multi", "prompt": "Pick all", "options": ["a", "b"], "correct_indices": [0]})
        self.assertEqual(multi_one["qtype"], "mcq")
        brief = normalize_item({"type": "short", "question": "Define lens power", "model_answer": "1/f"})
        self.assertEqual((brief["qtype"], brief["answer"], brief["options"]), ("brief", "1/f", []))

    def test_add_items_dedupes(self):
        created, skipped = add_items(self.bucket, [mcq("What is refraction?"), mcq("what is  REFRACTION")], source="manual")
        self.assertEqual((len(created), skipped), (1, 1))

    def test_split_by_mix(self):
        self.assertEqual(split_by_mix(10, {"easy": 30, "medium": 50, "hard": 20}), {"easy": 3, "medium": 5, "hard": 2})
        self.assertEqual(split_by_mix(4, None), {"any": 4})

    def test_pick_prefers_least_used_and_relaxes_difficulty(self):
        items, _ = add_items(
            self.bucket,
            [mcq(f"Question number {i}", "easy" if i < 3 else "hard") for i in range(6)],
            source="manual",
            topic=self.topic,
        )
        QuestionItem.objects.filter(pk=items[0].pk).update(times_used=5)
        picked = pick_items(self.bucket, qtype="mcq", count=4, difficulty_mix={"easy": 100})
        self.assertEqual(len(picked), 4)
        self.assertNotIn(items[0].pk, [p.pk for p in picked][:2])


class BankApiTests(NoTagMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.student = make_member(self.school, "student")
        grant(self.teacher, self.bucket)
        grant(self.student, self.bucket)
        self.topic = Topic.objects.create(school=self.school, bucket=self.bucket, name="Optics")

    def test_students_cannot_use_bank(self):
        res = client_for(self.student).get(f"/api/question-bank/items/?bucket_id={self.bucket.id}")
        self.assertEqual(res.status_code, 403)

    def test_teacher_without_grant_is_blocked(self):
        other = make_member(self.school, "teacher")
        res = client_for(other).post(
            "/api/question-bank/items/", {"bucket_id": self.bucket.id, **mcq("Why is the sky blue?")}, format="json"
        )
        self.assertEqual(res.status_code, 403)

    def test_crud_filter_and_pagination(self):
        c = client_for(self.teacher)
        res = c.post(
            "/api/question-bank/items/",
            {"bucket_id": self.bucket.id, "topic_id": self.topic.id, **mcq("Why is the sky blue?")},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        item_id = res.json()["id"]
        dup = c.post("/api/question-bank/items/", {"bucket_id": self.bucket.id, **mcq("Why is the sky blue?")}, format="json")
        self.assertEqual(dup.status_code, 400)

        listing = c.get(f"/api/question-bank/items/?bucket_id={self.bucket.id}&topic_id={self.topic.id}&limit=1").json()
        self.assertEqual((listing["count"], listing["results"][0]["topic_name"]), (1, "Optics"))

        res = c.patch(f"/api/question-bank/items/{item_id}/", {"difficulty": "hard", "correct_indices": [9]}, format="json")
        self.assertEqual(res.status_code, 400)
        res = c.patch(f"/api/question-bank/items/{item_id}/", {"difficulty": "hard"}, format="json")
        self.assertEqual(res.json()["difficulty"], "hard")
        self.assertEqual(c.delete(f"/api/question-bank/items/{item_id}/").status_code, 204)
        self.assertTrue(QuestionItem.objects.get(pk=item_id).is_archived)

    def test_generate_uses_llm_json(self):
        fake = {"questions": [mcq("Generated about lenses"), {"qtype": "brief", "prompt": "Define focal length", "answer": "f"}]}
        with mock.patch("question_bank.services.bank.retrieve", return_value=[{"chunk_id": 1, "text": "lens", "document_id": 1}]), \
             mock.patch("question_bank.services.bank.llm_json", return_value=fake):
            res = client_for(self.teacher).post(
                "/api/question-bank/items/generate/",
                {"bucket_id": self.bucket.id, "topic_id": self.topic.id, "counts": {"mcq": 1, "brief": 1}},
                format="json",
            )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(len(res.json()), 2)
        self.assertEqual(QuestionItem.objects.filter(source="ai_generated", topic=self.topic).count(), 2)

    def test_build_mock_test_from_bank_and_assign(self):
        add_items(self.bucket, [mcq(f"Bank question {i}") for i in range(5)], source="manual", topic=self.topic)
        res = client_for(self.teacher).post(
            "/api/question-bank/build-mock-test/",
            {
                "bucket_id": self.bucket.id,
                "title": "Optics drill",
                "counts": {"mcq": 3},
                "topic_ids": [self.topic.id],
                "assign_student_ids": [self.student.id],
                "publish": True,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        test = MockTest.objects.get(pk=res.json()["mock_test_id"])
        self.assertEqual(test.status, "published")
        self.assertEqual(test.questions.filter(topic=self.topic).count(), 3)
        self.assertEqual(QuestionItem.objects.filter(times_used=1).count(), 3)

        too_many = client_for(self.teacher).post(
            "/api/question-bank/build-mock-test/",
            {"bucket_id": self.bucket.id, "counts": {"mcq": 50}},
            format="json",
        )
        self.assertEqual(too_many.status_code, 400)

    def test_import_mock_test_tags_questions(self):
        test = MockTest.objects.create(school=self.school, bucket=self.bucket, created_by=self.teacher, title="T", topic_prompt="x")
        MockQuestion.objects.create(test=test, order=1, qtype="mcq", prompt="Mirror question?", options=["a", "b"], correct_indices=[0], topic=self.topic)
        res = client_for(self.teacher).post("/api/question-bank/items/import-mock-test/", {"mock_test_id": test.id}, format="json")
        self.assertEqual(res.json(), {"created": 1, "skipped": 0})
        self.assertEqual(QuestionItem.objects.get().topic, self.topic)


class PaperTests(NoTagMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        grant(self.teacher, self.bucket)
        add_items(self.bucket, [mcq(f"Paper mcq {i}") for i in range(4)], source="manual")
        add_items(
            self.bucket,
            [{"qtype": "long", "prompt": f"Explain phenomenon {i}", "answer": "because"} for i in range(2)],
            source="manual",
        )

    def _create(self, **extra):
        body = {
            "bucket_id": self.bucket.id,
            "title": "Half-yearly Physics",
            "source_mode": "bank_only",
            "sections": [
                {"title": "Section A", "qtype": "mcq", "count": 3, "marks_each": 1},
                {"title": "Section B", "qtype": "long", "count": 3, "marks_each": 5},
            ],
            **extra,
        }
        return client_for(self.teacher).post("/api/question-bank/papers/", body, format="json")

    def test_create_paper_reports_shortfall(self):
        res = self._create()
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        self.assertEqual(data["question_count"], 5)
        self.assertEqual(data["total_marks"], 3 + 10)
        self.assertTrue(any("only 2 of 3" in n for n in data["generation_notes"]))

    def test_export_swap_and_to_mock(self):
        paper_id = self._create().json()["id"]
        c = client_for(self.teacher)
        pdf = c.get(f"/api/question-bank/papers/{paper_id}/export/?fmt=pdf&answers=1")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        docx = c.get(f"/api/question-bank/papers/{paper_id}/export/?fmt=docx")
        self.assertEqual(docx.content[:2], b"PK")

        paper = QuestionPaper.objects.get(pk=paper_id)
        item = paper.sections.first().items.first()
        swapped = c.post(f"/api/question-bank/papers/{paper_id}/items/{item.id}/swap/")
        self.assertEqual(swapped.status_code, 200, swapped.content)
        self.assertNotEqual(swapped.json()["question"], item.question_id)

        mock_res = c.post(f"/api/question-bank/papers/{paper_id}/to-mock-test/")
        self.assertEqual(mock_res.status_code, 201)
        test = MockTest.objects.get(pk=mock_res.json()["mock_test_id"])
        self.assertEqual((test.count_mcq, test.count_brief), (3, 2))

    def test_final_paper_is_locked(self):
        paper_id = self._create().json()["id"]
        c = client_for(self.teacher)
        c.patch(f"/api/question-bank/papers/{paper_id}/", {"status": "final"}, format="json")
        item = QuestionPaper.objects.get(pk=paper_id).sections.first().items.first()
        res = c.patch(f"/api/question-bank/papers/{paper_id}/items/{item.id}/", {"marks": 2}, format="json")
        self.assertEqual(res.status_code, 400)


class TopicNamingTests(TestCase):
    def test_section_then_chapter_fallback(self):
        from .services.tagging import topic_name_from_heading as name

        self.assertEqual(name(["APPLICATION OF DERIVATIVES", "6.4  Maxima and Minima"]), "6.4 Maxima and Minima")
        self.assertEqual(name(["CONTINUITY AND DIFFERENTIABILITY", "5.3.  Differentiability"]), "5.3 Differentiability")
        self.assertEqual(name(["CONTINUITY AND DIFFERENTIABILITY", "5.1  Introduction"]), "Continuity and Differentiability")
        self.assertEqual(name(["MATRICES", "EXERCISE 3.2"]), "Matrices")
        self.assertEqual(name(["MATHEMATICS", "Textbook for Class XII", "Preface"]), "")
        self.assertEqual(name(["Summary"]), "")
        self.assertEqual(name(["Physics", "Optics"]), "Physics")
