"""
Microsoft Graph — create Teams online meetings.

Uses application (client credentials) auth:

  POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
  POST https://graph.microsoft.com/v1.0/users/{organizerId}/onlineMeetings

Required Azure setup:
  1. App registration with Application permission OnlineMeetings.ReadWrite.All
     (+ admin consent).
  2. Application access policy granting the app to create meetings for the
     organizer user (Teams PowerShell):
       New-CsApplicationAccessPolicy -Identity EduAI-Lectures -AppIds "<app-id>"
       Grant-CsApplicationAccessPolicy -PolicyName EduAI-Lectures -Identity "<user-oid>"
  3. Env: MS_GRAPH_TENANT_ID, MS_GRAPH_CLIENT_ID, MS_GRAPH_CLIENT_SECRET,
     MS_GRAPH_ORGANIZER_USER_ID (Entra object id or UPN of the teacher/organizer).

Docs:
  https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_GRAPH = "https://graph.microsoft.com/v1.0"

_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}


class TeamsNotConfigured(Exception):
    pass


class TeamsGraphError(Exception):
    pass


@dataclass
class TeamsMeeting:
    meeting_id: str
    join_url: str
    subject: str
    organizer_upn: str
    raw: dict[str, Any]


def teams_configured() -> bool:
    return bool(
        getattr(settings, "MS_GRAPH_TENANT_ID", "")
        and getattr(settings, "MS_GRAPH_CLIENT_ID", "")
        and getattr(settings, "MS_GRAPH_CLIENT_SECRET", "")
        and getattr(settings, "MS_GRAPH_ORGANIZER_USER_ID", "")
    )


def create_teams_online_meeting(
    *,
    subject: str,
    start: datetime,
    end: datetime,
) -> TeamsMeeting:
    if not teams_configured():
        raise TeamsNotConfigured(
            "Microsoft Teams is not configured. Set MS_GRAPH_TENANT_ID, "
            "MS_GRAPH_CLIENT_ID, MS_GRAPH_CLIENT_SECRET, and "
            "MS_GRAPH_ORGANIZER_USER_ID."
        )

    token = _access_token()
    organizer = settings.MS_GRAPH_ORGANIZER_USER_ID
    url = f"{_GRAPH}/users/{organizer}/onlineMeetings"
    body = {
        "subject": subject[:255],
        "startDateTime": _iso_z(start),
        "endDateTime": _iso_z(end),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as exc:
        logger.exception("Graph onlineMeetings request failed")
        raise TeamsGraphError(f"Could not reach Microsoft Graph: {exc}") from exc

    if res.status_code >= 400:
        detail = _error_detail(res)
        logger.error("Graph onlineMeetings error %s: %s", res.status_code, detail)
        raise TeamsGraphError(detail)

    data = res.json()
    join = (data.get("joinWebUrl") or "").strip()
    mid = (data.get("id") or "").strip()
    if not join or not mid:
        raise TeamsGraphError("Graph returned a meeting without joinWebUrl/id.")

    organizer_upn = ""
    parts = data.get("participants") or {}
    org = parts.get("organizer") or {}
    organizer_upn = (org.get("upn") or "").strip()

    return TeamsMeeting(
        meeting_id=mid,
        join_url=join,
        subject=data.get("subject") or subject,
        organizer_upn=organizer_upn,
        raw=data,
    )


def _access_token() -> str:
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    tenant = settings.MS_GRAPH_TENANT_ID
    url = _TOKEN_URL.format(tenant=tenant)
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.MS_GRAPH_CLIENT_ID,
        "client_secret": settings.MS_GRAPH_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, data=data)
    except httpx.HTTPError as exc:
        raise TeamsGraphError(f"Token request failed: {exc}") from exc

    if res.status_code >= 400:
        raise TeamsGraphError(_error_detail(res))

    payload = res.json()
    token = payload.get("access_token") or ""
    expires_in = int(payload.get("expires_in") or 3600)
    if not token:
        raise TeamsGraphError("No access_token in token response.")
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + expires_in
    return token


def _iso_z(dt: datetime) -> str:
    if timezone_is_naive(dt):
        from django.utils import timezone as dj_tz

        dt = dj_tz.make_aware(dt, dj_tz.get_current_timezone())
    return dt.astimezone(__import__("datetime").timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def timezone_is_naive(dt: datetime) -> bool:
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def _error_detail(res: httpx.Response) -> str:
    try:
        data = res.json()
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code") or str(err)
            return f"Microsoft Graph error ({res.status_code}): {msg}"
        return f"Microsoft Graph error ({res.status_code}): {data}"
    except Exception:
        return f"Microsoft Graph error ({res.status_code}): {res.text[:400]}"
