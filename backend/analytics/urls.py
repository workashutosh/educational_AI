from django.urls import path

from . import views

urlpatterns = [
    path("me/topics/", views.MyTopicsView.as_view(), name="analytics-me-topics"),
    path("me/practice/", views.SelfPracticeView.as_view(), name="analytics-me-practice"),
    path("students/<int:student_id>/topics/", views.StudentTopicsView.as_view(), name="analytics-student-topics"),
    path("buckets/<int:bucket_id>/heatmap/", views.BucketHeatmapView.as_view(), name="analytics-heatmap"),
    path("buckets/<int:bucket_id>/weak-topics/", views.BucketWeakTopicsView.as_view(), name="analytics-weak-topics"),
    path("remediate/", views.RemediateView.as_view(), name="analytics-remediate"),
]
