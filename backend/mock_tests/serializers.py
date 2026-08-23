from rest_framework import serializers


class GenerateMockTestSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    prompt = serializers.CharField(max_length=2000)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    duration_minutes = serializers.IntegerField(required=False, default=60, min_value=5, max_value=300)
    count_mcq = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    count_multi = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    count_brief = serializers.IntegerField(required=False, default=0, min_value=0, max_value=40)
    marks_mcq = serializers.IntegerField(required=False, default=1, min_value=1, max_value=100)
    marks_multi = serializers.IntegerField(required=False, default=2, min_value=1, max_value=100)
    marks_brief = serializers.IntegerField(required=False, default=5, min_value=1, max_value=100)
    results_mode = serializers.ChoiceField(
        choices=["immediate", "after_review"],
        required=False,
        default="after_review",
    )
    source_mode = serializers.ChoiceField(
        choices=["notes", "question_papers", "both"],
        required=False,
        default="notes",
    )
    reference_document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
        default=list,
    )

    # Back-compat: old clients sending question_count → treat as all MCQ
    question_count = serializers.IntegerField(required=False, min_value=1, max_value=40)

    def validate(self, attrs):
        if attrs.get("question_count") and not (
            attrs.get("count_mcq") or attrs.get("count_multi") or attrs.get("count_brief")
        ):
            attrs["count_mcq"] = attrs["question_count"]
            attrs.setdefault("count_multi", 0)
            attrs.setdefault("count_brief", 0)
        total = (
            attrs.get("count_mcq", 0)
            + attrs.get("count_multi", 0)
            + attrs.get("count_brief", 0)
        )
        if total < 1:
            raise serializers.ValidationError("Add at least one question to the blueprint.")
        if total > 40:
            raise serializers.ValidationError("Total questions cannot exceed 40.")
        return attrs


class MockTestUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    topic_prompt = serializers.CharField(max_length=2000, required=False)
    duration_minutes = serializers.IntegerField(required=False, min_value=5, max_value=300)
    count_mcq = serializers.IntegerField(required=False, min_value=0, max_value=40)
    count_multi = serializers.IntegerField(required=False, min_value=0, max_value=40)
    count_brief = serializers.IntegerField(required=False, min_value=0, max_value=40)
    marks_mcq = serializers.IntegerField(required=False, min_value=1, max_value=100)
    marks_multi = serializers.IntegerField(required=False, min_value=1, max_value=100)
    marks_brief = serializers.IntegerField(required=False, min_value=1, max_value=100)
    results_mode = serializers.ChoiceField(
        choices=["immediate", "after_review"],
        required=False,
    )
    source_mode = serializers.ChoiceField(
        choices=["notes", "question_papers", "both"],
        required=False,
    )
    reference_document_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs):
        # If any count is present, ensure we can compute a valid total against
        # existing values at the view layer; here only check provided totals.
        counts = [attrs.get("count_mcq"), attrs.get("count_multi"), attrs.get("count_brief")]
        if any(c is not None for c in counts) and all(c is not None for c in counts):
            total = sum(counts)
            if total < 1:
                raise serializers.ValidationError("Add at least one question to the blueprint.")
            if total > 40:
                raise serializers.ValidationError("Total questions cannot exceed 40.")
        return attrs


class RegenerateMockTestSerializer(MockTestUpdateSerializer):
    """Optional blueprint overrides before regenerating questions."""

    pass


class ReleaseResultsSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
        max_length=200,
    )


class QuestionUpdateSerializer(serializers.Serializer):
    prompt = serializers.CharField(required=False, allow_blank=False, max_length=4000)
    options = serializers.ListField(
        child=serializers.CharField(max_length=500),
        required=False,
        allow_empty=True,
    )
    correct_indices = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=20),
        required=False,
        allow_empty=True,
    )
    model_answer = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    marks = serializers.IntegerField(required=False, min_value=1, max_value=100)
    order = serializers.IntegerField(required=False, min_value=1)


class AssignStudentsSerializer(serializers.Serializer):
    student_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        max_length=200,
    )
    # When true (default), publish a draft after assigning so students can see it.
    publish = serializers.BooleanField(required=False, default=True)


class SubmitAnswersSerializer(serializers.Serializer):
    answers = serializers.DictField(allow_empty=True)
    auto = serializers.BooleanField(required=False, default=False)


class ConfirmBriefGradeSerializer(serializers.Serializer):
    score = serializers.FloatField(min_value=0)
    feedback = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
