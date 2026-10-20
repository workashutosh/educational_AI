"""
Topic tagging without an LLM: embed the question, find the closest note
chunk, and use its chapter heading as the topic. Same local embeddings as
retrieval, so tagging costs nothing per question.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from ingestion.models import Chunk, Document, SubjectBucket
from ingestion.services.retrieval_service import search_bucket

from ..models import Topic

logger = logging.getLogger(__name__)

_NOISE = re.compile(
    r"^(contents|preface|foreword|index|answers?|exercises?|appendix|references|"
    r"bibliography|acknowledg\w*|summary|miscellaneous\b.*|examples?\b.*|"
    r"solutions?\b.*|notes?|activity\b.*|figure\b.*|table\b.*|points? to remember|historical note|"
    r"page \d+|\(root\)|untitled)\b",
    re.I,
)
MAX_AUTO_TOPICS = 60
MIN_TAG_SCORE = 0.25


_FRONT_MATTER = re.compile(r"\b(preface|contents|foreword|acknowledg\w*|textbook for)\b", re.I)
_SECTION = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(.+)$")
_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


def clean_topic_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "")).strip(" #*-:.\t")
    name = re.sub(r"^(chapter|unit)\s+\d+\s*[:.\-–]\s*", "", name, flags=re.I)
    match = _SECTION.match(name)
    if match:  # "5.3.  Differentiability" → "5.3 Differentiability"
        name = f"{match.group(1)} {match.group(2).strip()}"
    if name.isupper() and len(name) > 3:  # "MATRICES" → "Matrices"
        words = name.lower().split()
        name = " ".join(
            w if (i and w in _SMALL_WORDS) else w.capitalize() for i, w in enumerate(words)
        )
    return name[:200]


def _usable(name: str) -> bool:
    return bool(name) and len(name) >= 3 and not _NOISE.match(name) and not name.isdigit()


def topic_name_from_heading(heading_path: list[str] | None) -> str:
    """
    Topic for a chunk: its numbered section ("6.4 Maxima and Minima") when there
    is one, else its chapter. Introductions, exercises, and summaries fold into
    the chapter; front matter (preface, contents) gets no topic.
    """
    raw = [p for p in heading_path or [] if p]
    if any(_FRONT_MATTER.search(p) for p in raw):
        return ""
    names = [clean_topic_name(p) for p in raw]
    sections = []
    for n in names:
        match = _SECTION.match(n)
        if match and _usable(match.group(2)) and not re.match(r"introduction\b", match.group(2), re.I):
            sections.append((match.group(1).count("."), n))
    if sections:
        return min(sections)[1]  # shallowest numbered section
    chapters = [n for n in names if _usable(n) and not _SECTION.match(n)]
    return chapters[0] if chapters else ""


def get_or_create_topic(bucket: SubjectBucket, name: str, *, source=Topic.SOURCE_AUTO) -> Topic:
    topic = Topic.objects.filter(bucket=bucket, name__iexact=name).first()
    if topic:
        return topic
    return Topic.objects.create(
        school_id=bucket.school_id,
        bucket=bucket,
        name=name,
        source=source,
        order=Topic.objects.filter(bucket=bucket).count(),
    )


def suggest_topic(bucket: SubjectBucket, text: str) -> Topic | None:
    """Best-matching topic for a question, creating it from the notes if new."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        hits = search_bucket(
            bucket.id,
            query=text[:1000],
            top_k=3,
            kinds=[Document.KIND_NOTES],
            min_score=0,
            expand_neighbors=False,
        )
    except Exception:
        logger.exception("topic tagging search failed bucket=%s", bucket.id)
        return None
    for hit in hits:
        if hit.score < MIN_TAG_SCORE:
            break
        name = topic_name_from_heading(hit.heading_path)
        if name:
            return get_or_create_topic(bucket, name)
    return None


def sync_topics_from_notes(bucket: SubjectBucket) -> list[Topic]:
    """Create topics from the most common chapter headings in indexed notes."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    labels: dict[str, str] = {}
    rows = Chunk.objects.filter(
        bucket=bucket,
        document__kind=Document.KIND_NOTES,
        document__status=Document.STATUS_INDEXED,
        document__deleted_at__isnull=True,
    ).values_list("heading_path", flat=True)
    for i, path in enumerate(rows):
        name = topic_name_from_heading(path)
        if not name:
            continue
        key = name.lower()
        counts[key] += 1
        first_seen.setdefault(key, i)
        labels.setdefault(key, name)

    created: list[Topic] = []
    # Keep frequent headings, in the order they appear in the notes.
    keep = [k for k, _ in counts.most_common(MAX_AUTO_TOPICS)]
    keep.sort(key=lambda k: first_seen[k])
    for key in keep:
        if Topic.objects.filter(bucket=bucket, name__iexact=labels[key]).exists():
            continue
        created.append(get_or_create_topic(bucket, labels[key]))
    return created
