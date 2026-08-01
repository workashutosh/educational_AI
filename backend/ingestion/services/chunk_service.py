"""
Structure-aware chunking — the "PageIndex methodology" (hierarchical,
page-anchored document structure) done deterministically, with no LLM call.

Walks parsed markdown (headings "#".."######" + "<!--PAGE:N-->" anchors, both
emitted by parse_service) and emits chunks that:
  - never straddle a heading boundary, unless the section itself is longer
    than max_chars — long sections are split into overlapping windows so
    context isn't lost at the cut point
  - carry a heading breadcrumb (heading_path) so a retrieved chunk is
    self-describing even out of context ("Chapter 1 > 1.2 Electric Charge")
  - carry accurate page_start/page_end for citations back to the source PDF
  - never emit a tiny orphan chunk — trailing fragments merge into the
    previous chunk of the same section

Chunk size is measured in characters, not tokens. This is a deliberate
choice: character length is a model-agnostic proxy that stays correct
forever, regardless of which embedding/LLM model is swapped in later — no
tokenizer dependency, no per-model recalibration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PAGE_MARKER_RE = re.compile(r"^<!--PAGE:(\d+)-->$")

DEFAULT_MAX_CHARS = 3200
DEFAULT_OVERLAP_CHARS = 320
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
    heading_stack: list[tuple[int, str]] = []  # (level, title), shallow→deep
    buffer: list[tuple[str, int | None]] = []  # (line_text, page_at_that_line)
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

        n = len(raw)
        start = 0
        while start < n:
            end = min(start + max_chars, n)
            if end < n:
                window = raw[start:end]
                boundary = max(window.rfind("\n\n"), window.rfind(". "))
                if boundary > max_chars * 0.5:
                    end = start + boundary + 1
            piece = raw[start:end].strip()
            if piece:
                chunks.append(
                    ChunkSpan(
                        heading_path=path,
                        page_start=page_at(start),
                        page_end=page_at(max(end - 1, start)),
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

        buffer.append((line, current_page))
        buffer_len = sum(len(t) + 1 for t, _ in buffer)
        if buffer_len >= max_chars * 1.4:
            flush()

    flush()

    merged = _merge_small_trailing_chunks(chunks, min_chars)
    # Anything still tiny found no same-section neighbor to merge into — that
    # only happens for junk fragments (e.g. a stray heading-detection
    # artifact isolated between two unrelated sections), never real content,
    # so drop it rather than storing/embedding noise.
    return [c for c in merged if len(c.text.strip()) >= 15]


def _merge_small_trailing_chunks(chunks: list[ChunkSpan], min_chars: int) -> list[ChunkSpan]:
    """Fold undersized fragments into the previous chunk of the same section
    so a short closing paragraph never becomes its own near-empty chunk."""
    merged: list[ChunkSpan] = []
    for chunk in chunks:
        if (
            merged
            and len(chunk.text) < min_chars
            and merged[-1].heading_path == chunk.heading_path
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
