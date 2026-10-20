from rest_framework import serializers

from .models import ChatFeedback, Doubt, Flashcard, FlashcardDeck


class FlashcardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flashcard
        fields = ("id", "deck", "order", "front", "back", "topic", "source_chunk_id", "created_at")
        read_only_fields = ("id", "deck", "source_chunk_id", "created_at")


class CardInputSerializer(serializers.Serializer):
    front = serializers.CharField(max_length=2000)
    back = serializers.CharField(max_length=4000)
    topic_id = serializers.IntegerField(required=False, allow_null=True)


class DeckSerializer(serializers.ModelSerializer):
    bucket_name = serializers.CharField(source="bucket.name", read_only=True)
    card_count = serializers.IntegerField(read_only=True)
    owner_name = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = FlashcardDeck
        fields = (
            "id",
            "bucket",
            "bucket_name",
            "title",
            "description",
            "topic",
            "source_document",
            "visibility",
            "owner",
            "owner_name",
            "card_count",
            "can_edit",
            "progress",
            "created_at",
            "updated_at",
        )

    def get_owner_name(self, obj) -> str:
        if not obj.owner_id:
            return ""
        user = obj.owner.user
        return user.get_full_name() or user.username

    def get_can_edit(self, obj) -> bool:
        member = self.context.get("member")
        return bool(member and (obj.owner_id == member.id or member.is_manager_or_above))

    def get_progress(self, obj) -> dict | None:
        from .services.srs import deck_progress

        member = self.context.get("member")
        return deck_progress(member, obj) if member else None


class DeckDetailSerializer(DeckSerializer):
    cards = FlashcardSerializer(many=True, read_only=True)

    class Meta(DeckSerializer.Meta):
        fields = DeckSerializer.Meta.fields + ("cards",)


class DeckCreateSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    visibility = serializers.ChoiceField(
        choices=[c[0] for c in FlashcardDeck.VISIBILITY_CHOICES], required=False
    )
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    cards = CardInputSerializer(many=True, required=False, default=list)


class DeckUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    visibility = serializers.ChoiceField(
        choices=[c[0] for c in FlashcardDeck.VISIBILITY_CHOICES], required=False
    )


class DeckGenerateSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    prompt = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    title = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    document_id = serializers.IntegerField(required=False, allow_null=True)
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    count = serializers.IntegerField(default=15, min_value=3, max_value=40)
    visibility = serializers.ChoiceField(
        choices=[c[0] for c in FlashcardDeck.VISIBILITY_CHOICES], required=False
    )


class ReviewSerializer(serializers.Serializer):
    card_id = serializers.IntegerField()
    grade = serializers.IntegerField(required=False, min_value=0, max_value=5)
    button = serializers.ChoiceField(choices=["again", "hard", "good", "easy"], required=False)

    def validate(self, attrs):
        if attrs.get("grade") is None and not attrs.get("button"):
            raise serializers.ValidationError("Send grade (0-5) or button.")
        return attrs


class DoubtSerializer(serializers.ModelSerializer):
    bucket_name = serializers.CharField(source="bucket.name", read_only=True)
    student_name = serializers.SerializerMethodField()
    answered_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Doubt
        fields = (
            "id",
            "bucket",
            "bucket_name",
            "student",
            "student_name",
            "question",
            "student_note",
            "ai_answer",
            "chat_message",
            "session",
            "reason",
            "status",
            "answer",
            "answered_by",
            "answered_by_name",
            "answered_at",
            "published_document",
            "student_seen_at",
            "created_at",
        )

    def get_student_name(self, obj) -> str:
        u = obj.student.user
        return u.get_full_name() or u.username

    def get_answered_by_name(self, obj) -> str:
        if not obj.answered_by_id:
            return ""
        u = obj.answered_by.user
        return u.get_full_name() or u.username


class DoubtCreateSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    question = serializers.CharField(max_length=4000)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    chat_message_id = serializers.IntegerField(required=False, allow_null=True)


class DoubtAnswerSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=8000)
    add_to_notes = serializers.BooleanField(default=False)


class FeedbackSerializer(serializers.Serializer):
    message_id = serializers.IntegerField()
    rating = serializers.ChoiceField(choices=[1, -1])
    reason = serializers.ChoiceField(
        choices=[c[0] for c in ChatFeedback.REASON_CHOICES], required=False, allow_blank=True, default=""
    )
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    ask_teacher = serializers.BooleanField(default=False)
