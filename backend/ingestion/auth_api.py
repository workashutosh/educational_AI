"""JSON auth endpoints for the React SPA (token-based)."""
from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    DEFAULT_BUCKET_QUOTA_BYTES,
    DEFAULT_MAX_BUCKETS,
    GB,
    PendingOnboard,
    School,
    SchoolMembership,
    SubjectBucket,
)
from .permissions import get_membership
from .services.brevo_service import BrevoError, send_otp_email


def _accessible_buckets(member: SchoolMembership):
    base = SubjectBucket.objects.filter(school=member.school, is_archived=False)
    if member.is_manager_or_above:
        return base
    return base.filter(access_grants__member=member).distinct()


def _member_payload(user: User, token_key: str | None = None) -> dict:
    member = get_membership(user)
    school = member.school if member else None
    if school is not None:
        school.ensure_join_code()

    payload: dict = {
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.first_name or "",
        },
        "membership": None,
        "school": None,
        "buckets": [],
        "can_manage": False,
        "can_upload": False,
        "can_create_students": False,
    }
    if token_key:
        payload["token"] = token_key

    if member is None or school is None:
        return payload

    buckets = list(
        _accessible_buckets(member)
        .order_by("name", "grade_level")
        .values("id", "name", "grade_level")[:50]
    )
    payload.update(
        {
            "membership": {
                "id": member.id,
                "role": member.role,
                "role_display": member.get_role_display(),
            },
            "school": {
                "id": school.id,
                "name": school.name,
                "join_code": school.join_code if member.is_manager_or_above else None,
                "max_buckets": school.max_buckets,
                "bucket_quota_bytes": school.bucket_quota_bytes,
                "max_users": school.max_users,
                "max_managers": school.max_managers,
                "onboarding_complete": school.onboarding_complete,
            },
            "buckets": buckets,
            "can_manage": member.is_manager_or_above,
            "can_upload": member.can_upload,
            "can_create_students": member.can_create_students,
        }
    )
    return payload


def _cleanup_expired_pending() -> None:
    PendingOnboard.objects.filter(expires_at__lt=timezone.now()).delete()


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _send_and_store_otp(pending: PendingOnboard) -> None:
    otp = _generate_otp()
    pending.set_otp(otp)
    pending.otp_expires_at = timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS)
    pending.last_otp_sent_at = timezone.now()
    pending.email_verified = False
    pending.setup_token = None
    pending.setup_token_expires_at = None
    pending.save(
        update_fields=[
            "otp_hash",
            "otp_attempts",
            "otp_expires_at",
            "last_otp_sent_at",
            "email_verified",
            "setup_token",
            "setup_token_expires_at",
        ]
    )
    send_otp_email(
        to_email=pending.email,
        otp=otp,
        organization_name=pending.organization_name,
    )


def _get_pending(pending_id) -> PendingOnboard | None:
    try:
        return PendingOnboard.objects.get(pk=pending_id)
    except (PendingOnboard.DoesNotExist, ValueError, TypeError):
        return None


class AuthLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        username = (request.data.get("username") or "").strip()
        password = request.data.get("password") or ""
        if not username or not password:
            return Response(
                {"detail": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = authenticate(request, username=username, password=password)
        if user is None:
            # Also try lowercased username (email-as-username onboard admins).
            user = authenticate(request, username=username.lower(), password=password)
        if user is None and "@" in username:
            # Students may be told to log in with email even if username differs.
            from django.contrib.auth import get_user_model

            UserModel = get_user_model()
            match = (
                UserModel.objects.filter(email__iexact=username, is_active=True)
                .order_by("id")
                .first()
            )
            if match:
                user = authenticate(
                    request, username=match.username, password=password
                )
        if user is None:
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not user.is_active:
            return Response(
                {"detail": "This account is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response(_member_payload(user, token.key))


class AuthRegisterSchoolView(APIView):
    """
    Legacy one-shot school register (no OTP). Prefer the onboard/* wizard.
    Kept for backward compatibility with older clients.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        school_name = (request.data.get("school_name") or "").strip()
        username = (request.data.get("username") or "").strip()
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        password_confirm = request.data.get("password_confirm") or ""
        full_name = (request.data.get("full_name") or "").strip()

        errors: dict[str, list[str]] = {}
        if not school_name:
            errors.setdefault("school_name", []).append("Required.")
        if not username:
            errors.setdefault("username", []).append("Required.")
        if not email:
            errors.setdefault("email", []).append("Required.")
        if len(password) < 8:
            errors.setdefault("password", []).append("At least 8 characters.")
        if password != password_confirm:
            errors.setdefault("password_confirm", []).append("Passwords do not match.")
        if username and User.objects.filter(username__iexact=username).exists():
            errors.setdefault("username", []).append("That username is already taken.")
        if school_name and School.objects.filter(name__iexact=school_name).exists():
            errors.setdefault("school_name", []).append("A school with that name already exists.")
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name,
            )
            school = School.objects.create(
                name=school_name,
                max_buckets=DEFAULT_MAX_BUCKETS,
                bucket_quota_bytes=DEFAULT_BUCKET_QUOTA_BYTES,
                onboarding_complete=True,
            )
            school.ensure_join_code()
            SchoolMembership.objects.create(
                user=user,
                school=school,
                role=SchoolMembership.ROLE_ADMIN,
            )
            token, _ = Token.objects.get_or_create(user=user)

        return Response(_member_payload(user, token.key), status=status.HTTP_201_CREATED)


class OnboardStartView(APIView):
    """Step 1: validate org form, create PendingOnboard, email OTP via Brevo."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _cleanup_expired_pending()

        organization_name = (request.data.get("organization_name") or "").strip()
        contact_phone = (request.data.get("contact_phone") or "").strip()
        email = (request.data.get("email") or "").strip().lower()
        country_region = (request.data.get("country_region") or "").strip()
        password = request.data.get("password") or ""
        password_confirm = request.data.get("password_confirm") or ""
        privacy_consent = bool(request.data.get("privacy_consent"))

        errors: dict[str, list[str]] = {}
        if not organization_name:
            errors.setdefault("organization_name", []).append("Required.")
        if not contact_phone:
            errors.setdefault("contact_phone", []).append("Required.")
        if not email:
            errors.setdefault("email", []).append("Required.")
        if not country_region:
            errors.setdefault("country_region", []).append("Required.")
        if not privacy_consent:
            errors.setdefault("privacy_consent", []).append("Consent is required.")
        if len(password) < 8:
            errors.setdefault("password", []).append("At least 8 characters.")
        if password != password_confirm:
            errors.setdefault("password_confirm", []).append("Passwords do not match.")
        if email and User.objects.filter(username__iexact=email).exists():
            errors.setdefault("email", []).append("An account with that email already exists.")
        if email and User.objects.filter(email__iexact=email).exists():
            errors.setdefault("email", []).append("An account with that email already exists.")
        if organization_name and School.objects.filter(name__iexact=organization_name).exists():
            errors.setdefault("organization_name", []).append(
                "An organization with that name already exists."
            )
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        # Replace any prior pending row for this email
        PendingOnboard.objects.filter(email__iexact=email).delete()

        pending = PendingOnboard(
            organization_name=organization_name,
            contact_phone=contact_phone,
            email=email,
            country_region=country_region,
            privacy_consent=True,
            expires_at=timezone.now()
            + timedelta(seconds=settings.ONBOARD_PENDING_TTL_SECONDS),
        )
        pending.set_password(password)
        pending.save()

        try:
            _send_and_store_otp(pending)
        except BrevoError as exc:
            pending.delete()
            return Response(
                {"detail": f"Could not send verification email: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "pending_id": pending.id,
                "email": pending.email,
                "otp_expires_in": settings.OTP_TTL_SECONDS,
                "resend_after": settings.OTP_RESEND_COOLDOWN_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )


class OnboardResendOtpView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _cleanup_expired_pending()
        pending_id = request.data.get("pending_id")
        pending = _get_pending(pending_id)
        if pending is None or pending.is_expired:
            return Response(
                {"detail": "Onboarding session expired. Please start again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if pending.email_verified:
            return Response(
                {"detail": "Email already verified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if pending.last_otp_sent_at:
            elapsed = (timezone.now() - pending.last_otp_sent_at).total_seconds()
            cooldown = settings.OTP_RESEND_COOLDOWN_SECONDS
            if elapsed < cooldown:
                return Response(
                    {
                        "detail": "Please wait before requesting another code.",
                        "resend_after": int(cooldown - elapsed),
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
        try:
            _send_and_store_otp(pending)
        except BrevoError as exc:
            return Response(
                {"detail": f"Could not send verification email: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            {
                "pending_id": pending.id,
                "email": pending.email,
                "otp_expires_in": settings.OTP_TTL_SECONDS,
                "resend_after": settings.OTP_RESEND_COOLDOWN_SECONDS,
            }
        )


class OnboardVerifyOtpView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _cleanup_expired_pending()
        pending_id = request.data.get("pending_id")
        otp = (request.data.get("otp") or "").strip()
        pending = _get_pending(pending_id)
        if pending is None or pending.is_expired:
            return Response(
                {"detail": "Onboarding session expired. Please start again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not otp or len(otp) != 6 or not otp.isdigit():
            return Response(
                {"errors": {"otp": ["Enter the 6-digit code."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if pending.otp_attempts >= settings.OTP_MAX_ATTEMPTS:
            return Response(
                {"detail": "Too many attempts. Request a new code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not pending.otp_expires_at or timezone.now() >= pending.otp_expires_at:
            return Response(
                {"detail": "Code expired. Request a new one."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pending.otp_attempts += 1
        pending.save(update_fields=["otp_attempts"])

        if not pending.check_otp(otp):
            remaining = max(0, settings.OTP_MAX_ATTEMPTS - pending.otp_attempts)
            return Response(
                {
                    "detail": "Invalid verification code.",
                    "attempts_remaining": remaining,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        setup_token = uuid.uuid4()
        pending.email_verified = True
        pending.setup_token = setup_token
        pending.setup_token_expires_at = timezone.now() + timedelta(
            seconds=settings.ONBOARD_SETUP_TOKEN_TTL_SECONDS
        )
        pending.otp_hash = ""
        pending.save(
            update_fields=[
                "email_verified",
                "setup_token",
                "setup_token_expires_at",
                "otp_hash",
            ]
        )
        return Response(
            {
                "pending_id": pending.id,
                "setup_token": str(setup_token),
                "setup_expires_in": settings.ONBOARD_SETUP_TOKEN_TTL_SECONDS,
            }
        )


class OnboardCompleteView(APIView):
    """Step 3: apply plan quotas (or defaults) and create School + admin."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        _cleanup_expired_pending()
        setup_token_raw = (request.data.get("setup_token") or "").strip()
        skip = bool(request.data.get("skip", False))

        if not setup_token_raw:
            return Response(
                {"detail": "setup_token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            setup_uuid = uuid.UUID(setup_token_raw)
        except ValueError:
            return Response(
                {"detail": "Invalid setup_token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        pending = PendingOnboard.objects.filter(setup_token=setup_uuid).first()
        if (
            pending is None
            or pending.is_expired
            or not pending.email_verified
            or not pending.setup_token_expires_at
            or timezone.now() >= pending.setup_token_expires_at
        ):
            return Response(
                {"detail": "Setup session expired. Please start onboarding again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_buckets = DEFAULT_MAX_BUCKETS
        bucket_quota_bytes = DEFAULT_BUCKET_QUOTA_BYTES
        max_users = 0
        max_managers = 0

        if not skip:
            try:
                if request.data.get("max_buckets") is not None:
                    max_buckets = int(request.data.get("max_buckets"))
                if request.data.get("bucket_quota_gb") is not None:
                    bucket_quota_bytes = int(float(request.data.get("bucket_quota_gb")) * GB)
                if request.data.get("max_users") is not None:
                    max_users = int(request.data.get("max_users"))
                if request.data.get("max_managers") is not None:
                    max_managers = int(request.data.get("max_managers"))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid plan configuration values."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if max_buckets < 1 or max_buckets > 100:
            return Response(
                {"errors": {"max_buckets": ["Must be between 1 and 100."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if bucket_quota_bytes < GB or bucket_quota_bytes > 100 * GB:
            return Response(
                {"errors": {"bucket_quota_gb": ["Must be between 1 and 100 GB."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if max_users < 0 or max_managers < 0:
            return Response(
                {"detail": "Seat counts cannot be negative."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Re-check uniqueness at completion time
        if User.objects.filter(username__iexact=pending.email).exists():
            return Response(
                {"detail": "An account with that email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if School.objects.filter(name__iexact=pending.organization_name).exists():
            return Response(
                {"detail": "An organization with that name already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user = User(
                username=pending.email,
                email=pending.email,
                first_name="",
            )
            user.password = pending.password_hash
            user.save()

            school = School.objects.create(
                name=pending.organization_name,
                contact_phone=pending.contact_phone,
                country_region=pending.country_region,
                privacy_consent_at=timezone.now() if pending.privacy_consent else None,
                max_buckets=max_buckets,
                bucket_quota_bytes=bucket_quota_bytes,
                max_users=max_users,
                max_managers=max_managers,
                onboarding_complete=True,
            )
            school.ensure_join_code()
            SchoolMembership.objects.create(
                user=user,
                school=school,
                role=SchoolMembership.ROLE_ADMIN,
            )
            token, _ = Token.objects.get_or_create(user=user)
            pending_id = pending.id
            pending.delete()

        payload = _member_payload(user, token.key)
        payload["pending_id"] = pending_id
        return Response(payload, status=status.HTTP_201_CREATED)


class AuthRegisterJoinView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        join_code = (request.data.get("join_code") or "").strip().upper()
        role = (request.data.get("role") or SchoolMembership.ROLE_TEACHER).strip()
        username = (request.data.get("username") or "").strip()
        email = (request.data.get("email") or "").strip()
        password = request.data.get("password") or ""
        password_confirm = request.data.get("password_confirm") or ""
        full_name = (request.data.get("full_name") or "").strip()

        errors: dict[str, list[str]] = {}
        if not join_code:
            errors.setdefault("join_code", []).append("Required.")
        if role not in {SchoolMembership.ROLE_TEACHER, SchoolMembership.ROLE_STUDENT}:
            errors.setdefault("role", []).append("Choose teacher or student.")
        if not username:
            errors.setdefault("username", []).append("Required.")
        if not email:
            errors.setdefault("email", []).append("Required.")
        if len(password) < 8:
            errors.setdefault("password", []).append("At least 8 characters.")
        if password != password_confirm:
            errors.setdefault("password_confirm", []).append("Passwords do not match.")
        if username and User.objects.filter(username__iexact=username).exists():
            errors.setdefault("username", []).append("That username is already taken.")

        school = None
        if join_code:
            school = School.objects.filter(join_code__iexact=join_code, is_active=True).first()
            if school is None:
                errors.setdefault("join_code", []).append("No active school found for that code.")

        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        assert school is not None
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=full_name,
            )
            SchoolMembership.objects.create(user=user, school=school, role=role)
            token, _ = Token.objects.get_or_create(user=user)

        return Response(_member_payload(user, token.key), status=status.HTTP_201_CREATED)


class AuthMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        token, _ = Token.objects.get_or_create(user=request.user)
        return Response(_member_payload(request.user, token.key))


class AuthLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response({"detail": "Signed out."})
