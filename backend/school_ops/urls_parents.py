from django.urls import path

from . import views

# Staff-side management: /api/parents/…
manage_urlpatterns = [
    path("", views.ParentListCreateView.as_view(), name="parents"),
    path("<int:pk>/", views.ParentDetailView.as_view(), name="parent-detail"),
    path("<int:pk>/links/", views.ParentLinkView.as_view(), name="parent-links"),
    path("<int:pk>/links/<int:student_id>/", views.ParentUnlinkView.as_view(), name="parent-link-delete"),
]

# Parent-facing portal: /api/parent/…
portal_urlpatterns = [
    path("me/", views.ParentMeView.as_view(), name="parent-me"),
    path("preferences/", views.ParentPreferencesView.as_view(), name="parent-preferences"),
    path("children/<int:student_id>/", views.ParentChildOverviewView.as_view(), name="parent-child"),
    path(
        "children/<int:student_id>/attendance/",
        views.ParentChildAttendanceView.as_view(),
        name="parent-child-attendance",
    ),
]
