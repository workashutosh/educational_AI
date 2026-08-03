from rest_framework import serializers


class CreateLectureSerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=4000
    )
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    # When True (default), create a Teams meeting via Graph if configured.
    create_teams_meeting = serializers.BooleanField(required=False, default=True)
    # Optional manual join URL when Teams Graph is not used / unavailable.
    teams_join_url = serializers.URLField(
        required=False, allow_blank=True, default="", max_length=1000
    )

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError("ends_at must be after starts_at.")
        return attrs


class UpdateLectureSerializer(serializers.Serializer):
    title = serializers.CharField(required=False, max_length=255)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=4000
    )
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    status = serializers.ChoiceField(
        choices=["scheduled", "live", "ended", "cancelled"],
        required=False,
    )
    teams_join_url = serializers.URLField(
        required=False, allow_blank=True, max_length=1000
    )
