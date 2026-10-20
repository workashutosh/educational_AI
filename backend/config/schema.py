"""
OpenAPI generation tuned for client codegen (mobile apps).

- operationId = <ViewName><Method>, e.g. assignmentDetailGet / paperExportGet:
  unique per endpoint and stable across URL changes.
- Plain APIViews without a serializer are documented as JSON objects instead
  of producing "unable to guess serializer" errors.
"""
from __future__ import annotations

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.types import OpenApiTypes


class ClassKitAutoSchema(AutoSchema):
    def get_operation_id(self):
        name = self.view.__class__.__name__
        if name.endswith("View"):
            name = name[: -len("View")]
        return f"{name[:1].lower()}{name[1:]}{self.method.capitalize()}"

    def _has_serializer(self) -> bool:
        view = self.view
        return bool(getattr(view, "serializer_class", None) or hasattr(view, "get_serializer_class"))

    def get_request_serializer(self):
        if self._has_serializer():
            return super().get_request_serializer()
        if self.method in ("POST", "PUT", "PATCH"):
            return OpenApiTypes.OBJECT
        return None

    def get_response_serializers(self):
        if self._has_serializer():
            return super().get_response_serializers()
        if self.method == "DELETE":
            return {204: None}
        return OpenApiTypes.OBJECT
