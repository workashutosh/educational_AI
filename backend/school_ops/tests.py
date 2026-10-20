from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from ingestion.testing import client_for, grant, make_bucket, make_member, make_school
from lectures.models import Lecture

from .models import AttendanceRecord, ParentProfile


class AttendanceTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.s1 = make_member(self.school, "student")
        self.s2 = make_member(self.school, "student")
        for m in (self.teacher, self.s1, self.s2):
            grant(m, self.bucket)
        now = timezone.now()
        self.lecture = Lecture.objects.create(
            school=self.school,
            bucket=self.bucket,
            created_by=self.teacher,
            title="Waves",
            starts_at=now - timedelta(minutes=30),
            ends_at=now + timedelta(minutes=30),
            status=Lecture.STATUS_LIVE,
        )

    def test_join_end_and_manual_override(self):
        room = client_for(self.s1).get(f"/api/lectures/{self.lecture.id}/room/")
        self.assertEqual(room.status_code, 200)
        self.assertEqual(room.json()["attendance"]["status"], "late")
        client_for(self.teacher).post(f"/api/lectures/{self.lecture.id}/end/")
        self.assertEqual(AttendanceRecord.objects.get(student=self.s2).status, "absent")

        tc = client_for(self.teacher)
        roster = tc.get(f"/api/attendance/lectures/{self.lecture.id}/").json()
        self.assertEqual(roster["counts"], {"late": 1, "absent": 1})
        res = tc.put(
            f"/api/attendance/lectures/{self.lecture.id}/",
            {"records": [{"student_id": self.s2.id, "status": "excused", "note": "Sick"}]},
            format="json",
        )
        self.assertEqual(res.json()["counts"], {"late": 1, "excused": 1})

        me = client_for(self.s1).get("/api/attendance/me/").json()
        self.assertEqual((me["attended"], me["total"], me["percent"]), (1, 1, 100.0))
        self.assertEqual(client_for(self.s1).get(f"/api/attendance/lectures/{self.lecture.id}/").status_code, 403)
        bucket_view = tc.get(f"/api/attendance/buckets/{self.bucket.id}/").json()
        self.assertEqual(len(bucket_view["students"]), 2)


class ParentPortalTests(TestCase):
    def setUp(self):
        self.school = make_school()
        self.bucket = make_bucket(self.school)
        self.teacher = make_member(self.school, "teacher")
        self.child = make_member(self.school, "student")
        self.other_child = make_member(self.school, "student")
        grant(self.teacher, self.bucket)
        grant(self.child, self.bucket)

    def _create_parent(self, client=None, student_ids=None):
        return (client or client_for(self.teacher)).post(
            "/api/parents/",
            {
                "username": "parent_raj",
                "password": "longpassword1",
                "full_name": "Raj",
                "student_ids": student_ids or [self.child.id],
                "relationship": "father",
            },
            format="json",
        )

    def test_teacher_creates_parent_for_own_students_only(self):
        self.assertEqual(self._create_parent(student_ids=[self.other_child.id]).status_code, 403)
        res = self._create_parent()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()["children"][0]["relationship"], "father")

    def test_parent_login_and_scope(self):
        self._create_parent()
        login = self.client.post("/api/auth/login/", {"username": "parent_raj", "password": "longpassword1"}, content_type="application/json")
        data = login.json()
        self.assertEqual((data["account_type"], data["membership"]), ("parent", None))
        self.assertEqual(data["parent"]["children"][0]["student_id"], self.child.id)

        pc = client_for(ParentProfile.objects.get().user)
        overview = pc.get(f"/api/parent/children/{self.child.id}/")
        self.assertEqual(overview.status_code, 200, overview.content)
        self.assertIn("attendance", overview.json())
        self.assertEqual(pc.get(f"/api/parent/children/{self.other_child.id}/").status_code, 404)
        # Parents never reach member endpoints.
        self.assertEqual(pc.get("/api/buckets/").status_code, 403)
        self.assertEqual(pc.get("/api/homework/").status_code, 403)
        self.assertEqual(client_for(self.teacher).get("/api/parent/me/").status_code, 403)
