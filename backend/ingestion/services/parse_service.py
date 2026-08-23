"""
Document parsing → structure-annotated markdown + page count.

Output contract (consumed by chunk_service.chunk_markdown):
  - Heading lines use standard markdown ATX syntax: "#".."######"
  - Page/slide boundaries are marked with a sentinel line: "<!--PAGE:N-->"
  - Everything else is body text, grouped into paragraphs

Native text extract for digital PDFs (PyMuPDF) infers heading levels from
this specific document's own font-size distribution — no hardcoded
thresholds, so it adapts to any style/size/layout. DOCX/PPTX use their
native heading/title structures. Scanned PDFs/images fall back to the
hosted PaddleOCR-VL API (AI Studio), which already returns leveled markdown.
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
PPTX_EXTS = {".pptx"}
TEXT_EXTS = {".md", ".markdown", ".txt"}

# If average extracted chars/page is below this, treat PDF as scanned → OCR.
_MIN_CHARS_PER_PAGE = 40

# Heading-candidate filters — kept generous since real headings vary a lot in
# length/punctuation across document styles; these mainly reject page-number
# artifacts and long sentences that merely happen to render in a larger font.
_MAX_HEADING_CHARS = 160
_MAX_HEADING_LEVEL = 6  # markdown ATX max ("######")

# Math-heavy PDFs (LaTeX-compiled textbooks especially) render pieces of
# equations — large brace/bracket continuations above all — using
# font-specific Private Use Area glyphs that carry no portable meaning.
# Strip them; they're never legitimate content in any well-formed document.
_PUA_RE = re.compile("[\uE000-\uF8FF]")

# Running headers/footers are near-always full words/phrases (book title,
# chapter name) — never this short. Keeping the floor here well above 1-2
# chars is what protects legitimate, frequently-recurring short math tokens
# ("sin", "cos", "lim", "dx") from being misclassified as boilerplate.
_MIN_BOILERPLATE_CHARS = 8


@dataclass
class ParseResult:
    markdown: str
    page_count: int | None
    output_path: Path


def parse_document(
    source_path: str | Path,
    output_dir: str | Path,
    on_progress: ProgressCallback | None = None,
) -> ParseResult:
    """
    Parse a PDF/DOCX/PPTX/image/text file into structure-annotated markdown
    and write it to output_dir.
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    ext = source_path.suffix.lower()

    if ext in PDF_EXTS:
        markdown, page_count = _parse_pdf(source_path, on_progress=on_progress)
    elif ext in IMAGE_EXTS:
        if on_progress:
            on_progress("1/1 pages")
        markdown, page_count = _parse_image(source_path), 1
    elif ext in DOCX_EXTS:
        if on_progress:
            on_progress("Reading document…")
        markdown, page_count = _parse_docx(source_path), None
    elif ext in PPTX_EXTS:
        if on_progress:
            on_progress("Reading slides…")
        markdown, page_count = _parse_pptx(source_path)
    elif ext in TEXT_EXTS:
        if on_progress:
            on_progress("Reading text…")
        markdown, page_count = source_path.read_text(encoding="utf-8", errors="replace"), None
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            "Supported: PDF, DOCX, PPTX, PNG/JPG/TIFF/BMP/WEBP, MD/TXT."
        )

    markdown = _normalize_markdown(markdown)
    if not markdown.strip():
        raise ValueError("Parser produced empty output for this file")

    out_path = output_dir / f"{source_path.stem}.md"
    out_path.write_text(markdown, encoding="utf-8")
    logger.info("Parsed %s → %s (pages=%s)", source_path.name, out_path.name, page_count)
    return ParseResult(markdown=markdown, page_count=page_count, output_path=out_path)


# --- PDF -----------------------------------------------------------------------


@dataclass
class _Segment:
    text: str
    size: float
    bold: bool
    continues_line: bool = False  # size-change continuation of the previous
    # segment's own physical PDF text line (not a new line/paragraph) — lets
    # us recognize "numeral/drop-cap run, then bold title text" as one heading
    # even though the two runs differ in size.
    is_table: bool = False  # multi-line markdown table; keep newlines intact
    y0: float = 0.0  # top of bbox for reading-order merge with tables


def _extract_page_segments(page) -> list[_Segment]:
    """
    Reading-order text segments with font size/weight, from PyMuPDF's dict
    layout. When tables are detected, emit GitHub-flavored markdown tables
    (with headers) and skip the raw spans inside those table bboxes so
    matrices are not flattened into unlabeled number soup.
    """
    ordered: list[_Segment] = []
    table_rects: list[tuple[float, float, float, float]] = []

    try:
        finder = page.find_tables()
        tables = list(getattr(finder, "tables", None) or [])
    except Exception:
        tables = []

    for table in tables:
        try:
            bbox = tuple(float(x) for x in table.bbox)
            table_rects.append(bbox)  # type: ignore[arg-type]
            md = _table_to_markdown(table)
            if md.strip():
                ordered.append(
                    _Segment(
                        text=md,
                        size=11.0,
                        bold=False,
                        continues_line=False,
                        is_table=True,
                        y0=bbox[1],
                    )
                )
        except Exception:
            logger.debug(
                "table extract failed on page %s",
                getattr(page, "number", "?"),
                exc_info=True,
            )

    def _in_table(bbox) -> bool:
        if not table_rects or not bbox:
            return False
        x0, y0, x1, y1 = bbox
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        for tx0, ty0, tx1, ty1 in table_rects:
            if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
                return True
        return False

    raw = page.get_text("dict")
    blocks = sorted(
        raw.get("blocks", []),
        key=lambda b: (
            round(b.get("bbox", (0, 0, 0, 0))[1]),
            b.get("bbox", (0, 0, 0, 0))[0],
        ),
    )
    for block in blocks:
        if block.get("type", 0) != 0:
            continue
        if _in_table(block.get("bbox")):
            continue
        for line in block.get("lines", []):
            line_y = float(line.get("bbox", (0, 0, 0, 0))[1])
            run_text: list[str] = []
            run_size: float | None = None
            run_bold = False
            first_run_in_line = True
            for span in line.get("spans", []):
                text = _PUA_RE.sub("", span.get("text", ""))
                if not text:
                    continue
                size = round(float(span.get("size", 0)), 1)
                bold = bool(span.get("flags", 0) & (1 << 4))
                if run_size is not None and size != run_size:
                    joined = "".join(run_text).strip()
                    if joined:
                        ordered.append(
                            _Segment(
                                text=joined,
                                size=run_size,
                                bold=run_bold,
                                continues_line=not first_run_in_line,
                                y0=line_y,
                            )
                        )
                        first_run_in_line = False
                    run_text, run_bold = [], False
                run_text.append(text)
                run_size = size
                run_bold = run_bold or bold
            joined = "".join(run_text).strip()
            if joined:
                ordered.append(
                    _Segment(
                        text=joined,
                        size=run_size or 0,
                        bold=run_bold,
                        continues_line=not first_run_in_line,
                        y0=line_y,
                    )
                )
    ordered.sort(key=lambda s: (round(s.y0), 0 if s.is_table else 1))
    return ordered


def _table_to_markdown(table) -> str:
    """Render a PyMuPDF table as markdown so row/column headers stay attached."""
    data = table.extract()
    if not data:
        return ""
    rows = [[(c or "").replace("\n", " ").strip() for c in row] for row in data]
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    # If the "header" is all numeric, invent column labels so values stay keyed
    if header and all(
        (not c) or re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", c) for c in header
    ):
        header = [f"C{i + 1}" for i in range(width)]
        body = rows
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _detect_boilerplate(pages: list[list[_Segment]]) -> set[str]:
    """
    Running headers/footers (book/chapter name, folio decorations) repeat
    verbatim across many pages — unlike real headings, which are specific to
    one section. Flag any short text appearing on an unusually large share of
    pages so it's dropped everywhere rather than misread as structure.
    """
    total_pages = len(pages)
    if total_pages < 4:
        return set()

    page_texts = [
        {
            seg.text.strip()
            for seg in segs
            if _MIN_BOILERPLATE_CHARS <= len(seg.text.strip()) <= 60
        }
        for segs in pages
    ]
    counts: Counter[str] = Counter()
    for texts in page_texts:
        counts.update(texts)

    threshold = max(3, int(total_pages * 0.15))
    return {text for text, count in counts.items() if count >= threshold}


def _is_page_number_artifact(text: str) -> bool:
    t = text.strip()
    return t.isdigit() and len(t) <= 4


def _infer_heading_sizes(pages: list[list[_Segment]]) -> dict[float, int]:
    """
    Cluster this document's own font sizes into heading levels. Purely
    data-driven (char-weighted mode = body text; larger sizes above it =
    heading candidates) so it adapts to any PDF's style without tuning.

    Sizes whose segments average under 3 characters are excluded even if
    larger than body text — that pattern is decorative drop-cap initials,
    not real heading content, and would otherwise register as a bogus
    single-letter "heading level".
    """
    char_count_by_size: Counter[float] = Counter()
    segment_count_by_size: Counter[float] = Counter()
    for segments in pages:
        for seg in segments:
            char_count_by_size[seg.size] += len(seg.text)
            segment_count_by_size[seg.size] += 1

    if not char_count_by_size:
        return {}

    body_size = char_count_by_size.most_common(1)[0][0]
    candidate_sizes = sorted(
        (
            size
            for size in char_count_by_size
            if size > body_size * 1.05
            and char_count_by_size[size] / segment_count_by_size[size] >= 3
        ),
        reverse=True,
    )
    # Every qualifying size becomes its own level (not just the top few) —
    # documents with many distinct tiers just clamp to h6 rather than losing
    # the deeper tiers entirely.
    return {size: min(rank, _MAX_HEADING_LEVEL) for rank, size in enumerate(candidate_sizes, start=1)}


def _looks_like_heading(seg: _Segment, level: int | None) -> bool:
    if level is None:
        return False
    text = seg.text.strip()
    if not text or len(text) > _MAX_HEADING_CHARS:
        return False
    if _is_page_number_artifact(text) or len(text) < 3:
        return False
    return True


def _segments_to_markdown(segments: list[_Segment], heading_levels: dict[float, int]) -> str:
    out: list[str] = []
    paragraph: list[str] = []
    pending: tuple[int, list[str]] | None = None  # (level, [text, ...]) — merges
    # consecutive same-level heading segments, e.g. a title wrapped over two
    # lines, into a single heading instead of two sibling headings that would
    # otherwise clobber each other in the heading stack.

    def flush_paragraph() -> None:
        if paragraph:
            out.append(" ".join(paragraph))
            paragraph.clear()

    def flush_heading() -> None:
        nonlocal pending
        if pending:
            level, parts = pending
            out.append(f"{'#' * level} {' '.join(parts)}")
            pending = None

    for seg in segments:
        if seg.is_table:
            flush_paragraph()
            flush_heading()
            out.append(seg.text.strip())
            continue

        level = heading_levels.get(seg.size)
        is_heading = _looks_like_heading(seg, level)

        if is_heading and pending and (seg.continues_line or level == pending[0]):
            # Same physical PDF line as the open heading (covers "1.2  TITLE"
            # layouts where the numeral/drop-cap differs in size from the
            # title text following it on the same line), or a same-level
            # heading continuing on the next line (a title wrapped over two
            # lines) — either way, still part of the same heading.
            pending[1].append(seg.text.strip())
            continue

        if is_heading:
            flush_paragraph()
            flush_heading()
            pending = (level, [seg.text.strip()])
            continue

        flush_heading()
        paragraph.append(seg.text)
    flush_heading()
    flush_paragraph()
    return "\n\n".join(out)


def _parse_pdf(
    path: Path,
    on_progress: ProgressCallback | None = None,
) -> tuple[str, int]:
    import fitz  # PyMuPDF (already required by PageIndex)

    doc = fitz.open(path)
    page_count = doc.page_count
    pages_segments = []
    for i, page in enumerate(doc, start=1):
        if on_progress:
            on_progress(f"{i}/{page_count} pages")
        pages_segments.append(_extract_page_segments(page))
    doc.close()

    total_chars = sum(len(seg.text) for segs in pages_segments for seg in segs)
    avg = total_chars / max(page_count, 1)

    if avg < _MIN_CHARS_PER_PAGE:
        logger.info(
            "PDF %s looks scanned (%.0f chars/page) — running PaddleOCR-VL",
            path.name,
            avg,
        )
        if on_progress:
            on_progress(f"0/{page_count} pages")
        ocr_pages = _ocr_via_paddleocr_vl(path, on_progress=on_progress)
        parts = [f"<!--PAGE:{i}-->\n{text}" for i, text in enumerate(ocr_pages, start=1)]
        if len(ocr_pages) != page_count:
            logger.warning(
                "PaddleOCR-VL returned %d pages, PyMuPDF counted %d for %s",
                len(ocr_pages),
                page_count,
                path.name,
            )
        return "\n\n".join(parts), page_count

    boilerplate = _detect_boilerplate(pages_segments)
    pages_segments = [
        [
            seg
            for seg in segs
            if seg.text.strip() not in boilerplate and not _is_page_number_artifact(seg.text)
        ]
        for segs in pages_segments
    ]

    heading_levels = _infer_heading_sizes(pages_segments)
    parts = [
        f"<!--PAGE:{i}-->\n{_segments_to_markdown(segs, heading_levels)}"
        for i, segs in enumerate(pages_segments, start=1)
    ]
    return "\n\n".join(parts), page_count


def _parse_image(path: Path) -> str:
    pages = _ocr_via_paddleocr_vl(path)
    text = (pages[0] if pages else "").strip()
    title = path.stem.replace("_", " ").replace("-", " ")
    body = text or f"# {title}"
    return f"<!--PAGE:1-->\n{body}"


# --- DOCX / PPTX -----------------------------------------------------------------


def _parse_docx(path: Path) -> str:
    """Word has no fixed 'pages' pre-render, so chunks from this source carry no
    page numbers — heading structure (native Heading N styles) still applies."""
    from docx import Document as DocxDocument

    doc = DocxDocument(str(path))
    blocks: list[str] = []
    for para in doc.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue
        style = (para.style.name or "") if para.style else ""
        if style.startswith("Heading"):
            level = 1
            for ch in style:
                if ch.isdigit():
                    level = int(ch)
                    break
            level = max(1, min(level, 6))
            blocks.append(f"{'#' * level} {text}")
        else:
            blocks.append(text)
    return "\n\n".join(blocks)


def _parse_pptx(path: Path) -> tuple[str, int]:
    from pptx import Presentation

    prs = Presentation(str(path))
    parts: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title = (title_shape.text or "").strip() if title_shape else ""
        parts.append(f"<!--PAGE:{i}-->\n" + (f"## {title}" if title else f"## Slide {i}"))

        title_id = title_shape.shape_id if title_shape else None
        body_texts = [
            shape.text.strip()
            for shape in slide.shapes
            if shape.shape_id != title_id and hasattr(shape, "text") and shape.text and shape.text.strip()
        ]
        if body_texts:
            parts.append("\n\n".join(body_texts))
    return "\n\n".join(parts), len(prs.slides)


# --- PaddleOCR-VL hosted API (AI Studio) --------------------------------------
# Async job API: submit a file → poll job status → download a JSONL result with
# one layout-parsed markdown page per line (headings already leveled by the
# model). Runs entirely on AI Studio's infrastructure — no local paddle install.
_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
_POLL_INTERVAL_S = 5
_JOB_TIMEOUT_S = 600
_UPLOAD_ATTEMPTS = 3
_UPLOAD_RETRY_BACKOFF_S = 3


def _paddleocr_vl_headers() -> dict:
    token = getattr(settings, "PADDLEOCR_VL_TOKEN", "")
    if not token:
        raise RuntimeError(
            "PADDLEOCR_VL_TOKEN is not set — required for scanned PDF/image OCR."
        )
    return {"Authorization": f"bearer {token}"}


def _ocr_via_paddleocr_vl(
    path: Path,
    on_progress: ProgressCallback | None = None,
) -> list[str]:
    """
    Submit a file (PDF or image) to the PaddleOCR-VL hosted API and return one
    markdown string per extracted page, in order.

    Large multi-page scanned PDFs are rendered page-by-page to PNG and submitted
    individually — full ~10MB PDF uploads time out on slow links, and single-page
    PDFs can fail PaddleOCR's splitter (系统错误-拆页).
    """
    import fitz

    suffix = path.suffix.lower()
    size = path.stat().st_size
    if suffix != ".pdf" or size <= 1_500_000:
        if on_progress:
            on_progress("OCR…")
        return _ocr_submit_paddleocr_vl_file(path)

    doc = fitz.open(path)
    try:
        page_count = doc.page_count
        if page_count <= 1:
            if on_progress:
                on_progress("1/1 pages")
            return _ocr_submit_paddleocr_vl_file(path)

        logger.info(
            "PaddleOCR-VL: OCR %s as %d page images (%d bytes)",
            path.name,
            page_count,
            size,
        )
        pages: list[str] = []
        with tempfile.TemporaryDirectory(prefix="paddleocr_pages_") as tmp:
            tmp_dir = Path(tmp)
            # ~144 DPI — sharp enough for exam papers, small enough to upload.
            matrix = fitz.Matrix(2, 2)
            for i in range(page_count):
                if on_progress:
                    on_progress(f"{i + 1}/{page_count} pages")
                page_png = tmp_dir / f"page_{i + 1:04d}.png"
                pix = doc[i].get_pixmap(matrix=matrix)
                pix.save(page_png)
                page_texts = _ocr_submit_paddleocr_vl_file(page_png)
                if page_texts:
                    pages.append(page_texts[0] if len(page_texts) == 1 else "\n\n".join(page_texts))
                else:
                    pages.append("")
                logger.info(
                    "PaddleOCR-VL page %d/%d done for %s",
                    i + 1,
                    page_count,
                    path.name,
                )
        return pages
    finally:
        doc.close()


def _ocr_submit_paddleocr_vl_file(path: Path) -> list[str]:
    """Submit one file (whole PDF or a single-page PDF) and return page markdowns."""
    import requests

    model = getattr(settings, "PADDLEOCR_VL_MODEL", "PaddleOCR-VL-1.6")
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    # A single dropped connection would otherwise discard a whole multi-page job.
    response = None
    last_exc: Exception | None = None
    for attempt in range(_UPLOAD_ATTEMPTS):
        try:
            with open(path, "rb") as f:
                files = {"file": (path.name, f)}
                data = {"model": model, "optionalPayload": json.dumps(optional_payload)}
                response = requests.post(
                    _JOB_URL,
                    headers=_paddleocr_vl_headers(),
                    data=data,
                    files=files,
                    timeout=600,
                )
            break
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning(
                "PaddleOCR-VL upload failed for %s (attempt %d/%d): %s",
                path.name,
                attempt + 1,
                _UPLOAD_ATTEMPTS,
                exc,
            )
            if attempt + 1 < _UPLOAD_ATTEMPTS:
                time.sleep(_UPLOAD_RETRY_BACKOFF_S * (attempt + 1))

    if response is None:
        raise RuntimeError(
            "Could not reach the OCR service. Check your internet connection "
            "and try again."
        ) from last_exc
    if response.status_code != 200:
        raise RuntimeError(
            f"PaddleOCR-VL job submission failed ({response.status_code}): {response.text}"
        )
    job_id = response.json()["data"]["jobId"]
    logger.info("PaddleOCR-VL job submitted for %s (job_id=%s)", path.name, job_id)

    jsonl_url = _poll_paddleocr_vl_job(job_id)
    return _download_paddleocr_vl_pages(jsonl_url)


def _poll_paddleocr_vl_job(job_id: str) -> str:
    import requests

    deadline = time.monotonic() + _JOB_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = requests.get(
            f"{_JOB_URL}/{job_id}", headers=_paddleocr_vl_headers(), timeout=30
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"PaddleOCR-VL job status check failed ({resp.status_code}): {resp.text}"
            )
        data = resp.json()["data"]
        state = data.get("state")

        if state == "done":
            return data["resultUrl"]["jsonUrl"]
        if state == "failed":
            raise RuntimeError(f"PaddleOCR-VL job failed: {data.get('errorMsg')}")

        logger.info("PaddleOCR-VL job %s: %s", job_id, state)
        time.sleep(_POLL_INTERVAL_S)

    raise RuntimeError(f"PaddleOCR-VL job {job_id} timed out after {_JOB_TIMEOUT_S}s")


def _download_paddleocr_vl_pages(jsonl_url: str) -> list[str]:
    import requests

    resp = requests.get(jsonl_url, timeout=120)
    resp.raise_for_status()

    pages: list[str] = []
    for line in resp.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        result = json.loads(line)["result"]
        for page_result in result.get("layoutParsingResults", []):
            pages.append(page_result.get("markdown", {}).get("text", ""))
    return pages


def _normalize_markdown(text: str) -> str:
    # Collapse excessive blank lines; keep heading/page-marker lines intact.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"
