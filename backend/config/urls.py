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
    path("api/", include("ingestion.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
