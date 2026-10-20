"""API-wide conventions shared by web and mobile clients."""
from __future__ import annotations

from rest_framework.views import exception_handler as drf_exception_handler


def _first_message(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        return _first_message(data[0])
    if isinstance(data, dict) and data:
        key, value = next(iter(data.items()))
        msg = _first_message(value)
        return msg if key in ("non_field_errors", "detail") else f"{key}: {msg}"
    return "Invalid request."


def exception_handler(exc, context):
    """
    Keep DRF's payload but guarantee a human-readable `detail`, and nest field
    errors under `errors` so clients can show one message or per-field hints.
    """
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    data = response.data
    if isinstance(data, dict) and "detail" not in data:
        response.data = {"detail": _first_message(data), "errors": data, **data}
    elif isinstance(data, list):
        response.data = {"detail": _first_message(data), "errors": {"non_field_errors": data}}
    return response


def drop_versioned_duplicates(endpoints, **kwargs):
    """drf-spectacular hook: document /api/… once; /api/v1/… is an identical mirror."""
    return [e for e in endpoints if not e[0].startswith("/api/v1/")]
