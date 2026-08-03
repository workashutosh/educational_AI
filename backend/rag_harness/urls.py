from django.urls import path

from .views import HarnessQueryView

urlpatterns = [
    path("query/", HarnessQueryView.as_view(), name="harness-query"),
]
