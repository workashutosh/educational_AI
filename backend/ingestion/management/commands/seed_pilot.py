"""
Seed two pilot schools with admin/manager/teacher/student memberships + buckets.

  python manage.py seed_pilot
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from ingestion.models import BucketAccess, School, SchoolMembership, SubjectBucket


User = get_user_model()


class Command(BaseCommand):
    help = "Seed 2-school pilot users, roles, and subject buckets."

    def handle(self, *args, **options):
        schools = [
            ("Greenfield High", "greenfield"),
            ("Riverside Academy", "riverside"),
        ]
        for school_name, slug in schools:
            school, _ = School.objects.get_or_create(name=school_name)
            school.ensure_join_code()
            self.stdout.write(f"School {school_name} join code: {school.join_code}")
            roles = [
                (SchoolMembership.ROLE_ADMIN, f"{slug}_admin"),
                (SchoolMembership.ROLE_MANAGER, f"{slug}_manager"),
                (SchoolMembership.ROLE_TEACHER, f"{slug}_teacher"),
                (SchoolMembership.ROLE_STUDENT, f"{slug}_student"),
            ]
            members = {}
            for role, username in roles:
                user, created = User.objects.get_or_create(
                    username=username,
                    defaults={"email": f"{username}@example.com"},
                )
                if created or not user.has_usable_password():
                    user.set_password("changeme123")
                    user.save()
                member, _ = SchoolMembership.objects.update_or_create(
                    user=user,
                    defaults={"school": school, "role": role, "is_active": True},
                )
                Token.objects.get_or_create(user=user)
                members[role] = member
                self.stdout.write(f"  {school_name}: {username} / changeme123 [{role}]")

            for subject, grade in (("Mathematics", "Class 12"), ("Physics", "Class 12")):
                bucket, _ = SubjectBucket.objects.get_or_create(
                    school=school, name=subject, grade_level=grade
                )
                # Teachers & students need explicit grants; admin/manager don't.
                for role in (SchoolMembership.ROLE_TEACHER, SchoolMembership.ROLE_STUDENT):
                    BucketAccess.objects.get_or_create(
                        member=members[role],
                        bucket=bucket,
                        defaults={"granted_by": members[SchoolMembership.ROLE_ADMIN]},
                    )

        self.stdout.write(self.style.SUCCESS("Pilot seed complete."))
