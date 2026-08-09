"""
Microsoft Graph — create Teams online meetings.

Two modes:
  1) Delegated (preferred): teacher connects Microsoft account once, then
     POST /me/onlineMeetings with OnlineMeetings.ReadWrite.
     Does NOT need Teams application access policy.
  2) App-only: client credentials + OnlineMeetings.ReadWrite.All +
     application access policy (needs Microsoft 365 / Teams admin).

Docs:
  https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.core import signing
from django.utils import timezone

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_GRAPH = "https://graph.microsoft.com/v1.0"

_DELEGATED_SCOPES = (
    "openid offline_access User.Read OnlineMeetings.ReadWrite"
)

_token_cache: dict[str, Any] = {"access_token": "", "expires_at": 0.0}

_OAUTH_STATE_SALT = "lectures-ms-oauth"


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
    via: str = "app"  # app | delegated


def oauth_app_ready() -> bool:
    """Client id/secret/tenant enough to run OAuth (organizer user id optional)."""
    return bool(
        getattr(settings, "MS_GRAPH_TENANT_ID", "")
        and getattr(settings, "MS_GRAPH_CLIENT_ID", "")
        and getattr(settings, "MS_GRAPH_CLIENT_SECRET", "")
    )


def teams_configured() -> bool:
    """App-only mode fully configured (includes organizer)."""
    return oauth_app_ready() and bool(
        getattr(settings, "MS_GRAPH_ORGANIZER_USER_ID", "")
    )


def redirect_uri() -> str:
    return (
        getattr(settings, "MS_GRAPH_REDIRECT_URI", "")
        or "http://127.0.0.1:8000/api/lectures/teams/callback/"
    ).rstrip("/") + "/"


def oauth_tenant() -> str:
    # "organizations" lets teachers sign in with any work/school tenant that has Teams.
    return (
        getattr(settings, "MS_GRAPH_OAUTH_TENANT", "")
        or "organizations"
    )


def build_oauth_authorize_url(*, member_id: int) -> str:
    if not oauth_app_ready():
        raise TeamsNotConfigured(
            "Microsoft Teams isn’t available right now. "
            "You can still create a lecture and paste a meeting link."
        )
    state = signing.dumps(
        {"member_id": member_id, "nonce": secrets.token_urlsafe(8)},
        salt=_OAUTH_STATE_SALT,
    )
    params = {
        "client_id": settings.MS_GRAPH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "response_mode": "query",
        "scope": _DELEGATED_SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    return _AUTH_URL.format(tenant=oauth_tenant()) + "?" + urlencode(params)


def parse_oauth_state(state: str) -> int:
    data = signing.loads(state, salt=_OAUTH_STATE_SALT, max_age=600)
    return int(data["member_id"])


def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    if not oauth_app_ready():
        raise TeamsNotConfigured(
            "Microsoft Teams isn’t available right now. Please try again later."
        )
    data = {
        "client_id": settings.MS_GRAPH_CLIENT_ID,
        "client_secret": settings.MS_GRAPH_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "scope": _DELEGATED_SCOPES,
    }
    # Token endpoint: use same tenant authority as authorize when possible
    url = _TOKEN_URL.format(tenant=oauth_tenant())
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.post(url, data=data)
    except httpx.HTTPError as exc:
        raise TeamsGraphError(f"Token exchange failed: {exc}") from exc
    if res.status_code >= 400:
        raise TeamsGraphError(_error_detail(res))
    payload = res.json()
    if not payload.get("access_token"):
        raise TeamsGraphError("No access_token in OAuth response.")
    return payload


def refresh_delegated_tokens(refresh_token: str) -> dict[str, Any]:
    data = {
        "client_id": settings.MS_GRAPH_CLIENT_ID,
        "client_secret": settings.MS_GRAPH_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": _DELEGATED_SCOPES,
    }
    url = _TOKEN_URL.format(tenant=oauth_tenant())
    with httpx.Client(timeout=30.0) as client:
        res = client.post(url, data=data)
    if res.status_code >= 400:
        raise TeamsGraphError(_error_detail(res))
    return res.json()


def fetch_me_profile(access_token: str) -> dict[str, str]:
    with httpx.Client(timeout=20.0) as client:
        res = client.get(
            f"{_GRAPH}/me",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"$select": "id,userPrincipalName,displayName,mail"},
        )
    if res.status_code >= 400:
        raise TeamsGraphError(_error_detail(res))
    data = res.json()
    return {
        "ms_user_id": data.get("id") or "",
        "ms_upn": data.get("userPrincipalName")
        or data.get("mail")
        or "",
        "display_name": data.get("displayName") or "",
    }


def create_teams_online_meeting(
    *,
    subject: str,
    start: datetime,
    end: datetime,
    member=None,
) -> TeamsMeeting:
    """
    Prefer delegated token for ``member`` (no access policy).
    Fall back to app-only if configured.
    """
    if member is not None:
        from .ms_oauth import get_valid_access_token_for_member

        token = get_valid_access_token_for_member(member)
        if token:
            return _create_meeting_with_token(
                token,
                subject=subject,
                start=start,
                end=end,
                url=f"{_GRAPH}/me/onlineMeetings",
                via="delegated",
            )

    if not teams_configured():
        if member is not None:
            raise TeamsNotConfigured(
                "Connect your Microsoft account (with Teams) to create meeting "
                "links from ClassKit, or paste a join URL."
            )
        raise TeamsNotConfigured(
            "Microsoft Teams isn’t available right now. "
            "Connect Microsoft on the Lectures page, or paste a join URL."
        )

    token = _app_access_token()
    organizer = settings.MS_GRAPH_ORGANIZER_USER_ID
    return _create_meeting_with_token(
        token,
        subject=subject,
        start=start,
        end=end,
        url=f"{_GRAPH}/users/{organizer}/onlineMeetings",
        via="app",
    )


def _create_meeting_with_token(
    token: str,
    *,
    subject: str,
    start: datetime,
    end: datetime,
    url: str,
    via: str,
) -> TeamsMeeting:
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
        via=via,
    )


def _app_access_token() -> str:
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
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(__import__("datetime").timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"


def timezone_is_naive(dt: datetime) -> bool:
    return dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None


def token_expiry(expires_in: int) -> datetime:
    return timezone.now() + timedelta(seconds=max(60, int(expires_in) - 60))


def user_facing_teams_error(raw: str) -> str:
    """Map stored/raw Graph failures to short product copy (never expose IDs/codes)."""
    text = (raw or "").strip()
    if not text:
        return ""
    lower = text.lower()
    if "application access policy" in lower:
        return (
            "Couldn’t create a Teams link automatically. "
            "Connect Microsoft on the Lectures page, then try again."
        )
    if "connect your microsoft" in lower or "connect microsoft" in lower:
        return (
            "Connect Microsoft on the Lectures page to create meeting links, "
            "then try again."
        )
    if "not configured" in lower or "ms_graph" in lower or ".env" in lower:
        return (
            "Microsoft Teams isn’t available right now. "
            "You can still create a lecture and paste a meeting link."
        )
    if "graph" in lower or "403" in lower or "401" in lower or "forbidden" in lower:
        return (
            "Couldn’t create a Teams link. Connect Microsoft on the Lectures page "
            "with a work account that has Teams, then try again."
        )
    # Strip anything that looks like a technical dump
    if any(
        token in lower
        for token in (
            "microsoft graph error",
            "status_code",
            "traceback",
            "client_id",
            "aadsts",
            "onlinemeetings",
        )
    ):
        return (
            "Couldn’t create a Teams link. Connect Microsoft on the Lectures page, "
            "then try again."
        )
    # Already short product copy
    if len(text) <= 160 and "http" not in lower and "{" not in text:
        return text
    return (
        "Couldn’t create a Teams link. Connect Microsoft on the Lectures page, "
        "then try again."
    )


def _error_detail(res: httpx.Response) -> str:
    """Log full Graph error; return only user-facing copy for API/UI."""
    raw_body = ""
    msg = ""
    try:
        data = res.json()
        raw_body = str(data)[:800]
        err = data.get("error") or {}
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or err)
        elif isinstance(err, str):
            msg = err
        else:
            msg = raw_body
    except Exception:
        raw_body = (res.text or "")[:800]
        msg = raw_body

    logger.error(
        "Microsoft Graph onlineMeetings failed status=%s body=%s",
        res.status_code,
        raw_body or msg,
    )
    return user_facing_teams_error(msg or f"status {res.status_code}")
