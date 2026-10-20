from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from ingestion.auth_views import (
    app_home,
    login_view,
    logout_view,
    onboarding_needed,
    register_join_view,
    register_school_view,
)
from ingestion.views import ask_test_page
from school_ops import urls_parents

api_patterns = [
    path("", include("ingestion.urls")),
    path("harness/", include("rag_harness.urls")),
    path("mock-tests/", include("mock_tests.urls")),
    path("lectures/", include("lectures.urls")),
    path("engagement/", include("engagement.urls")),
    path("question-bank/", include("question_bank.urls")),
    path("learning/", include("learning.urls")),
    path("homework/", include("homework.urls")),
    path("analytics/", include("analytics.urls")),
    path("attendance/", include("school_ops.urls_attendance")),
    path("parents/", include(urls_parents.manage_urlpatterns)),
    path("parent/", include(urls_parents.portal_urlpatterns)),
    path("billing/", include("billing.urls")),
]

urlpatterns = [
    path("", app_home, name="root"),
    path("app/", app_home, name="app_home"),
    path("accounts/login/", login_view, name="login"),
    path("accounts/logout/", logout_view, name="logout"),
    path("accounts/register/school/", register_school_view, name="register_school"),
    path("accounts/register/join/", register_join_view, name="register_join"),
    path("accounts/onboarding/", onboarding_needed, name="onboarding_needed"),
    path("admin/", admin.site.urls),
    path("ask-test/", ask_test_page, name="ask-test"),
    path("api/", include(api_patterns)),
    # Stable, versioned mirror for mobile apps (same views, same auth).
    path("api/v1/", include((api_patterns, "v1"))),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
