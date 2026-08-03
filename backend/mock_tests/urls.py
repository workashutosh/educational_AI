from django.urls import path

from . import views

urlpatterns = [
    path("", views.MockTestListCreateView.as_view(), name="mock-test-list"),
    path("<int:pk>/", views.MockTestDetailView.as_view(), name="mock-test-detail"),
    path(
        "<int:pk>/questions/<int:qid>/",
        views.MockQuestionDetailView.as_view(),
        name="mock-question-detail",
    ),
    path(
        "<int:pk>/regenerate/",
        views.MockTestRegenerateView.as_view(),
        name="mock-test-regenerate",
    ),
    path("<int:pk>/assign/", views.MockTestAssignView.as_view(), name="mock-test-assign"),
    path(
        "<int:pk>/assign/<int:student_id>/",
        views.MockTestUnassignView.as_view(),
        name="mock-test-unassign",
    ),
    path("<int:pk>/publish/", views.MockTestPublishView.as_view(), name="mock-test-publish"),
    path("<int:pk>/close/", views.MockTestCloseView.as_view(), name="mock-test-close"),
    path("<int:pk>/start/", views.MockTestStartView.as_view(), name="mock-test-start"),
    path("<int:pk>/submit/", views.MockTestSubmitView.as_view(), name="mock-test-submit"),
    path("<int:pk>/me/", views.MockTestMeView.as_view(), name="mock-test-me"),
    path("<int:pk>/results/", views.MockTestResultsView.as_view(), name="mock-test-results"),
    path(
        "<int:pk>/results/release/",
        views.MockTestReleaseResultsView.as_view(),
        name="mock-test-release-results",
    ),
    path(
        "<int:pk>/results/<int:student_id>/",
        views.MockTestStudentResultView.as_view(),
        name="mock-test-student-result",
    ),
    path(
        "<int:pk>/results/<int:student_id>/release/",
        views.MockTestReleaseResultsView.as_view(),
        name="mock-test-release-student",
    ),
    path(
        "<int:pk>/results/<int:student_id>/questions/<int:qid>/confirm/",
        views.MockTestConfirmBriefView.as_view(),
        name="mock-test-confirm-brief",
    ),
]
