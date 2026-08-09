"""
Structure-aware chunking — hierarchical, page-anchored, deterministic.

Walks parsed markdown (headings + <!--PAGE:N--> + semantic Example/Solution
markers) and emits chunks that:
  - never straddle a markdown heading boundary (unless the section is huge)
  - prefer cuts at Example / Solution / Exercise / Theorem boundaries
  - carry heading_path + page_start/page_end for citations
  - use overlapping windows so a cut never orphans the second half of a unit
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PAGE_MARKER_RE = re.compile(r"^<!--PAGE:(\d+)-->$")

# Soft section boundaries inside a heading section (NCERT / textbook style)
_SEMANTIC_BOUNDARY_RE = re.compile(
    r"^(?:"
    r"Example\s+\d+[.:)]?|"
    r"EXERCISE\s+\d+(?:\.\d+)?|"
    r"Exercise\s+\d+(?:\.\d+)?|"
    r"Solution\s*:?|"
    r"SOLUTION\s*:?|"
    r"Theorem\s+\d+(?:\.\d+)?|"
    r"Proof\s*:?|"
    r"Remark\s*:?|"
    r"Note\s*:?"
    r")\b",
    re.IGNORECASE,
)

DEFAULT_MAX_CHARS = 3200
DEFAULT_OVERLAP_CHARS = 640  # was 320 — keep more of unit across window cuts
DEFAULT_MIN_CHARS = 200


@dataclass
class ChunkSpan:
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str


def chunk_markdown(
    markdown: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[ChunkSpan]:
    heading_stack: list[tuple[int, str]] = []
    buffer: list[tuple[str, int | None]] = []
    current_page: int | None = None
    chunks: list[ChunkSpan] = []

    def heading_path() -> list[str]:
        return [title for _, title in heading_stack]

    def flush() -> None:
        if not buffer:
            return
        raw = "\n".join(line for line, _ in buffer)
        if not raw.strip():
            buffer.clear()
            return

        path = heading_path()
        offsets: list[tuple[int, int, int | None]] = []
        pos = 0
        for line, page in buffer:
            offsets.append((pos, pos + len(line), page))
            pos += len(line) + 1

        def page_at(offset: int) -> int | None:
            for start, end, page in offsets:
                if start <= offset <= end:
                    return page
            return offsets[-1][2] if offsets else None

        # Prefer semantic unit splits before fixed windows
        units = _split_semantic_units(raw)
        for unit in units:
            unit = unit.strip()
            if not unit:
                continue
            # Locate unit start in raw for page mapping
            unit_start = raw.find(unit[: min(80, len(unit))])
            if unit_start < 0:
                unit_start = 0

            if len(unit) <= max_chars:
                chunks.append(
                    ChunkSpan(
                        heading_path=path,
                        page_start=page_at(unit_start),
                        page_end=page_at(unit_start + len(unit) - 1),
                        text=unit,
                    )
                )
                continue

            # Long unit: overlapping windows, prefer paragraph / sentence / semantic cuts
            start = 0
            n = len(unit)
            while start < n:
                end = min(start + max_chars, n)
                if end < n:
                    window = unit[start:end]
                    boundary = _best_cut(window, max_chars)
                    if boundary > 0:
                        end = start + boundary
                piece = unit[start:end].strip()
                if piece:
                    abs_start = unit_start + start
                    abs_end = unit_start + max(end - 1, start)
                    chunks.append(
                        ChunkSpan(
                            heading_path=path,
                            page_start=page_at(abs_start),
                            page_end=page_at(abs_end),
                            text=piece,
                        )
                    )
                if end >= n:
                    break
                start = max(end - overlap_chars, start + 1)
        buffer.clear()

    for raw_line in markdown.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        page_match = _PAGE_MARKER_RE.match(stripped)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            continue

        # Soft flush before a new Example/Solution so the prior unit stays whole
        if buffer and _SEMANTIC_BOUNDARY_RE.match(stripped):
            buf_len = sum(len(t) + 1 for t, _ in buffer)
            if buf_len >= min_chars:
                flush()

        buffer.append((line, current_page))
        buffer_len = sum(len(t) + 1 for t, _ in buffer)
        if buffer_len >= max_chars * 1.5:
            flush()

    flush()

    merged = _merge_small_trailing_chunks(chunks, min_chars, max_chars)
    return [c for c in merged if len(c.text.strip()) >= 15]


def _split_semantic_units(raw: str) -> list[str]:
    """Split text on Example/Solution/Exercise lines while keeping the marker."""
    lines = raw.split("\n")
    units: list[str] = []
    cur: list[str] = []
    for line in lines:
        if cur and _SEMANTIC_BOUNDARY_RE.match(line.strip()):
            units.append("\n".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        units.append("\n".join(cur))
    return units or [raw]


def _best_cut(window: str, max_chars: int) -> int:
    """Prefer semantic marker, then blank line, then sentence end."""
    # Look in the second half of the window
    half = int(max_chars * 0.45)
    search = window[half:]
    # Semantic marker near cut
    for m in _SEMANTIC_BOUNDARY_RE.finditer(search):
        # cut just before this marker
        return half + m.start()
    for sep in ("\n\n", ". ", ".\n"):
        idx = search.rfind(sep)
        if idx > 0:
            return half + idx + len(sep)
    return 0


def _merge_small_trailing_chunks(
    chunks: list[ChunkSpan],
    min_chars: int,
    max_chars: int,
) -> list[ChunkSpan]:
    """
    Fold tiny window leftovers into the previous chunk — but never across a
    semantic Example/Solution boundary, and never past max_chars (otherwise
    every stub cascades into one mega-chunk and undoes splitting).
    """
    merged: list[ChunkSpan] = []
    for chunk in chunks:
        starts_unit = bool(_SEMANTIC_BOUNDARY_RE.match(chunk.text.lstrip().split("\n", 1)[0]))
        if (
            merged
            and len(chunk.text) < min_chars
            and not starts_unit
            and merged[-1].heading_path == chunk.heading_path
            and len(merged[-1].text) + len(chunk.text) + 2 <= max_chars
        ):
            prev = merged[-1]
            merged[-1] = ChunkSpan(
                heading_path=prev.heading_path,
                page_start=prev.page_start,
                page_end=chunk.page_end or prev.page_end,
                text=f"{prev.text}\n\n{chunk.text}".strip(),
            )
        else:
            merged.append(chunk)
    return merged
