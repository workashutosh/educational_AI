"""Browser auth: login, school onboarding, join-school registration."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from rest_framework.authtoken.models import Token

from .forms import JoinSchoolForm, LoginForm, SchoolOnboardForm
from .models import School, SchoolMembership, SubjectBucket
from .permissions import get_membership


def _home_for(user):
    member = get_membership(user)
    if member is None:
        return redirect("onboarding_needed")
    return redirect("app_home")


def _accessible_buckets(member: SchoolMembership):
    base = SubjectBucket.objects.filter(school=member.school, is_archived=False)
    if member.is_manager_or_above:
        return base
    return base.filter(access_grants__member=member).distinct()


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return _home_for(request.user)

    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if user is None:
            messages.error(request, "Invalid username or password.")
        elif not user.is_active:
            messages.error(request, "This account is disabled.")
        else:
            login(request, user)
            next_url = request.GET.get("next") or request.POST.get("next")
            if next_url:
                return redirect(next_url)
            return _home_for(user)

    return render(request, "ingestion/auth/login.html", {"form": form})


@require_http_methods(["POST", "GET"])
def logout_view(request):
    logout(request)
    messages.success(request, "Signed out.")
    return redirect("login")


@require_http_methods(["GET", "POST"])
def register_school_view(request):
    """Onboarding: create a new school + first admin account."""
    if request.user.is_authenticated:
        return _home_for(request.user)

    form = SchoolOnboardForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if User.objects.filter(username__iexact=form.cleaned_data["username"]).exists():
                    form.add_error("username", "That username is already taken.")
                    raise ValueError("username")
                if School.objects.filter(name__iexact=form.cleaned_data["school_name"]).exists():
                    form.add_error("school_name", "A school with that name already exists.")
                    raise ValueError("school")

                user = User.objects.create_user(
                    username=form.cleaned_data["username"].strip(),
                    email=form.cleaned_data["email"].strip(),
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data.get("full_name", "").strip(),
                )
                school = School.objects.create(name=form.cleaned_data["school_name"].strip())
                school.ensure_join_code()
                SchoolMembership.objects.create(
                    user=user,
                    school=school,
                    role=SchoolMembership.ROLE_ADMIN,
                )
                Token.objects.get_or_create(user=user)
            login(request, user)
            messages.success(
                request,
                f"School “{school.name}” created. Share join code {school.join_code} "
                "with teachers and students.",
            )
            return redirect("app_home")
        except ValueError:
            pass

    return render(request, "ingestion/auth/register_school.html", {"form": form})


@require_http_methods(["GET", "POST"])
def register_join_view(request):
    """Join an existing school as teacher or student using the school join code."""
    if request.user.is_authenticated:
        return _home_for(request.user)

    form = JoinSchoolForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if User.objects.filter(username__iexact=form.cleaned_data["username"]).exists():
                    form.add_error("username", "That username is already taken.")
                    raise ValueError("username")

                code = form.cleaned_data["join_code"].strip().upper()
                school = School.objects.filter(join_code__iexact=code, is_active=True).first()
                if school is None:
                    form.add_error("join_code", "No active school found for that code.")
                    raise ValueError("code")

                user = User.objects.create_user(
                    username=form.cleaned_data["username"].strip(),
                    email=form.cleaned_data["email"].strip(),
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data.get("full_name", "").strip(),
                )
                SchoolMembership.objects.create(
                    user=user,
                    school=school,
                    role=form.cleaned_data["role"],
                )
                Token.objects.get_or_create(user=user)
            login(request, user)
            messages.success(
                request,
                f"Welcome to {school.name}. Ask an admin/manager to grant bucket access if needed.",
            )
            return redirect("app_home")
        except ValueError:
            pass

    return render(request, "ingestion/auth/register_join.html", {"form": form})


@login_required(login_url="/accounts/login/")
def onboarding_needed(request):
    if get_membership(request.user):
        return redirect("app_home")
    return render(request, "ingestion/auth/onboarding_needed.html")


@login_required(login_url="/accounts/login/")
def app_home(request):
    member = get_membership(request.user)
    if member is None:
        return redirect("onboarding_needed")

    school = member.school
    school.ensure_join_code()
    token, _ = Token.objects.get_or_create(user=request.user)
    buckets = list(_accessible_buckets(member).order_by("name", "grade_level")[:20])

    return render(
        request,
        "ingestion/app/home.html",
        {
            "member": member,
            "school": school,
            "buckets": buckets,
            "api_token": token.key,
            "can_manage": member.is_manager_or_above,
            "can_upload": member.can_upload,
        },
    )
