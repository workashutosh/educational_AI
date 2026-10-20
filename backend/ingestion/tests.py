from unittest import mock

from django.test import TestCase

from .services.language_service import answer_instruction, mostly_non_latin, normalize_language, retrieval_query_in_english
from .testing import client_for, make_member, make_school


class ApiConventionTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.teacher = make_member(self.school, "teacher")

    def test_v1_mirror_serves_same_views(self):
        c = client_for(self.teacher)
        self.assertEqual(c.get("/api/buckets/").status_code, 200)
        self.assertEqual(c.get("/api/v1/buckets/").json(), c.get("/api/buckets/").json())

    def test_validation_errors_have_detail(self):
        res = client_for(self.teacher).post("/api/question-bank/papers/", {"title": "x"}, format="json")
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertIn("detail", body)
        self.assertIn("bucket_id", body["errors"])

    def test_unauthenticated_is_401_or_403_with_detail(self):
        res = self.client.get("/api/homework/")
        self.assertIn(res.status_code, (401, 403))
        self.assertIn("detail", res.json())

    def test_change_password_rotates_token(self):
        c = client_for(self.teacher)
        res = c.post("/api/auth/password/change/", {"old_password": "pass12345!", "new_password": "a-much-better-pass-42"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(c.get("/api/buckets/").status_code, 401)

    def test_device_registration(self):
        c = client_for(self.teacher)
        res = c.post("/api/engagement/devices/", {"token": "fcm-abc", "platform": "android"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(c.post("/api/engagement/devices/", {"token": "x", "platform": "nokia"}, format="json").status_code, 400)


class LanguageTests(TestCase):
    def test_normalize_and_instruction(self):
        self.assertEqual(normalize_language("Hindi"), "hi")
        self.assertEqual(normalize_language("klingon"), "en")
        self.assertEqual(answer_instruction("en"), "")
        self.assertIn("Tamil", answer_instruction("ta"))

    def test_translate_only_non_latin_questions(self):
        self.assertTrue(mostly_non_latin("प्रकाश का अपवर्तन क्या है?"))
        self.assertFalse(mostly_non_latin("What is refraction?"))
        with mock.patch("ingestion.services.language_service.chat_completion", return_value="What is refraction of light?") as llm:
            self.assertEqual(retrieval_query_in_english("What is refraction?"), "What is refraction?")
            llm.assert_not_called()
            self.assertEqual(retrieval_query_in_english("प्रकाश का अपवर्तन क्या है?"), "What is refraction of light?")
