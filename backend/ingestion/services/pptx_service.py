"""
Generate a downloadable PPTX from bucket notes (RAG + Groq outline + python-pptx).
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import dataclass

import requests
from django.conf import settings
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from .retrieval_service import search_bucket

logger = logging.getLogger(__name__)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT = (
    "You create teaching PowerPoint outlines for Class XII students.\n"
    "Use ONLY the numbered excerpts from the teacher's indexed notes. "
    "Do not invent facts that are not supported by the excerpts.\n\n"
    "Respond with valid JSON only (no markdown fences). Schema:\n"
    "{\n"
    '  "title": "deck title",\n'
    '  "slides": [\n'
    '    {"heading": "slide title", "bullets": ["point", "..."], "notes": "optional"}\n'
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Produce exactly the requested number of slides in the slides array.\n"
    "- First slide should introduce the topic; last may summarize or list takeaways.\n"
    "- 3–6 short bullets per slide; no long paragraphs.\n"
    "- Prefer plain text; for formulas use simple Unicode or ASCII math "
    "(e.g. ∫ f(x) dx), not LaTeX dollar delimiters.\n"
    "- Speaker notes are optional and brief."
)


class PptxGenerationError(Exception):
    """User-facing generation failure (empty retrieval, bad model output, etc.)."""


@dataclass
class GeneratedOutline:
    title: str
    slides: list[dict]
    model: str
    prompt: str


@dataclass
class GeneratedPptx:
    data: bytes
    filename: str
    title: str
    slide_count: int


def generate_pptx_outline(
    bucket_id: int,
    prompt: str,
    slide_count: int = 8,
    top_k: int = 12,
) -> GeneratedOutline:
    """RAG + Groq → structured slide outline for preview (no file yet)."""
    prompt = (prompt or "").strip()
    if not prompt:
        raise PptxGenerationError("Prompt is required.")
    if slide_count < 3 or slide_count > 15:
        raise PptxGenerationError("slide_count must be between 3 and 15.")

    model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    chunks = search_bucket(bucket_id, query=prompt, top_k=top_k, kinds=["notes"])
    if not chunks:
        raise PptxGenerationError(
            "No matching notes found in this AI Bucket. Index notes first, "
            "or try a more specific topic from your materials."
        )

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set — required for PPT generation.")

    context = "\n\n".join(
        f"[{i}] (pages {c.page_start}-{c.page_end}, "
        f"{' > '.join(c.heading_path) or 'untitled section'}):\n{c.text}"
        for i, c in enumerate(chunks, start=1)
    )
    user_msg = (
        f"Excerpts:\n\n{context}\n\n"
        f"User request: {prompt}\n"
        f"Create exactly {slide_count} slides."
    )

    outline = _fetch_outline(api_key, model, user_msg, slide_count)
    return GeneratedOutline(
        title=outline["title"],
        slides=outline["slides"],
        model=model,
        prompt=prompt,
    )


def pptx_from_outline(title: str, slides: list[dict]) -> GeneratedPptx:
    """Build a .pptx from a previewed outline (no LLM call)."""
    outline = _normalize_outline({"title": title, "slides": slides}, slide_count=None)
    if not outline["slides"]:
        raise PptxGenerationError("Outline has no slides to export.")
    data = _build_pptx(outline)
    return GeneratedPptx(
        data=data,
        filename=_safe_filename(outline["title"]),
        title=outline["title"],
        slide_count=len(outline["slides"]),
    )


def generate_pptx(
    bucket_id: int,
    prompt: str,
    slide_count: int = 8,
    top_k: int = 12,
) -> GeneratedPptx:
    """Convenience: outline + build in one step."""
    outline = generate_pptx_outline(
        bucket_id, prompt=prompt, slide_count=slide_count, top_k=top_k
    )
    return pptx_from_outline(outline.title, outline.slides)


def _fetch_outline(api_key: str, model: str, user_msg: str, slide_count: int) -> dict:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }
    response = requests.post(
        _GROQ_CHAT_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if response.status_code == 429:
        time.sleep(2.0)
        response = requests.post(
            _GROQ_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
    if response.status_code != 200:
        raise RuntimeError(f"Groq API error ({response.status_code}): {response.text}")

    raw = response.json()["choices"][0]["message"]["content"].strip()
    data = _parse_outline_json(raw)
    return _normalize_outline(data, slide_count)


def _parse_outline_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PptxGenerationError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PptxGenerationError("Model outline must be a JSON object.")
    return data


def _normalize_outline(data: dict, slide_count: int | None) -> dict:
    title = str(data.get("title") or "Lesson slides").strip() or "Lesson slides"
    slides_raw = data.get("slides")
    if not isinstance(slides_raw, list) or not slides_raw:
        raise PptxGenerationError("Model returned no slides.")

    slides: list[dict] = []
    for item in slides_raw:
        if not isinstance(item, dict):
            continue
        heading = str(item.get("heading") or item.get("title") or "Slide").strip()
        bullets_in = item.get("bullets") or item.get("points") or []
        if isinstance(bullets_in, str):
            bullets_in = [bullets_in]
        bullets = [str(b).strip() for b in bullets_in if str(b).strip()][:8]
        if not bullets:
            body = str(item.get("content") or item.get("body") or "").strip()
            if body:
                bullets = [body]
        notes = str(item.get("notes") or "").strip()
        if not bullets:
            continue
        slides.append({"heading": heading[:120], "bullets": bullets, "notes": notes[:500]})

    if not slides:
        raise PptxGenerationError("Model returned empty slide content.")

    # Trim or pad only when a target count was requested (LLM generation path).
    if slide_count is not None:
        if len(slides) > slide_count:
            slides = slides[:slide_count]
        while len(slides) < slide_count:
            base = slides[-1]
            slides.append(
                {
                    "heading": f"{base['heading']} (cont.)",
                    "bullets": base["bullets"][:3],
                    "notes": "",
                }
            )

    return {"title": title[:160], "slides": slides}


def _safe_filename(title: str) -> str:
    stem = re.sub(r"[^\w\s\-]+", "", title, flags=re.UNICODE).strip()
    stem = re.sub(r"\s+", "_", stem)[:60] or "lesson"
    return f"{stem}.pptx"


def _build_pptx(outline: dict) -> bytes:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Title slide
    title_layout = prs.slide_layouts[6]  # blank
    title_slide = prs.slides.add_slide(title_layout)
    _add_textbox(
        title_slide,
        Inches(0.8),
        Inches(2.4),
        Inches(11.7),
        Inches(1.5),
        outline["title"],
        font_size=36,
        bold=True,
        color=RGBColor(0x1A, 0x3A, 0x32),
    )
    _add_textbox(
        title_slide,
        Inches(0.8),
        Inches(4.1),
        Inches(11.7),
        Inches(0.6),
        "Generated from your AI Bucket notes",
        font_size=16,
        color=RGBColor(0x5A, 0x6B, 0x66),
    )

    body_layout = prs.slide_layouts[6]
    for slide_data in outline["slides"]:
        slide = prs.slides.add_slide(body_layout)
        _add_textbox(
            slide,
            Inches(0.7),
            Inches(0.45),
            Inches(12.0),
            Inches(1.0),
            slide_data["heading"],
            font_size=28,
            bold=True,
            color=RGBColor(0x1A, 0x3A, 0x32),
        )
        bullets_text = "\n".join(f"• {b}" for b in slide_data["bullets"])
        _add_textbox(
            slide,
            Inches(0.85),
            Inches(1.6),
            Inches(11.6),
            Inches(5.2),
            bullets_text,
            font_size=18,
            color=RGBColor(0x22, 0x28, 0x26),
        )
        if slide_data.get("notes"):
            notes_frame = slide.notes_slide.notes_text_frame
            notes_frame.text = slide_data["notes"]

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _add_textbox(
    slide,
    left,
    top,
    width,
    height,
    text: str,
    *,
    font_size: int = 18,
    bold: bool = False,
    color: RGBColor | None = None,
):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    lines = text.split("\n") or [""]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(8)
        if not p.runs:
            continue
        font = p.runs[0].font
        font.size = Pt(font_size)
        font.bold = bold
        font.name = "Calibri"
        if color is not None:
            font.color.rgb = color
