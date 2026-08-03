"""
Test / proof endpoint for the RAG harness.

POST /api/harness/query/  {bucket_id, query}
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ingestion.permissions import IsSchoolMember, get_membership

from .agent import run_query
from .exceptions import HarnessLLMError
from .serializers import HarnessQuerySerializer


class HarnessQueryView(APIView):
    """
    Permissioned RAG query via ``rag_harness.agent.run_query``.

    Proves retrieval + access checks end-to-end. Generation agents should
    call ``run_query`` directly rather than this view.
    """

    permission_classes = [IsSchoolMember]

    def post(self, request):
        serializer = HarnessQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        teacher = getattr(request, "teacher", None) or getattr(
            request, "member", None
        ) or get_membership(request.user)

        try:
            result = run_query(
                teacher,
                bucket_id=serializer.validated_data["bucket_id"],
                query=serializer.validated_data["query"],
            )
        except PermissionDenied as exc:
            return Response(
                {"detail": str(exc) or "Forbidden"},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except HarnessLLMError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "answer": result["answer"],
                "sources": result.get("sources") or [],
            }
        )
