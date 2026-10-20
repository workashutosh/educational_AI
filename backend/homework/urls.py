from django.urls import path

from . import views

urlpatterns = [
    path("", views.AssignmentListCreateView.as_view(), name="homework-list"),
    path("<int:pk>/", views.AssignmentDetailView.as_view(), name="homework-detail"),
    path("<int:pk>/attachment/", views.AssignmentAttachmentView.as_view(), name="homework-attachment"),
    path("<int:pk>/assign/", views.AssignmentAssignView.as_view(), name="homework-assign"),
    path("<int:pk>/publish/", views.AssignmentPublishView.as_view(), name="homework-publish"),
    path("<int:pk>/close/", views.AssignmentCloseView.as_view(), name="homework-close"),
    path("<int:pk>/submit/", views.AssignmentSubmitView.as_view(), name="homework-submit"),
    path("<int:pk>/submissions/", views.AssignmentSubmissionsView.as_view(), name="homework-submissions"),
    path("<int:pk>/release/", views.AssignmentReleaseView.as_view(), name="homework-release"),
    path("submissions/<int:sid>/", views.SubmissionDetailView.as_view(), name="homework-submission"),
    path("submissions/<int:sid>/grade/", views.SubmissionGradeView.as_view(), name="homework-grade"),
    path("submissions/<int:sid>/regrade-ai/", views.SubmissionRegradeView.as_view(), name="homework-regrade"),
    path(
        "submissions/<int:sid>/files/<int:fid>/",
        views.SubmissionFileView.as_view(),
        name="homework-submission-file",
    ),
]
