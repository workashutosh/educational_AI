from django.urls import path

from . import views

urlpatterns = [
    path("decks/", views.DeckListCreateView.as_view(), name="learning-decks"),
    path("decks/generate/", views.DeckGenerateView.as_view(), name="learning-deck-generate"),
    path("decks/<int:pk>/", views.DeckDetailView.as_view(), name="learning-deck-detail"),
    path("decks/<int:pk>/cards/", views.DeckCardCreateView.as_view(), name="learning-deck-cards"),
    path("cards/<int:pk>/", views.CardDetailView.as_view(), name="learning-card-detail"),
    path("study/", views.StudyQueueView.as_view(), name="learning-study"),
    path("study/review/", views.StudyReviewView.as_view(), name="learning-study-review"),
    path("study/stats/", views.StudyStatsView.as_view(), name="learning-study-stats"),
    path("doubts/", views.DoubtListCreateView.as_view(), name="learning-doubts"),
    path("doubts/<int:pk>/", views.DoubtDetailView.as_view(), name="learning-doubt-detail"),
    path("doubts/<int:pk>/answer/", views.DoubtAnswerView.as_view(), name="learning-doubt-answer"),
    path("doubts/<int:pk>/close/", views.DoubtCloseView.as_view(), name="learning-doubt-close"),
    path("feedback/", views.FeedbackView.as_view(), name="learning-feedback"),
    path("feedback/summary/", views.FeedbackSummaryView.as_view(), name="learning-feedback-summary"),
]
