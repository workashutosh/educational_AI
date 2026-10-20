"""Flashcards + spaced repetition, doubt inbox, and chat answer feedback."""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.api_utils import accessible_buckets, bucket_for, is_staff, paginate
from ingestion.models import ChatMessage, Document
from ingestion.permissions import IsSchoolMember, IsStaffMember
from ingestion.services.llm_errors import LLMProviderError, http_status_for_llm_error

from .models import ChatFeedback, Doubt, Flashcard, FlashcardDeck, ReviewLog
from .serializers import (
    CardInputSerializer,
    DeckCreateSerializer,
    DeckDetailSerializer,
    DeckGenerateSerializer,
    DeckSerializer,
    DeckUpdateSerializer,
    DoubtAnswerSerializer,
    DoubtCreateSerializer,
    DoubtSerializer,
    FeedbackSerializer,
    FlashcardSerializer,
    ReviewSerializer,
)
from .services.content import (
    LearningError,
    answer_doubt,
    feedback_summary,
    generate_deck,
    open_doubt,
    top_source_score,
)
from .services.srs import GRADE_BUTTONS, due_cards, review_card, visible_decks


def _deck_qs(member):
    return visible_decks(member).select_related("bucket", "owner__user").annotate(card_count=Count("cards"))


def _deck_for(member, pk, *, edit: bool = False) -> FlashcardDeck:
    deck = get_object_or_404(_deck_qs(member), pk=pk)
    if edit and not (deck.owner_id == member.id or member.is_manager_or_above):
        raise PermissionDenied("Only the deck owner can change it.")
    return deck


def _visibility_for(member, requested: str | None) -> str:
    # Students' decks are always private; staff default to sharing with the bucket.
    if not is_staff(member):
        return FlashcardDeck.VISIBILITY_PRIVATE
    return requested or FlashcardDeck.VISIBILITY_BUCKET


# ---------------------------------------------------------------------------
# Decks & cards
# ---------------------------------------------------------------------------


class DeckListCreateView(APIView):
    permission_classes = [IsSchoolMember]

    @extend_schema(parameters=[OpenApiParameter("bucket_id", int)], responses=DeckSerializer(many=True))
    def get(self, request):
        qs = _deck_qs(request.member)
        if request.query_params.get("bucket_id"):
            qs = qs.filter(bucket_id=request.query_params["bucket_id"])
        return Response(DeckSerializer(qs[:200], many=True, context={"member": request.member}).data)

    @extend_schema(request=DeckCreateSerializer, responses=DeckDetailSerializer)
    def post(self, request):
        from question_bank.models import Topic

        ser = DeckCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        topic = Topic.objects.filter(pk=vd.get("topic_id"), bucket=bucket).first() if vd.get("topic_id") else None
        deck = FlashcardDeck.objects.create(
            school=bucket.school,
            bucket=bucket,
            owner=request.member,
            title=vd["title"].strip(),
            description=vd.get("description") or "",
            topic=topic,
            visibility=_visibility_for(request.member, vd.get("visibility")),
        )
        Flashcard.objects.bulk_create(
            [
                Flashcard(deck=deck, order=i, front=c["front"], back=c["back"], topic=topic)
                for i, c in enumerate(vd.get("cards") or [])
            ]
        )
        deck = _deck_for(request.member, deck.pk)
        return Response(
            DeckDetailSerializer(deck, context={"member": request.member}).data,
            status=status.HTTP_201_CREATED,
        )


class DeckGenerateView(APIView):
    """POST — AI deck from a topic/prompt or one document's notes."""

    permission_classes = [IsSchoolMember]

    @extend_schema(request=DeckGenerateSerializer, responses=DeckDetailSerializer)
    def post(self, request):
        from question_bank.models import Topic

        ser = DeckGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        document = None
        if vd.get("document_id"):
            document = get_object_or_404(
                Document,
                pk=vd["document_id"],
                bucket=bucket,
                status=Document.STATUS_INDEXED,
                deleted_at__isnull=True,
            )
        topic = Topic.objects.filter(pk=vd.get("topic_id"), bucket=bucket).first() if vd.get("topic_id") else None
        try:
            deck = generate_deck(
                request.member,
                bucket,
                prompt=vd.get("prompt") or "",
                title=vd.get("title") or "",
                count=vd["count"],
                document=document,
                topic=topic,
                visibility=_visibility_for(request.member, vd.get("visibility")),
            )
        except LearningError as exc:
            return Response({"detail": str(exc)}, status=400)
        except LLMProviderError as exc:
            return Response({"detail": exc.public_message}, status=http_status_for_llm_error(exc))
        deck = _deck_for(request.member, deck.pk)
        return Response(
            DeckDetailSerializer(deck, context={"member": request.member}).data,
            status=status.HTTP_201_CREATED,
        )


class DeckDetailView(APIView):
    permission_classes = [IsSchoolMember]

    @extend_schema(responses=DeckDetailSerializer)
    def get(self, request, pk):
        deck = _deck_for(request.member, pk)
        return Response(DeckDetailSerializer(deck, context={"member": request.member}).data)

    @extend_schema(request=DeckUpdateSerializer, responses=DeckSerializer)
    def patch(self, request, pk):
        deck = _deck_for(request.member, pk, edit=True)
        ser = DeckUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        for field, value in ser.validated_data.items():
            if field == "visibility":
                value = _visibility_for(request.member, value)
            setattr(deck, field, value)
        deck.save()
        return Response(DeckSerializer(_deck_for(request.member, pk), context={"member": request.member}).data)

    def delete(self, request, pk):
        _deck_for(request.member, pk, edit=True).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeckCardCreateView(APIView):
    permission_classes = [IsSchoolMember]

    @extend_schema(request=CardInputSerializer, responses=FlashcardSerializer)
    def post(self, request, pk):
        deck = _deck_for(request.member, pk, edit=True)
        ser = CardInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        card = Flashcard.objects.create(
            deck=deck,
            order=deck.cards.count(),
            front=ser.validated_data["front"],
            back=ser.validated_data["back"],
            topic_id=ser.validated_data.get("topic_id") or deck.topic_id,
        )
        return Response(FlashcardSerializer(card).data, status=status.HTTP_201_CREATED)


class CardDetailView(APIView):
    permission_classes = [IsSchoolMember]

    def _get(self, request, pk):
        card = get_object_or_404(Flashcard.objects.select_related("deck"), pk=pk)
        _deck_for(request.member, card.deck_id, edit=True)
        return card

    @extend_schema(request=CardInputSerializer, responses=FlashcardSerializer)
    def patch(self, request, pk):
        card = self._get(request, pk)
        for field in ("front", "back", "order"):
            if field in request.data:
                setattr(card, field, request.data[field])
        card.save()
        return Response(FlashcardSerializer(card).data)

    def delete(self, request, pk):
        self._get(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Study (spaced repetition)
# ---------------------------------------------------------------------------


class StudyQueueView(APIView):
    """GET ?bucket_id&deck_id&limit — cards to review now (due first, then new)."""

    permission_classes = [IsSchoolMember]

    @extend_schema(
        parameters=[OpenApiParameter("bucket_id", int), OpenApiParameter("deck_id", int), OpenApiParameter("limit", int)]
    )
    def get(self, request):
        try:
            limit = max(1, min(100, int(request.query_params.get("limit", 30))))
        except ValueError:
            limit = 30
        queue = due_cards(
            request.member,
            bucket_id=request.query_params.get("bucket_id"),
            deck_id=request.query_params.get("deck_id"),
            limit=limit,
        )
        return Response(
            {
                "due_count": queue["due_count"],
                "new_count": queue["new_count"],
                "cards": [
                    {
                        "id": card.id,
                        "deck_id": card.deck_id,
                        "deck_title": card.deck.title,
                        "front": card.front,
                        "back": card.back,
                        "state": kind,
                    }
                    for card, kind in queue["cards"]
                ],
                "buttons": GRADE_BUTTONS,
            }
        )


class StudyReviewView(APIView):
    """POST {card_id, grade 0-5 | button again|hard|good|easy} — schedule next review."""

    permission_classes = [IsSchoolMember]

    @extend_schema(request=ReviewSerializer)
    def post(self, request):
        ser = ReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        card = get_object_or_404(Flashcard.objects.select_related("deck__bucket"), pk=vd["card_id"])
        if not visible_decks(request.member).filter(pk=card.deck_id).exists():
            return Response({"detail": "Card not found."}, status=404)
        grade = vd.get("grade")
        if grade is None:
            grade = GRADE_BUTTONS[vd["button"]]
        state = review_card(request.member, card, grade)

        # First review of the day counts toward the student's streak.
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if ReviewLog.objects.filter(member=request.member, reviewed_at__gte=start).count() == 1:
            try:
                from engagement.models import EngagementActivity
                from engagement.services.activity import record_activity

                record_activity(
                    member=request.member,
                    kind=EngagementActivity.KIND_FLASHCARD,
                    bucket=card.deck.bucket,
                    ref_id=f"deck:{card.deck_id}",
                )
            except Exception:
                pass
        return Response(
            {
                "card_id": card.id,
                "grade": grade,
                "ease": state.ease,
                "interval_days": state.interval_days,
                "repetitions": state.repetitions,
                "due_at": state.due_at,
            }
        )


class StudyStatsView(APIView):
    """GET — reviews today/this week and due counts per bucket."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        from .models import CardState

        member = request.member
        now = timezone.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        logs = ReviewLog.objects.filter(member=member)
        per_bucket = []
        for bucket in accessible_buckets(member):
            cards = Flashcard.objects.filter(deck__in=visible_decks(member).filter(bucket=bucket))
            total = cards.count()
            if not total:
                continue
            seen = CardState.objects.filter(member=member, card__in=cards)
            per_bucket.append(
                {
                    "bucket_id": bucket.id,
                    "bucket_name": bucket.name,
                    "cards": total,
                    "due": seen.filter(due_at__lte=now).count(),
                    "new": total - seen.count(),
                    "learned": seen.filter(repetitions__gte=2).count(),
                }
            )
        return Response(
            {
                "reviews_today": logs.filter(reviewed_at__gte=start).count(),
                "reviews_7d": logs.filter(reviewed_at__gte=now - timedelta(days=7)).count(),
                "buckets": per_bucket,
            }
        )


# ---------------------------------------------------------------------------
# Doubts
# ---------------------------------------------------------------------------


def _doubt_for(member, pk) -> Doubt:
    doubt = get_object_or_404(
        Doubt.objects.select_related("bucket", "student__user", "answered_by__user"),
        pk=pk,
        school=member.school,
    )
    if is_staff(member):
        bucket_for(member, doubt.bucket_id)
    elif doubt.student_id != member.id:
        raise PermissionDenied("Not your doubt.")
    return doubt


class DoubtListCreateView(APIView):
    """
    GET — students: their own doubts; staff: doubts in their buckets
    (?status=open|answered|closed, ?bucket_id, paginated).
    POST — student asks a teacher.
    """

    permission_classes = [IsSchoolMember]

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("bucket_id", int)])
    def get(self, request):
        member = request.member
        qs = Doubt.objects.filter(school=member.school).select_related(
            "bucket", "student__user", "answered_by__user"
        )
        if is_staff(member):
            qs = qs.filter(bucket__in=accessible_buckets(member))
        else:
            qs = qs.filter(student=member)
        if request.query_params.get("bucket_id"):
            qs = qs.filter(bucket_id=request.query_params["bucket_id"])
        open_count = qs.filter(status=Doubt.STATUS_OPEN).count()
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = paginate(request, qs)
        page["results"] = DoubtSerializer(page["results"], many=True).data
        page["open_count"] = open_count
        return Response(page)

    @extend_schema(request=DoubtCreateSerializer, responses=DoubtSerializer)
    def post(self, request):
        ser = DoubtCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        bucket = bucket_for(request.member, vd["bucket_id"])
        message = None
        if vd.get("chat_message_id"):
            message = get_object_or_404(
                ChatMessage, pk=vd["chat_message_id"], session__member=request.member, session__bucket=bucket
            )
        try:
            doubt, created = open_doubt(
                student=request.member,
                bucket=bucket,
                question=vd["question"],
                reason=Doubt.REASON_STUDENT,
                ai_answer=message.content if message else "",
                chat_message=message,
                student_note=vd.get("note") or "",
            )
        except LearningError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(
            DoubtSerializer(doubt).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class DoubtDetailView(APIView):
    permission_classes = [IsSchoolMember]

    @extend_schema(responses=DoubtSerializer)
    def get(self, request, pk):
        doubt = _doubt_for(request.member, pk)
        if doubt.student_id == request.member.id and doubt.answered_at and not doubt.student_seen_at:
            doubt.student_seen_at = timezone.now()
            doubt.save(update_fields=["student_seen_at"])
        return Response(DoubtSerializer(doubt).data)


class DoubtAnswerView(APIView):
    """POST {answer, add_to_notes} — teacher reply; optionally index it as notes."""

    permission_classes = [IsStaffMember]

    @extend_schema(request=DoubtAnswerSerializer, responses=DoubtSerializer)
    def post(self, request, pk):
        doubt = _doubt_for(request.member, pk)
        ser = DoubtAnswerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            doubt = answer_doubt(
                doubt,
                request.member,
                answer=ser.validated_data["answer"],
                add_to_notes=ser.validated_data["add_to_notes"],
            )
        except LearningError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(DoubtSerializer(doubt).data)


class DoubtCloseView(APIView):
    permission_classes = [IsSchoolMember]

    @extend_schema(responses=DoubtSerializer)
    def post(self, request, pk):
        doubt = _doubt_for(request.member, pk)
        doubt.status = Doubt.STATUS_CLOSED
        doubt.save(update_fields=["status"])
        return Response(DoubtSerializer(doubt).data)


# ---------------------------------------------------------------------------
# Answer feedback
# ---------------------------------------------------------------------------


class FeedbackView(APIView):
    """POST {message_id, rating 1|-1, reason, comment, ask_teacher} — rate an AI answer."""

    permission_classes = [IsSchoolMember]

    @extend_schema(request=FeedbackSerializer)
    def post(self, request):
        ser = FeedbackSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        message = get_object_or_404(
            ChatMessage.objects.select_related("session__bucket"),
            pk=vd["message_id"],
            role=ChatMessage.ROLE_ASSISTANT,
            session__member=request.member,
        )
        bucket = message.session.bucket
        fb, _ = ChatFeedback.objects.update_or_create(
            message=message,
            member=request.member,
            defaults={
                "school": request.member.school,
                "bucket": bucket,
                "rating": vd["rating"],
                "reason": vd.get("reason") or "",
                "comment": vd.get("comment") or "",
                "top_score": top_source_score(message),
            },
        )
        doubt_id = None
        if vd["rating"] == ChatFeedback.RATING_DOWN and vd.get("ask_teacher"):
            from .services.content import preceding_question

            doubt, _ = open_doubt(
                student=request.member,
                bucket=bucket,
                question=preceding_question(message) or message.content[:500],
                reason=Doubt.REASON_LOW_RATING,
                ai_answer=message.content,
                chat_message=message,
                student_note=vd.get("comment") or "",
            )
            doubt_id = doubt.id
        return Response({"id": fb.id, "rating": fb.rating, "reason": fb.reason, "doubt_id": doubt_id})


class FeedbackSummaryView(APIView):
    """GET ?bucket_id&days — helpful rate, reasons, low-rated answers, score tuning hint."""

    permission_classes = [IsStaffMember]

    @extend_schema(parameters=[OpenApiParameter("bucket_id", int), OpenApiParameter("days", int)])
    def get(self, request):
        bucket_id = request.query_params.get("bucket_id")
        if bucket_id:
            bucket_for(request.member, bucket_id)
        elif not request.member.is_manager_or_above:
            return Response({"detail": "bucket_id is required."}, status=400)
        try:
            days = max(1, min(365, int(request.query_params.get("days", 30))))
        except ValueError:
            days = 30
        return Response(feedback_summary(request.member.school, bucket_id=bucket_id, days=days))
