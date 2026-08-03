from django.urls import path

from . import views

urlpatterns = [
    path("teams/status/", views.TeamsStatusView.as_view(), name="lectures-teams-status"),
    path("", views.LectureListCreateView.as_view(), name="lecture-list-create"),
    path("<int:pk>/", views.LectureDetailView.as_view(), name="lecture-detail"),
    path("<int:pk>/room/", views.LectureRoomView.as_view(), name="lecture-room"),
    path("<int:pk>/go-live/", views.LectureGoLiveView.as_view(), name="lecture-go-live"),
    path("<int:pk>/end/", views.LectureEndView.as_view(), name="lecture-end"),
    path(
        "<int:pk>/create-teams/",
        views.LectureCreateTeamsView.as_view(),
        name="lecture-create-teams",
    ),
]
