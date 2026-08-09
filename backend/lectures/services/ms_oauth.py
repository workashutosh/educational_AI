"""Persist delegated Microsoft tokens per school member."""
from __future__ import annotations

from django.utils import timezone

from lectures.models import MicrosoftAccountLink
from lectures.services.teams_graph import (
    TeamsGraphError,
    fetch_me_profile,
    refresh_delegated_tokens,
    token_expiry,
)


def member_teams_connected(member) -> bool:
    return MicrosoftAccountLink.objects.filter(
        member=member, refresh_token__gt=""
    ).exists()


def save_oauth_tokens(member, token_payload: dict) -> MicrosoftAccountLink:
    access = token_payload.get("access_token") or ""
    refresh = token_payload.get("refresh_token") or ""
    expires_in = int(token_payload.get("expires_in") or 3600)
    profile = fetch_me_profile(access) if access else {}

    link, _ = MicrosoftAccountLink.objects.update_or_create(
        member=member,
        defaults={
            "access_token": access,
            "refresh_token": refresh or "",
            "expires_at": token_expiry(expires_in),
            "ms_user_id": profile.get("ms_user_id") or "",
            "ms_upn": profile.get("ms_upn") or "",
            "display_name": profile.get("display_name") or "",
        },
    )
    # Keep prior refresh if new response omitted it
    if not refresh and link.refresh_token:
        pass
    elif refresh:
        link.refresh_token = refresh
        link.save(update_fields=["refresh_token", "updated_at"])
    return link


def get_valid_access_token_for_member(member) -> str | None:
    try:
        link = MicrosoftAccountLink.objects.get(member=member)
    except MicrosoftAccountLink.DoesNotExist:
        return None
    if not link.access_token and not link.refresh_token:
        return None
    if link.expires_at and link.expires_at > timezone.now() and link.access_token:
        return link.access_token
    if not link.refresh_token:
        return None
    try:
        payload = refresh_delegated_tokens(link.refresh_token)
    except TeamsGraphError:
        return None
    access = payload.get("access_token") or ""
    if not access:
        return None
    link.access_token = access
    if payload.get("refresh_token"):
        link.refresh_token = payload["refresh_token"]
    link.expires_at = token_expiry(int(payload.get("expires_in") or 3600))
    link.save(
        update_fields=["access_token", "refresh_token", "expires_at", "updated_at"]
    )
    return access


def disconnect_member(member) -> None:
    MicrosoftAccountLink.objects.filter(member=member).delete()
