from django.urls import path

from . import views

urlpatterns = [
    path("summary/", views.EngagementSummaryView.as_view(), name="engagement-summary"),
    path(
        "notifications/",
        views.NotificationListView.as_view(),
        name="engagement-notifications",
    ),
    path(
        "notifications/read-all/",
        views.NotificationReadAllView.as_view(),
        name="engagement-notifications-read-all",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.NotificationReadView.as_view(),
        name="engagement-notification-read",
    ),
    path("preferences/", views.PreferenceView.as_view(), name="engagement-preferences"),
    path("devices/", views.DeviceTokenView.as_view(), name="engagement-devices"),
    path(
        "micro-quizzes/",
        views.MicroQuizListView.as_view(),
        name="engagement-micro-list",
    ),
    path(
        "micro-quizzes/<int:pk>/",
        views.MicroQuizDetailView.as_view(),
        name="engagement-micro-detail",
    ),
    path(
        "micro-quizzes/<int:pk>/submit/",
        views.MicroQuizSubmitView.as_view(),
        name="engagement-micro-submit",
    ),
    path("mastery/", views.MasteryListView.as_view(), name="engagement-mastery"),
    path("impact/", views.ImpactView.as_view(), name="engagement-impact"),
    path(
        "buckets/<int:bucket_id>/investment/",
        views.BucketInvestmentView.as_view(),
        name="engagement-bucket-investment",
    ),
    path(
        "mock-tests/<int:pk>/leaderboard/",
        views.LeaderboardView.as_view(),
        name="engagement-leaderboard",
    ),
    path(
        "mock-tests/<int:pk>/leaderboard/settings/",
        views.LeaderboardSettingsView.as_view(),
        name="engagement-leaderboard-settings",
    ),
]
