"""Render PDF/image document pages to PNG for chat source previews."""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from ..models import Document

logger = logging.getLogger(__name__)


def page_image_path(document: Document, page: int) -> Path:
    root = Path(settings.MEDIA_ROOT)
    return root / "page_previews" / str(document.bucket_id) / str(document.id) / f"{page}.png"


def render_document_page(document: Document, page: int, *, max_width: int = 1200) -> Path | None:
    """
    Return a cached PNG path for 1-based page number, or None if unavailable.
    Supports PDF (PyMuPDF) and single-page image uploads.
    """
    if page < 1:
        return None
    try:
        src = Path(document.file.path)
    except Exception:
        return None
    if not src.exists():
        return None

    out = page_image_path(document, page)
    if out.exists() and out.stat().st_size > 0:
        return out

    suffix = src.suffix.lower()
    try:
        if suffix == ".pdf":
            return _render_pdf_page(src, page, out, max_width=max_width)
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff", ".bmp"}:
            if page != 1:
                return None
            return _copy_image(src, out)
    except Exception:
        logger.exception(
            "Failed to render page image doc=%s page=%s", document.id, page
        )
        return None
    return None


def _render_pdf_page(src: Path, page: int, out: Path, *, max_width: int) -> Path | None:
    import fitz  # PyMuPDF

    doc = fitz.open(src)
    try:
        if page > doc.page_count:
            return None
        pg = doc.load_page(page - 1)
        # Scale so width ≈ max_width
        rect = pg.rect
        scale = min(2.0, max_width / max(rect.width, 1.0))
        mat = fitz.Matrix(scale, scale)
        pix = pg.get_pixmap(matrix=mat, alpha=False)
        out.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out))
        return out
    finally:
        doc.close()


def _copy_image(src: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(src.read_bytes())
    return out
