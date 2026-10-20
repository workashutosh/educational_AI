from django.urls import path

from . import views

urlpatterns = [
    path("teams/status/", views.TeamsStatusView.as_view(), name="lectures-teams-status"),
    path("teams/connect/", views.TeamsConnectView.as_view(), name="lectures-teams-connect"),
    path(
        "teams/callback/",
        views.TeamsOAuthCallbackView.as_view(),
        name="lectures-teams-callback",
    ),
    path(
        "teams/disconnect/",
        views.TeamsDisconnectView.as_view(),
        name="lectures-teams-disconnect",
    ),
    path("", views.LectureListCreateView.as_view(), name="lecture-list-create"),
    path("<int:pk>/", views.LectureDetailView.as_view(), name="lecture-detail"),
    path("<int:pk>/room/", views.LectureRoomView.as_view(), name="lecture-room"),
    path("<int:pk>/go-live/", views.LectureGoLiveView.as_view(), name="lecture-go-live"),
    path("<int:pk>/end/", views.LectureEndView.as_view(), name="lecture-end"),
    path(
        "<int:pk>/recordings/",
        views.LectureRecordingListCreateView.as_view(),
        name="lecture-recordings",
    ),
    path(
        "recordings/<int:rec_id>/",
        views.LectureRecordingDetailView.as_view(),
        name="lecture-recording-detail",
    ),
    path(
        "recordings/<int:rec_id>/audio/",
        views.LectureRecordingAudioView.as_view(),
        name="lecture-recording-audio",
    ),
    path(
        "<int:pk>/create-teams/",
        views.LectureCreateTeamsView.as_view(),
        name="lecture-create-teams",
    ),
]
