from rest_framework import serializers


class HarnessQuerySerializer(serializers.Serializer):
    bucket_id = serializers.IntegerField()
    query = serializers.CharField(max_length=4000)
