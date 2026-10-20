from rest_framework import serializers

from .models import PaperItem, PaperSection, QuestionItem, QuestionPaper, Topic

QTYPES = [c[0] for c in QuestionItem.TYPE_CHOICES]
DIFFICULTIES = QuestionItem.DIFFICULTIES


class TopicSerializer(serializers.ModelSerializer):
    item_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Topic
        fields = ("id", "bucket", "name", "parent", "order", "source", "item_count", "created_at")
        read_only_fields = ("id", "bucket", "source", "created_at", "item_count")


class TopicCreateSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    name = serializers.CharField(max_length=200)
    parent = serializers.IntegerField(required=False, allow_null=True)


class QuestionItemSerializer(serializers.ModelSerializer):
    topic_name = serializers.SerializerMethodField()
    bucket_name = serializers.CharField(source="bucket.name", read_only=True)

    class Meta:
        model = QuestionItem
        fields = (
            "id",
            "bucket",
            "bucket_name",
            "topic",
            "topic_name",
            "qtype",
            "prompt",
            "options",
            "correct_indices",
            "answer",
            "explanation",
            "marks",
            "difficulty",
            "tags",
            "source",
            "source_ref",
            "source_document",
            "source_year",
            "times_used",
            "last_used_at",
            "is_archived",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "bucket",
            "bucket_name",
            "topic_name",
            "source",
            "source_ref",
            "source_document",
            "times_used",
            "last_used_at",
            "created_at",
            "updated_at",
        )

    def get_topic_name(self, obj) -> str | None:
        return obj.topic.name if obj.topic_id else None


class QuestionItemWriteSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField(required=False)
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    qtype = serializers.ChoiceField(choices=QTYPES, required=False)
    prompt = serializers.CharField(max_length=6000, required=False)
    options = serializers.ListField(child=serializers.CharField(max_length=1000), required=False)
    correct_indices = serializers.ListField(child=serializers.IntegerField(min_value=0), required=False)
    answer = serializers.CharField(required=False, allow_blank=True, max_length=6000)
    explanation = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    marks = serializers.IntegerField(required=False, min_value=1, max_value=100)
    difficulty = serializers.ChoiceField(choices=DIFFICULTIES, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=50), required=False)
    source_year = serializers.IntegerField(required=False, allow_null=True, min_value=1980, max_value=2100)
    is_archived = serializers.BooleanField(required=False)


class CountsSerializer(serializers.Serializer):
    mcq = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    multi = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    brief = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    long = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    numeric = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)


class GenerateItemsSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    prompt = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    topic_id = serializers.IntegerField(required=False, allow_null=True)
    difficulty = serializers.ChoiceField(choices=DIFFICULTIES, default="medium")
    counts = CountsSerializer()
    use_past_papers = serializers.BooleanField(default=False)


class ImportMockSerializer(serializers.Serializer):
    mock_test_id = serializers.IntegerField()


class ImportDocumentSerializer(serializers.Serializer):
    document_id = serializers.IntegerField()


class DifficultyMixSerializer(serializers.Serializer):
    easy = serializers.IntegerField(required=False, min_value=0, max_value=100)
    medium = serializers.IntegerField(required=False, min_value=0, max_value=100)
    hard = serializers.IntegerField(required=False, min_value=0, max_value=100)


class BuildMockTestSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    duration_minutes = serializers.IntegerField(default=30, min_value=5, max_value=300)
    counts = CountsSerializer(required=False)
    marks = CountsSerializer(required=False)
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    item_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    difficulty_mix = DifficultyMixSerializer(required=False)
    results_mode = serializers.ChoiceField(
        choices=["immediate", "after_review"], default="immediate"
    )
    assign_student_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    publish = serializers.BooleanField(default=False)


class PaperSectionSpecSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    qtype = serializers.ChoiceField(choices=QTYPES)
    count = serializers.IntegerField(min_value=1, max_value=60)
    marks_each = serializers.IntegerField(min_value=1, max_value=100, default=1)


class CreatePaperSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=255)
    exam_name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    class_label = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    duration_minutes = serializers.IntegerField(default=180, min_value=10, max_value=600)
    source_mode = serializers.ChoiceField(
        choices=[c[0] for c in QuestionPaper.MODE_CHOICES], default=QuestionPaper.MODE_BANK_THEN_AI
    )
    difficulty_mix = DifficultyMixSerializer(required=False)
    topic_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    sections = PaperSectionSpecSerializer(many=True)


class UpdatePaperSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    exam_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    class_label = serializers.CharField(max_length=100, required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    duration_minutes = serializers.IntegerField(required=False, min_value=10, max_value=600)
    status = serializers.ChoiceField(choices=["draft", "final"], required=False)


class UpdatePaperItemSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, max_length=6000)
    options = serializers.ListField(child=serializers.CharField(max_length=1000), required=False)
    correct_indices = serializers.ListField(child=serializers.IntegerField(min_value=0), required=False)
    answer = serializers.CharField(required=False, allow_blank=True, max_length=6000)
    explanation = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    marks = serializers.IntegerField(required=False, min_value=1, max_value=100)
    order = serializers.IntegerField(required=False, min_value=0)


class PaperItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaperItem
        fields = (
            "id",
            "order",
            "question",
            "qtype",
            "prompt",
            "options",
            "correct_indices",
            "answer",
            "explanation",
            "marks",
            "difficulty",
            "topic_name",
        )


class PaperSectionSerializer(serializers.ModelSerializer):
    items = PaperItemSerializer(many=True, read_only=True)
    total_marks = serializers.SerializerMethodField()

    class Meta:
        model = PaperSection
        fields = (
            "id",
            "order",
            "title",
            "instructions",
            "qtype",
            "marks_each",
            "requested_count",
            "total_marks",
            "items",
        )

    def get_total_marks(self, obj) -> int:
        return sum(i.marks for i in obj.items.all())


class QuestionPaperSerializer(serializers.ModelSerializer):
    sections = PaperSectionSerializer(many=True, read_only=True)
    bucket_name = serializers.CharField(source="bucket.name", read_only=True)
    total_marks = serializers.SerializerMethodField()
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = QuestionPaper
        fields = (
            "id",
            "bucket",
            "bucket_name",
            "title",
            "exam_name",
            "class_label",
            "instructions",
            "duration_minutes",
            "status",
            "source_mode",
            "difficulty_mix",
            "topic_ids",
            "generation_notes",
            "total_marks",
            "question_count",
            "created_by",
            "created_at",
            "updated_at",
            "sections",
        )

    def get_total_marks(self, obj) -> int:
        return sum(i.marks for s in obj.sections.all() for i in s.items.all())

    def get_question_count(self, obj) -> int:
        return sum(len(s.items.all()) for s in obj.sections.all())


class QuestionPaperListSerializer(QuestionPaperSerializer):
    class Meta(QuestionPaperSerializer.Meta):
        fields = tuple(f for f in QuestionPaperSerializer.Meta.fields if f != "sections")
