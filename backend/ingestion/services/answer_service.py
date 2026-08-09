"""
Query-time answer generation via Groq (OpenAI-compatible chat completions).

Multi-turn: the client sends prior {role, content} turns; those are included
in the chat so the model remembers the conversation. Retrieval for follow-ups
is rewritten from conversation context — especially the *topic the assistant
just named* (e.g. "7.3 Methods of Integration") when the student says
"explain that" — not just the previous user wording, which is often meta
("what comes next?") and would otherwise pull TOC/answer-key pages.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings

from .llm_errors import raise_for_llm_response
from .retrieval_service import RetrievedChunk, search_bucket
from ..models import Chunk

logger = logging.getLogger(__name__)

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
_MAX_HISTORY_MESSAGES = 12  # 6 user/assistant pairs

_SYSTEM_PROMPT = (
    "You are a study assistant for a school having a continuing conversation "
    "with a student. Use the conversation history for context and follow-ups "
    "(pronouns like 'that', 'it', 'the next topic', 'explain more', etc.).\n\n"
    "When the student asks you to explain 'that' / 'the next topic', they mean "
    "the concrete syllabus topic you just identified — teach that topic from "
    "the excerpts, with a clear example when possible. Do NOT answer as if "
    "they asked for a table of contents again.\n\n"
    "If a SYLLABUS HINT is provided with the current turn, treat it as the "
    "intended topic to teach or confirm.\n\n"
    "Answer using the numbered excerpts provided with the CURRENT turn — "
    "they come from this subject's indexed teacher notes. Each excerpt is "
    "labeled with its source file=… and doc_id=… — when you cite, keep claims "
    "tied to that file. Cite excerpt numbers inline like [1] or [2][3]. "
    "Prefer teaching text over answer keys / exercise lists.\n\n"
    "HOW TO ANSWER:\n"
    "- If the excerpts contain the answer (or enough to teach the asked topic), "
    "answer clearly and completely from those excerpts.\n"
    "- If the excerpts are only partly related, answer what they do support and "
    "say briefly what is missing.\n"
    "- Only if the excerpts clearly do not address the question at all, reply "
    "exactly: \"I couldn't find that in the indexed notes.\" "
    "Do not invent formulas, steps, matrix entries, or page references from "
    "general knowledge.\n"
    "- Never contradict yourself across numbers/rows; if a table is incomplete "
    "in the excerpts, say so instead of guessing missing cells.\n\n"
    "Keep answers clear and suitable for Class XII students.\n\n"
    "MATH & CHEMISTRY FORMATTING (required for the UI renderer):\n"
    "- Write every equation / formula in LaTeX with dollar delimiters.\n"
    "- Inline math: $...$  e.g. $\\int \\sin(mx)\\,dx = -\\cos(mx)/m + C$\n"
    "- Display (block) math on its own line: $$...$$  e.g. "
    "$$I = \\int f(x)\\,dx = \\int f(g(t)) g'(t)\\,dt$$\n"
    "- Chemical formulae / reactions with mhchem inside math: "
    "$\\ce{H2SO4}$ or $$\\ce{2H2 + O2 -> 2H2O}$$\n"
    "- Do NOT write plain-text approximations like ∫sin(mx) dx or H2O when "
    "LaTeX is possible — always use $...$ / $$...$$ / $\\ce{...}$.\n"
    "- Prefer short markdown structure: headings, bullets, and numbered steps "
    "when helpful.\n"
    "- When a cited excerpt includes a figure / diagram / graph, say so "
    "(e.g. 'See the figure on page N [1]') so the student UI can show that page."
)

_FOLLOWUP_HINT = re.compile(
    r"\b(it|that|this|those|these|them|above|previous|earlier|"
    r"more|again|explain|elaborate|why|how|what about|same|"
    r"next topic|that topic|the next)\b",
    re.IGNORECASE,
)

_META_QUESTION = re.compile(
    r"\b(what comes next|next topic|what'?s next|which topic|"
    r"list (the )?topics|table of contents|toc)\b",
    re.IGNORECASE,
)

# "7.3 Methods of Integration", "13.2 Conditional Probability"
_SECTION_HEADING = re.compile(
    r"\b(\d+(?:\.\d+){1,2}\s+[A-Z][A-Za-z0-9][A-Za-z0-9 ,/\-]{2,80})"
)
# Quoted titles the model often emits: "Methods of Integration"
_QUOTED_TITLE = re.compile(r'"([A-Z][^"]{3,80})"')


@dataclass
class GeneratedAnswer:
    answer: str
    sources: list[RetrievedChunk]
    model: str
    retrieval_query: str


def answer_question(
    bucket_id: int,
    question: str,
    top_k: int | None = None,
    history: list[dict] | None = None,
) -> GeneratedAnswer:
    model = getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile")
    history = _normalize_history(history or [])

    syllabus_hint = _resolve_syllabus_topic(bucket_id, question, history)
    retrieval_query = _retrieval_query(question, history, syllabus_hint=syllabus_hint)
    # Chat/ask uses teaching notes; previous-year papers are for mock tests.
    if top_k is None:
        top_k = int(getattr(settings, "RAG_TOP_K", 5) or 5)
    chunks = search_bucket(
        bucket_id,
        query=retrieval_query,
        top_k=top_k,
        kinds=["notes"],
    )

    if not chunks:
        return GeneratedAnswer(
            answer="I couldn't find that in the indexed notes.",
            sources=[],
            model=model,
            retrieval_query=retrieval_query,
        )

    floor = float(getattr(settings, "RAG_MIN_SCORE", 0.22) or 0.0)
    best = max(c.score for c in chunks)
    if floor and best < floor:
        return GeneratedAnswer(
            answer="I couldn't find that in the indexed notes.",
            sources=chunks[:3],
            model=model,
            retrieval_query=retrieval_query,
        )

    # Fast path: user asks for Appendix content that was never uploaded.
    missing = _missing_appendix_message(bucket_id, question, chunks)
    if missing:
        return GeneratedAnswer(
            answer=missing,
            sources=chunks[:2],
            model=model,
            retrieval_query=retrieval_query,
        )

    api_key = getattr(settings, "GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set — required for /api/ask/.")

    # Groq free tier ~12k TPM — keep prompt small or requests hang / 413.
    context_chunks = _fit_context_chunks(chunks)
    history_for_llm = _trim_history_for_llm(history, budget_chars=2500)

    answer_text = _call_groq(
        api_key=api_key,
        model=model,
        history=history_for_llm,
        chunks=context_chunks,
        syllabus_hint=syllabus_hint,
        question=question,
    )
    return GeneratedAnswer(
        answer=answer_text,
        sources=context_chunks,
        model=model,
        retrieval_query=retrieval_query,
    )


def _fit_context_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    max_total = int(getattr(settings, "RAG_MAX_CONTEXT_CHARS", 7000) or 7000)
    max_each = int(getattr(settings, "RAG_MAX_CHUNK_CHARS", 1100) or 1100)
    fitted: list[RetrievedChunk] = []
    used = 0
    for c in chunks:
        text = (c.text or "").strip()
        if len(text) > max_each:
            text = text[: max_each - 1].rstrip() + "…"
        if used + len(text) > max_total and fitted:
            break
        fitted.append(
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_filename=c.document_filename,
                heading_path=c.heading_path,
                page_start=c.page_start,
                page_end=c.page_end,
                text=text,
                score=c.score,
            )
        )
        used += len(text)
    return fitted or chunks[:1]


def _trim_history_for_llm(history: list[dict], budget_chars: int) -> list[dict]:
    if not history:
        return []
    out: list[dict] = []
    used = 0
    for item in reversed(history):
        content = (item.get("content") or "")[:800]
        if used + len(content) > budget_chars and out:
            break
        out.append({"role": item["role"], "content": content})
        used += len(content)
    out.reverse()
    return out


def _missing_appendix_message(
    bucket_id: int,
    question: str,
    chunks: list[RetrievedChunk],
) -> str | None:
    q = (question or "").lower()
    if "appendix" not in q:
        return None
    from django.db.models import Q

    has_body = (
        Chunk.objects.filter(
            bucket_id=bucket_id,
            document__status="indexed",
            document__deleted_at__isnull=True,
            document__kind="notes",
        )
        .filter(
            Q(text__icontains="Proofs in Mathematics")
            | Q(text__icontains="Mathematical Modelling")
            | Q(text__icontains="What is a Proof")
            | Q(text__icontains="foot of the tower")
            | Q(text__icontains="A.1.2")
            | Q(text__icontains="A.2.2")
        )
        .exclude(text__icontains="Contents")
        .exists()
    )
    if has_body:
        return None
    joined = " ".join(c.text for c in chunks).lower()
    if "inaccessible" in joined or "tower" in joined:
        return None
    return (
        "I couldn't find that in the indexed notes. "
        "Appendix 1 / Appendix 2 content is not in the uploaded PDFs yet "
        "(only the table of contents mentions them). "
        "Please upload the NCERT appendix chapters, then ask again."
    )


def _call_groq(
    *,
    api_key: str,
    model: str,
    history: list[dict],
    chunks: list[RetrievedChunk],
    syllabus_hint: str | None,
    question: str,
) -> str:
    def build_messages(use_chunks: list[RetrievedChunk]) -> list[dict]:
        context = "\n\n".join(
            f"[{i}] file={c.document_filename!r} doc_id={c.document_id} "
            f"pages={c.page_start}-{c.page_end} "
            f"section={' > '.join(c.heading_path) or 'untitled'}:\n{c.text}"
            for i, c in enumerate(use_chunks, start=1)
        )
        hint_line = (
            f"\n\nSYLLABUS HINT (intended topic): {syllabus_hint}" if syllabus_hint else ""
        )
        current_user = (
            f"Excerpts for this turn:\n\n{context}{hint_line}\n\n"
            f"Current question: {question}"
        )
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": current_user})
        return messages

    def post(messages: list[dict]):
        return requests.post(
            _GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1000,
            },
            timeout=45,
        )

    working = list(chunks)
    messages = build_messages(working)
    response = post(messages)

    # Oversized / TPM: shrink context and retry once (no long sleep).
    if response.status_code in (413, 429):
        body = (response.text or "").lower()
        if response.status_code == 413 or "request too large" in body or "tpm" in body:
            logger.warning(
                "Groq request too large (status=%s) — retrying with smaller context",
                response.status_code,
            )
            working = working[: max(2, len(working) // 2)]
            working = _fit_context_chunks(working)
            # Drop history on retry to free tokens
            messages = build_messages(working)
            # strip history
            messages = [messages[0], messages[-1]]
            response = post(messages)

    if response.status_code == 429:
        import time

        time.sleep(1.5)
        response = post(messages)

    raise_for_llm_response(response, provider="Groq")
    return response.json()["choices"][0]["message"]["content"].strip()


def _normalize_history(raw: list[dict]) -> list[dict]:
    """Keep only alternating user/assistant turns, most recent N messages."""
    cleaned: list[dict] = []
    for item in raw:
        role = (item.get("role") or "").strip().lower()
        content = (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned.append({"role": role, "content": content[:4000]})
    return cleaned[-_MAX_HISTORY_MESSAGES:]


def _retrieval_query(
    question: str,
    history: list[dict],
    syllabus_hint: str | None = None,
) -> str:
    """
    Build a search string that finds *teaching content*, not TOC/answer keys.

    Critical case: after the agent lists "next topic = 7.3 Methods of
    Integration", the student says "okay explain that" — we must search for
    that section title, not for "what comes next topic".
    """
    if syllabus_hint:
        return f"{syllabus_hint}\n{question}"

    if not history:
        return question

    words = question.split()
    looks_like_followup = len(words) <= 16 or bool(_FOLLOWUP_HINT.search(question))
    if not looks_like_followup:
        return question

    prior_user = [m["content"] for m in history if m["role"] == "user"]
    prior_assistant = [m["content"] for m in history if m["role"] == "assistant"]
    last_assistant = prior_assistant[-1] if prior_assistant else ""
    last_user = prior_user[-1] if prior_user else ""

    topics = _extract_topics(last_assistant)
    if topics and (
        _META_QUESTION.search(last_user)
        or re.search(r"\b(next topic|that topic|explain that|explain (it|this))\b", question, re.I)
        or re.search(r"\bnext\b", question, re.I)
    ):
        return f"{topics[0]}\n{question}"

    anchor = ""
    for text in reversed(prior_user):
        if not _META_QUESTION.search(text):
            anchor = text
            break
    if not anchor and topics:
        anchor = topics[0]
    if not anchor and last_user:
        anchor = last_user

    return f"{anchor}\n{question}" if anchor else question


def _resolve_syllabus_topic(
    bucket_id: int, question: str, history: list[dict]
) -> str | None:
    """
    Resolve the concrete syllabus section the student is talking about using
    indexed heading_paths (ground truth), not only the model's previous wording.
    """
    prior_user = [m["content"] for m in history if m["role"] == "user"]
    prior_assistant = [m["content"] for m in history if m["role"] == "assistant"]

    # Prefer a section the assistant already named.
    if prior_assistant:
        named = _extract_topics(prior_assistant[-1])
        if named and (
            _FOLLOWUP_HINT.search(question)
            or _META_QUESTION.search(question)
            or len(question.split()) <= 16
        ):
            # "what's next" → first named next section; "explain that" after a
            # next-topic turn also wants the first one.
            if _META_QUESTION.search(question) or (
                prior_user and _META_QUESTION.search(prior_user[-1])
            ):
                return named[0]
            if re.search(r"\b(explain|elaborate|example)\b", question, re.I):
                return named[0]

    # Structural next-section from indexed headings.
    anchor_text = ""
    for text in reversed(prior_user):
        if not _META_QUESTION.search(text):
            anchor_text = text
            break
    if not anchor_text and prior_user:
        anchor_text = prior_user[-1]
    if not anchor_text:
        return None

    current = _find_heading_for_text(bucket_id, anchor_text)
    if not current:
        return None

    wants_next = bool(_META_QUESTION.search(question)) or (
        prior_user
        and _META_QUESTION.search(prior_user[-1])
        and bool(_FOLLOWUP_HINT.search(question) or len(question.split()) <= 16)
    )
    if wants_next:
        nxt = _next_heading_after(bucket_id, current)
        return nxt or current
    return current


def _find_heading_for_text(bucket_id: int, text: str) -> str | None:
    """Best matching leaf heading for a free-text topic mention."""
    hits = search_bucket(bucket_id, query=text, top_k=8, kinds=["notes"])
    for hit in hits:
        for part in reversed(hit.heading_path or []):
            if _SECTION_HEADING.search(part) or re.search(
                r"Integration as an Inverse|Methods of Integration|"
                r"Conditional Probability|Definite Integral",
                part,
                re.I,
            ):
                return part.strip()
        if hit.heading_path:
            leaf = hit.heading_path[-1].strip()
            if leaf and leaf.lower() not in {"answers", "summary", "contents"}:
                return leaf
    return None


def _next_heading_after(bucket_id: int, current_heading: str) -> str | None:
    """
    Walk numbered leaf headings in document order and return the one after
    `current_heading` (e.g. 7.2 … → 7.3 Methods of Integration).
    """
    rows = list(
        Chunk.objects.filter(bucket_id=bucket_id)
        .order_by("document_id", "order_index")
        .values_list("heading_path", flat=True)
    )
    ordered: list[str] = []
    seen: set[str] = set()
    for path in rows:
        if not path:
            continue
        leaf = path[-1].strip()
        if not leaf or leaf in seen:
            continue
        if not (_SECTION_HEADING.search(leaf) or re.match(r"^\d", leaf)):
            continue
        seen.add(leaf)
        ordered.append(leaf)

    current_norm = re.sub(r"\s+", " ", current_heading).strip().lower()
    for i, heading in enumerate(ordered):
        if re.sub(r"\s+", " ", heading).strip().lower() == current_norm:
            if i + 1 < len(ordered):
                return ordered[i + 1]
            return None
        # fuzzy: current is contained in heading or shares section number
        cur_num = re.match(r"^(\d+(?:\.\d+){1,2})", current_heading)
        head_num = re.match(r"^(\d+(?:\.\d+){1,2})", heading)
        if cur_num and head_num and cur_num.group(1) == head_num.group(1):
            if i + 1 < len(ordered):
                return ordered[i + 1]
            return None
    return None


def _extract_topics(assistant_text: str) -> list[str]:
    """Pull syllabus section titles out of the assistant's last reply."""
    if not assistant_text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    def add(title: str) -> None:
        cleaned = re.sub(r"\s+", " ", title).strip(" .;,:")
        key = cleaned.lower()
        if len(cleaned) < 5 or key in seen:
            return
        if cleaned.lower() in {"integrals", "mathematics", "answers", "exercises"}:
            return
        seen.add(key)
        found.append(cleaned)

    for match in _SECTION_HEADING.finditer(assistant_text):
        add(match.group(1))

    for match in _QUOTED_TITLE.finditer(assistant_text):
        add(match.group(1))

    for line in assistant_text.splitlines():
        line = line.strip(" -•*\t")
        m = re.match(r"^(\d+(?:\.\d+){1,2}\s+[A-Za-z].+)$", line)
        if m:
            add(m.group(1))

    return found