"""Proactive chat follow-up suggestions from retrieved sources."""
from __future__ import annotations

from engagement.models import SubjectMastery


def build_chat_suggestions(
    *,
    sources: list,
    bucket,
    member=None,
    limit: int = 3,
) -> list[str]:
    suggestions: list[str] = []
    seen: set[str] = set()

    for s in sources or []:
        path = getattr(s, "heading_path", None)
        if isinstance(path, list):
            label = " › ".join(str(p) for p in path if p)[-120:]
        elif isinstance(path, str):
            label = path.strip()[-120:]
        else:
            label = ""
        if not label:
            # Fall back to filename + page
            fn = getattr(s, "document_filename", "") or ""
            page = getattr(s, "page_start", None)
            if fn and page:
                label = f"{fn} (page {page})"
            elif fn:
                label = fn
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(f"Explain more about {label}")
        if len(suggestions) >= limit:
            break

    if member and len(suggestions) < limit:
        weak = (
            SubjectMastery.objects.filter(member=member, bucket=bucket, score_0_100__lt=60)
            .select_related("bucket")
            .first()
        )
        if weak and weak.bucket_id == bucket.id:
            tip = f"What should I revise in {bucket.name}?"
            if tip.lower() not in seen:
                suggestions.append(tip)

    if not suggestions:
        suggestions = [
            f"Summarize the key ideas in {bucket.name}",
            "Give me a short example from the notes",
            "What should I practice next?",
        ]
    return suggestions[:limit]
