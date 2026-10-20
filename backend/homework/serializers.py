from rest_framework import serializers

from .models import Assignment


class AssignmentWriteSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField(required=False)
    title = serializers.CharField(max_length=255, required=False)
    instructions = serializers.CharField(required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    max_marks = serializers.IntegerField(required=False, min_value=1, max_value=1000)
    rubric = serializers.CharField(required=False, allow_blank=True)
    model_answer = serializers.CharField(required=False, allow_blank=True)
    allow_late = serializers.BooleanField(required=False)
    ai_grading = serializers.BooleanField(required=False)
    results_mode = serializers.ChoiceField(choices=[c[0] for c in Assignment.RESULTS_CHOICES], required=False)
    student_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    assign_all = serializers.BooleanField(required=False, default=False)
    publish = serializers.BooleanField(required=False, default=False)


class AssignSerializer(serializers.Serializer):
    student_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    assign_all = serializers.BooleanField(default=False)


class GradeSerializer(serializers.Serializer):
    score = serializers.FloatField(min_value=0)
    feedback = serializers.CharField(required=False, allow_blank=True, default="")
    release = serializers.BooleanField(default=True)
