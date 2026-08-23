from django.urls import path

from . import auth_api, views

urlpatterns = [
    path("auth/login/", auth_api.AuthLoginView.as_view(), name="auth-login"),
    path("auth/register/school/", auth_api.AuthRegisterSchoolView.as_view(), name="auth-register-school"),
    path("auth/register/join/", auth_api.AuthRegisterJoinView.as_view(), name="auth-register-join"),
    path("auth/onboard/start/", auth_api.OnboardStartView.as_view(), name="auth-onboard-start"),
    path("auth/onboard/resend-otp/", auth_api.OnboardResendOtpView.as_view(), name="auth-onboard-resend"),
    path("auth/onboard/verify-otp/", auth_api.OnboardVerifyOtpView.as_view(), name="auth-onboard-verify"),
    path("auth/onboard/complete/", auth_api.OnboardCompleteView.as_view(), name="auth-onboard-complete"),
    path("auth/me/", auth_api.AuthMeView.as_view(), name="auth-me"),
    path("auth/logout/", auth_api.AuthLogoutView.as_view(), name="auth-logout"),
    path("buckets/", views.BucketListView.as_view(), name="bucket-list"),
    path("documents/", views.DocumentListCreateView.as_view(), name="document-list-create"),
    path("documents/<int:pk>/status/", views.DocumentStatusView.as_view(), name="document-status"),
    path(
        "documents/<int:pk>/pages/<int:page>/",
        views.DocumentPageImageView.as_view(),
        name="document-page-image",
    ),
    path("query/", views.QueryView.as_view(), name="query"),
    path("ask/", views.AskView.as_view(), name="ask"),
    path("generate-pptx/", views.GeneratePptxView.as_view(), name="generate-pptx"),
    path(
        "generate-pptx/download/",
        views.DownloadPptxView.as_view(),
        name="generate-pptx-download",
    ),
    path("chat/sessions/", views.ChatSessionListCreateView.as_view(), name="chat-session-list"),
    path(
        "chat/sessions/<int:pk>/",
        views.ChatSessionDetailView.as_view(),
        name="chat-session-detail",
    ),
    path("admin/buckets/", views.AdminBucketCreateView.as_view(), name="admin-bucket-create"),
    path("admin/members/", views.AdminMembersListView.as_view(), name="admin-members"),
    path(
        "admin/members/create/",
        views.AdminCreateMemberView.as_view(),
        name="admin-create-member",
    ),
    path(
        "admin/members/<int:member_id>/access/",
        views.AdminMemberAccessView.as_view(),
        name="admin-member-access",
    ),
    path("admin/students/", views.AdminCreateStudentView.as_view(), name="admin-create-student"),
    path(
        "admin/buckets/<int:pk>/grant/",
        views.AdminGrantAccessView.as_view(),
        name="admin-bucket-grant",
    ),
    path(
        "admin/buckets/<int:pk>/grant/<int:member_id>/",
        views.AdminRevokeAccessView.as_view(),
        name="admin-bucket-revoke",
    ),
    path(
        "admin/buckets/<int:pk>/access/",
        views.AdminBucketAccessListView.as_view(),
        name="admin-bucket-access",
    ),
]
