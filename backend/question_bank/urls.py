from django.urls import path

from . import views

urlpatterns = [
    path("topics/", views.TopicListCreateView.as_view(), name="qb-topics"),
    path("topics/sync/", views.TopicSyncView.as_view(), name="qb-topics-sync"),
    path("topics/tag-untagged/", views.TagUntaggedView.as_view(), name="qb-tag-untagged"),
    path("topics/<int:pk>/", views.TopicDetailView.as_view(), name="qb-topic-detail"),
    path("items/", views.ItemListCreateView.as_view(), name="qb-items"),
    path("items/generate/", views.GenerateItemsView.as_view(), name="qb-items-generate"),
    path("items/import-mock-test/", views.ImportMockTestView.as_view(), name="qb-import-mock"),
    path("items/import-document/", views.ImportDocumentView.as_view(), name="qb-import-document"),
    path("items/<int:pk>/", views.ItemDetailView.as_view(), name="qb-item-detail"),
    path("import-jobs/", views.ImportJobListView.as_view(), name="qb-import-jobs"),
    path("import-jobs/<int:pk>/", views.ImportJobDetailView.as_view(), name="qb-import-job"),
    path("coverage/", views.CoverageView.as_view(), name="qb-coverage"),
    path("build-mock-test/", views.BuildMockTestView.as_view(), name="qb-build-mock"),
    path("papers/", views.PaperListCreateView.as_view(), name="qb-papers"),
    path("papers/<int:pk>/", views.PaperDetailView.as_view(), name="qb-paper-detail"),
    path(
        "papers/<int:pk>/sections/<int:section_id>/refill/",
        views.PaperSectionRefillView.as_view(),
        name="qb-paper-section-refill",
    ),
    path(
        "papers/<int:pk>/items/<int:item_id>/",
        views.PaperItemDetailView.as_view(),
        name="qb-paper-item",
    ),
    path(
        "papers/<int:pk>/items/<int:item_id>/swap/",
        views.PaperItemSwapView.as_view(),
        name="qb-paper-item-swap",
    ),
    path("papers/<int:pk>/export/", views.PaperExportView.as_view(), name="qb-paper-export"),
    path(
        "papers/<int:pk>/to-mock-test/",
        views.PaperToMockTestView.as_view(),
        name="qb-paper-to-mock",
    ),
]
