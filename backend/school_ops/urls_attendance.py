from django.urls import path

from . import views

urlpatterns = [
    path("me/", views.MyAttendanceView.as_view(), name="attendance-me"),
    path("lectures/<int:lecture_id>/", views.LectureAttendanceView.as_view(), name="attendance-lecture"),
    path("buckets/<int:bucket_id>/", views.BucketAttendanceView.as_view(), name="attendance-bucket"),
    path("students/<int:student_id>/", views.StudentAttendanceView.as_view(), name="attendance-student"),
]
