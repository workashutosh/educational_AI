"""Open a usage-metering scope per request (member is bound during auth)."""
from __future__ import annotations

from .services.usage import usage_scope


def _feature_from_path(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        parts = parts[1:]
    if parts and parts[0] == "v1":
        parts = parts[1:]
    return (parts[0] if parts else "web")[:64]


class UsageScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with usage_scope(feature=_feature_from_path(request.path)):
            return self.get_response(request)
