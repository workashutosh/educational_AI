"""Test fixtures shared by app test suites (no external services)."""
from __future__ import annotations

import itertools

from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import BucketAccess, School, SchoolMembership, SubjectBucket

_seq = itertools.count(1)


def make_school(name: str = "Test School", **kw) -> School:
    return School.objects.create(name=f"{name} {next(_seq)}", **kw)


def make_member(school: School, role: str = "teacher", *, username: str | None = None, email: str = "") -> SchoolMembership:
    user = get_user_model().objects.create_user(
        username=username or f"{role}{next(_seq)}", password="pass12345!", email=email
    )
    return SchoolMembership.objects.create(school=school, user=user, role=role)


def make_bucket(school: School, name: str = "Physics") -> SubjectBucket:
    return SubjectBucket.objects.create(school=school, name=f"{name} {next(_seq)}", grade_level="XII")


def grant(member: SchoolMembership, bucket: SubjectBucket) -> None:
    BucketAccess.objects.get_or_create(member=member, bucket=bucket)


def client_for(user_or_member) -> APIClient:
    user = getattr(user_or_member, "user", user_or_member)
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client
