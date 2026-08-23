"""Generate mixed-type mock tests and grade brief answers via RAG + LLM."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ingestion.models import Document, SchoolMembership, SubjectBucket
from ingestion.services.brevo_service import BrevoError, send_transactional_email
from ingestion.services.llm_provider import chat_completion, get_chat_llm
from rag_harness.bucket_router import get_indexed_documents
from rag_harness.context_builder import build_context
from rag_harness.exceptions import HarnessLLMError
from rag_harness.permissions import check_bucket_access
from rag_harness.retriever import retrieve

from .models import MockAnswerGrade, MockAttempt, MockQuestion, MockTest

logger = logging.getLogger(__name__)

_SYSTEM_BASE = (
    "Use ONLY the numbered source excerpts. Do not invent unsupported facts.\n"
    "Respond with valid JSON only (no markdown fences). Schema:\n"
    "{\n"
    '  "title": "short test title",\n'
    '  "questions": [\n'
    "    {\n"
    '      "qtype": "mcq" | "multi" | "brief",\n'
    '      "prompt": "question text",\n'
    '      "options": ["A", "B", "C", "D"],\n'
    '      "correct_indices": [0],\n'
    '      "model_answer": ""\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Rules:\n"
    "- mcq: exactly 4 options; correct_indices has exactly one index 0-3; model_answer empty.\n"
    "- multi: exactly 4 options; correct_indices has 2 or more distinct indices 0-3; model_answer empty.\n"
    "- brief: options []; correct_indices []; model_answer is a concise ideal answer.\n"
    "- Produce exactly the requested counts of each type, in that order "
    "(all mcq, then multi, then brief).\n"
    "- Clear, unambiguous stems."
)

_SYSTEM_NOTES = (
    "You create Class XII mock tests from teacher notes.\n" + _SYSTEM_BASE
)

_SYSTEM_PAPERS = (
    "You create Class XII mock tests modelled on previous-year question papers.\n"
    "Match the style, difficulty, and wording patterns of the exam excerpts. "
    "Create NEW questions in that style (do not copy stems verbatim).\n"
    + _SYSTEM_BASE
)

_SYSTEM_BOTH = (
    "You create Class XII mock tests using teacher notes AND previous-year papers.\n"
    "Prefer exam-style wording from the papers; ground facts in the notes.\n"
    + _SYSTEM_BASE
)


def source_mode_to_kinds(source_mode: str) -> list[str]:
    if source_mode == MockTest.SOURCE_QUESTION_PAPERS:
        return [Document.KIND_QUESTION_PAPER]
    if source_mode == MockTest.SOURCE_BOTH:
        return [Document.KIND_NOTES, Document.KIND_QUESTION_PAPER]
    return [Document.KIND_NOTES]


def _validated_reference_paper_ids(
    bucket: SubjectBucket,
    reference_document_ids: list[int] | None,
    *,
    required: bool,
) -> list[int]:
    """Return indexed question-paper IDs in this bucket (subset if ids given)."""
    indexed = list(
        get_indexed_documents(bucket, kinds=[Document.KIND_QUESTION_PAPER]).values_list(
            "id", flat=True
        )
    )
    if not indexed:
        if required:
            raise MockTestGenerationError(
                "No indexed previous-year papers in this AI Bucket. "
                "Upload question papers under the Question papers tab first."
            )
        return []

    allowed = {int(i) for i in indexed}
    raw = reference_document_ids or []
    if not raw:
        return sorted(allowed)

    picked: list[int] = []
    seen: set[int] = set()
    for item in raw:
        try:
            doc_id = int(item)
        except (TypeError, ValueError):
            continue
        if doc_id not in allowed:
            raise MockTestGenerationError(
                f"Question paper #{doc_id} is not indexed in this AI Bucket."
            )
        if doc_id not in seen:
            seen.add(doc_id)
            picked.append(doc_id)
    if required and not picked:
        raise MockTestGenerationError("Select at least one indexed question paper.")
    return picked


def _retrieve_for_mock(
    bucket: SubjectBucket,
    *,
    prompt: str,
    top_k: int,
    source_mode: str,
    reference_document_ids: list[int] | None,
) -> list[dict[str, Any]]:
    if source_mode == MockTest.SOURCE_NOTES:
        return retrieve(bucket, query=prompt, top_k=top_k, kinds=[Document.KIND_NOTES])

    paper_ids = _validated_reference_paper_ids(
        bucket, reference_document_ids, required=True
    )
    if source_mode == MockTest.SOURCE_QUESTION_PAPERS:
        return retrieve(
            bucket,
            query=prompt,
            top_k=top_k,
            kinds=[Document.KIND_QUESTION_PAPER],
            document_ids=paper_ids,
        )

    k_notes = max(4, top_k // 2)
    k_papers = max(4, top_k - k_notes)
    notes_nodes = retrieve(
        bucket, query=prompt, top_k=k_notes, kinds=[Document.KIND_NOTES]
    )
    paper_nodes = retrieve(
        bucket,
        query=prompt,
        top_k=k_papers,
        kinds=[Document.KIND_QUESTION_PAPER],
        document_ids=paper_ids,
    )
    merged = notes_nodes + paper_nodes
    merged.sort(key=lambda n: n.get("score") or 0.0, reverse=True)
    return merged[:top_k]


def system_prompt_for_source(source_mode: str) -> str:
    if source_mode == MockTest.SOURCE_QUESTION_PAPERS:
        return _SYSTEM_PAPERS
    if source_mode == MockTest.SOURCE_BOTH:
        return _SYSTEM_BOTH
    return _SYSTEM_NOTES

_GRADE_SYSTEM = (
    "You grade a student's short answer against a model answer for Class XII.\n"
    "Respond with valid JSON only:\n"
    '{ "score": <number 0 to max_marks>, "feedback": "1-3 sentences" }\n'
    "Be fair: award partial credit for partially correct answers. "
    "score must be between 0 and max_marks inclusive."
)


class MockTestGenerationError(Exception):
    pass


def generate_mock_test(
    member: SchoolMembership,
    *,
    bucket_id: int,
    prompt: str,
    title: str = "",
    duration_minutes: int = 60,
    count_mcq: int = 0,
    count_multi: int = 0,
    count_brief: int = 0,
    marks_mcq: int = 1,
    marks_multi: int = 2,
    marks_brief: int = 5,
    results_mode: str = MockTest.RESULTS_AFTER_REVIEW,
    source_mode: str = MockTest.SOURCE_NOTES,
    reference_document_ids: list[int] | None = None,
) -> MockTest:
    prompt = (prompt or "").strip()
    if not prompt:
        raise MockTestGenerationError("Prompt is required.")
    total = count_mcq + count_multi + count_brief
    if total < 1:
        raise MockTestGenerationError("Add at least one question in the blueprint.")
    if total > 40:
        raise MockTestGenerationError("Total questions cannot exceed 40.")
    if duration_minutes < 5 or duration_minutes > 300:
        raise MockTestGenerationError("duration_minutes must be between 5 and 300.")
    if source_mode not in {
        MockTest.SOURCE_NOTES,
        MockTest.SOURCE_QUESTION_PAPERS,
        MockTest.SOURCE_BOTH,
    }:
        source_mode = MockTest.SOURCE_NOTES

    bucket = SubjectBucket.objects.select_related("school").get(pk=bucket_id)
    check_bucket_access(member, bucket)

    kinds = source_mode_to_kinds(source_mode)
    if source_mode == MockTest.SOURCE_NOTES:
        if not get_indexed_documents(bucket, kinds=kinds).exists():
            raise MockTestGenerationError(
                "No indexed notes in this AI Bucket. Upload and index notes first."
            )
    elif source_mode == MockTest.SOURCE_QUESTION_PAPERS:
        _validated_reference_paper_ids(bucket, reference_document_ids, required=True)
    else:
        if not get_indexed_documents(bucket, kinds=[Document.KIND_NOTES]).exists():
            raise MockTestGenerationError(
                "No indexed notes in this AI Bucket. Upload and index notes first."
            )
        _validated_reference_paper_ids(bucket, reference_document_ids, required=True)

    stored_paper_ids: list[int] = []
    if source_mode in (MockTest.SOURCE_QUESTION_PAPERS, MockTest.SOURCE_BOTH):
        stored_paper_ids = _validated_reference_paper_ids(
            bucket, reference_document_ids, required=False
        )

    top_k = max(8, min(24, total + 4))
    try:
        nodes = _retrieve_for_mock(
            bucket,
            prompt=prompt,
            top_k=top_k,
            source_mode=source_mode,
            reference_document_ids=stored_paper_ids or reference_document_ids,
        )
    except Exception as exc:
        logger.exception("Mock test retrieval failed")
        raise MockTestGenerationError("Could not retrieve sources for this topic.") from exc

    if not nodes:
        raise MockTestGenerationError(
            "No matching material found for that topic. Try a more specific prompt "
            "or upload more papers/notes."
        )

    context = build_context(nodes)
    outline = None
    last_err: Exception | None = None
    for _ in range(2):
        try:
            raw = _call_llm_json(
                prompt=prompt,
                context=context,
                count_mcq=count_mcq,
                count_multi=count_multi,
                count_brief=count_brief,
                source_mode=source_mode,
            )
            outline = _parse_outline(
                raw,
                count_mcq=count_mcq,
                count_multi=count_multi,
                count_brief=count_brief,
            )
            break
        except (HarnessLLMError, MockTestGenerationError) as exc:
            last_err = exc
            logger.warning("Mock test generation attempt failed: %s", exc)
    if outline is None:
        raise MockTestGenerationError(
            str(last_err) if last_err else "Failed to generate questions."
        )

    final_title = (title or "").strip()[:255] or outline["title"]

    with transaction.atomic():
        test = MockTest.objects.create(
            school=bucket.school,
            bucket=bucket,
            created_by=member,
            title=final_title,
            topic_prompt=prompt,
            status=MockTest.STATUS_DRAFT,
            question_count=len(outline["questions"]),
            duration_minutes=duration_minutes,
            count_mcq=count_mcq,
            count_multi=count_multi,
            count_brief=count_brief,
            marks_mcq=marks_mcq,
            marks_multi=marks_multi,
            marks_brief=marks_brief,
            source_mode=source_mode,
            results_mode=(
                results_mode
                if results_mode
                in (MockTest.RESULTS_IMMEDIATE, MockTest.RESULTS_AFTER_REVIEW)
                else MockTest.RESULTS_AFTER_REVIEW
            ),
            reference_document_ids=stored_paper_ids,
        )
        rows = []
        for i, q in enumerate(outline["questions"], start=1):
            qtype = q["qtype"]
            if qtype == MockQuestion.TYPE_MCQ:
                marks = marks_mcq
            elif qtype == MockQuestion.TYPE_MULTI:
                marks = marks_multi
            else:
                marks = marks_brief
            rows.append(
                MockQuestion(
                    test=test,
                    order=i,
                    qtype=qtype,
                    prompt=q["prompt"],
                    options=q["options"],
                    correct_indices=q["correct_indices"],
                    model_answer=q.get("model_answer") or "",
                    marks=marks,
                )
            )
        MockQuestion.objects.bulk_create(rows)
    return test


def apply_draft_settings(test: MockTest, updates: dict) -> list[str]:
    """Apply allowed draft settings; returns update_fields. Raises on bad totals."""
    if test.status != MockTest.STATUS_DRAFT:
        raise MockTestGenerationError("Only draft tests can be edited.")
    fields: list[str] = []
    mapping = {
        "title": "title",
        "topic_prompt": "topic_prompt",
        "duration_minutes": "duration_minutes",
        "count_mcq": "count_mcq",
        "count_multi": "count_multi",
        "count_brief": "count_brief",
        "marks_mcq": "marks_mcq",
        "marks_multi": "marks_multi",
        "marks_brief": "marks_brief",
        "results_mode": "results_mode",
        "source_mode": "source_mode",
        "reference_document_ids": "reference_document_ids",
    }
    for key, attr in mapping.items():
        if key not in updates:
            continue
        val = updates[key]
        if key == "title":
            val = str(val).strip()
        elif key == "topic_prompt":
            val = str(val).strip()
            if not val:
                raise MockTestGenerationError("Topic / instructions cannot be empty.")
        elif key == "reference_document_ids":
            if not isinstance(val, list):
                raise MockTestGenerationError("reference_document_ids must be a list.")
            val = _validated_reference_paper_ids(
                test.bucket,
                [int(x) for x in val if x is not None],
                required=test.source_mode
                in (MockTest.SOURCE_QUESTION_PAPERS, MockTest.SOURCE_BOTH),
            )
        setattr(test, attr, val)
        fields.append(attr)

    total = test.count_mcq + test.count_multi + test.count_brief
    if total < 1:
        raise MockTestGenerationError("Add at least one question to the blueprint.")
    if total > 40:
        raise MockTestGenerationError("Total questions cannot exceed 40.")
    if test.duration_minutes < 5 or test.duration_minutes > 300:
        raise MockTestGenerationError("duration_minutes must be between 5 and 300.")
    return fields


def regenerate_questions(
    test: MockTest,
    member: SchoolMembership,
    *,
    overrides: dict | None = None,
) -> MockTest:
    if test.status != MockTest.STATUS_DRAFT:
        raise MockTestGenerationError("Only draft tests can be regenerated.")
    check_bucket_access(member, test.bucket)

    if overrides:
        fields = apply_draft_settings(test, overrides)
        if fields:
            test.save(update_fields=fields)

    # Delete and recreate questions using (possibly updated) blueprint metadata
    new = generate_mock_test(
        member,
        bucket_id=test.bucket_id,
        prompt=test.topic_prompt,
        title=test.title,
        duration_minutes=test.duration_minutes,
        count_mcq=test.count_mcq,
        count_multi=test.count_multi,
        count_brief=test.count_brief,
        marks_mcq=test.marks_mcq,
        marks_multi=test.marks_multi,
        marks_brief=test.marks_brief,
        results_mode=test.results_mode,
        source_mode=test.source_mode,
        reference_document_ids=test.reference_document_ids or None,
    )
    # Move questions onto original test, drop the temp test
    with transaction.atomic():
        test.questions.all().delete()
        new.questions.update(test=test)
        test.question_count = test.questions.count()
        test.title = new.title or test.title
        test.duration_minutes = new.duration_minutes
        test.count_mcq = new.count_mcq
        test.count_multi = new.count_multi
        test.count_brief = new.count_brief
        test.marks_mcq = new.marks_mcq
        test.marks_multi = new.marks_multi
        test.marks_brief = new.marks_brief
        test.results_mode = new.results_mode
        test.source_mode = new.source_mode
        test.reference_document_ids = new.reference_document_ids
        test.save(
            update_fields=[
                "question_count",
                "title",
                "duration_minutes",
                "count_mcq",
                "count_multi",
                "count_brief",
                "marks_mcq",
                "marks_multi",
                "marks_brief",
                "results_mode",
                "source_mode",
                "reference_document_ids",
            ]
        )
        new.delete()
    return test


def _parse_outline(
    raw: str,
    *,
    count_mcq: int,
    count_multi: int,
    count_brief: int,
) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MockTestGenerationError(f"Model returned invalid JSON: {exc}") from exc

    title = str(data.get("title") or "Mock test").strip()[:255] or "Mock test"
    questions_raw = data.get("questions")
    if not isinstance(questions_raw, list) or not questions_raw:
        raise MockTestGenerationError("Model returned no questions.")

    mcqs: list[dict] = []
    multis: list[dict] = []
    briefs: list[dict] = []

    for item in questions_raw:
        if not isinstance(item, dict):
            continue
        parsed = _normalize_question(item)
        if parsed is None:
            continue
        if parsed["qtype"] == MockQuestion.TYPE_MCQ:
            mcqs.append(parsed)
        elif parsed["qtype"] == MockQuestion.TYPE_MULTI:
            multis.append(parsed)
        else:
            briefs.append(parsed)

    questions = (
        _pad_or_trim(mcqs, count_mcq, MockQuestion.TYPE_MCQ)
        + _pad_or_trim(multis, count_multi, MockQuestion.TYPE_MULTI)
        + _pad_or_trim(briefs, count_brief, MockQuestion.TYPE_BRIEF)
    )
    if not questions:
        raise MockTestGenerationError("Model returned empty questions.")
    return {"title": title, "questions": questions}


def _normalize_question(item: dict) -> dict | None:
    qtype = str(item.get("qtype") or MockQuestion.TYPE_MCQ).strip().lower()
    if qtype in ("multiple", "multi_select", "multiselect"):
        qtype = MockQuestion.TYPE_MULTI
    if qtype in ("short", "short_answer", "text"):
        qtype = MockQuestion.TYPE_BRIEF
    if qtype not in (
        MockQuestion.TYPE_MCQ,
        MockQuestion.TYPE_MULTI,
        MockQuestion.TYPE_BRIEF,
    ):
        qtype = MockQuestion.TYPE_MCQ

    q_prompt = str(item.get("prompt") or "").strip()
    if not q_prompt:
        return None

    if qtype == MockQuestion.TYPE_BRIEF:
        model_answer = str(item.get("model_answer") or "").strip()[:4000]
        if not model_answer:
            model_answer = "See teacher notes for expected points."
        return {
            "qtype": qtype,
            "prompt": q_prompt[:2000],
            "options": [],
            "correct_indices": [],
            "model_answer": model_answer,
        }

    options = item.get("options") or []
    if isinstance(options, str):
        options = [options]
    options = [str(o).strip() for o in options if str(o).strip()]
    while len(options) < 4:
        options.append(f"Option {len(options) + 1}")
    options = options[:4]

    indices_raw = item.get("correct_indices")
    if indices_raw is None and item.get("correct_index") is not None:
        indices_raw = [item.get("correct_index")]
    indices: list[int] = []
    if isinstance(indices_raw, list):
        for x in indices_raw:
            try:
                i = int(x)
            except (TypeError, ValueError):
                continue
            if 0 <= i <= 3 and i not in indices:
                indices.append(i)

    if qtype == MockQuestion.TYPE_MCQ:
        if not indices:
            indices = [0]
        indices = indices[:1]
    else:
        if len(indices) < 2:
            # ensure at least two distinct
            indices = sorted(set(indices + [0, 1]))[:2]
            if len(indices) < 2:
                indices = [0, 1]

    return {
        "qtype": qtype,
        "prompt": q_prompt[:2000],
        "options": options,
        "correct_indices": indices,
        "model_answer": "",
    }


def _pad_or_trim(items: list[dict], count: int, qtype: str) -> list[dict]:
    if count <= 0:
        return []
    if len(items) >= count:
        return items[:count]
    if not items:
        # synthesize placeholders so generation never hard-fails on under-delivery
        filler = {
            "qtype": qtype,
            "prompt": f"[{qtype.upper()}] Review the notes and answer carefully.",
            "options": (
                ["Option A", "Option B", "Option C", "Option D"]
                if qtype != MockQuestion.TYPE_BRIEF
                else []
            ),
            "correct_indices": (
                [0]
                if qtype == MockQuestion.TYPE_MCQ
                else ([0, 1] if qtype == MockQuestion.TYPE_MULTI else [])
            ),
            "model_answer": (
                "Key points from the source notes."
                if qtype == MockQuestion.TYPE_BRIEF
                else ""
            ),
        }
        items = [filler]
    while len(items) < count:
        base = dict(items[-1])
        base["prompt"] = f"{base['prompt']} (variant {len(items) + 1})"
        items.append(base)
    return items


def _resolve_model() -> tuple[str, str]:
    """Prefer DeepSeek/Groq chat provider; else Gemini via LiteLLM."""
    try:
        cfg = get_chat_llm()
        return "chat_http", cfg.model
    except RuntimeError:
        pass
    if getattr(settings, "GEMINI_API_KEY", ""):
        return "litellm", getattr(settings, "PAGEINDEX_MODEL", "gemini/gemini-2.5-flash")
    raise HarnessLLMError(
        "No LLM configured. Set DEEPSEEK_API_KEY (preferred), GROQ_API_KEY, or GEMINI_API_KEY."
    )


def _call_llm_json(
    *,
    prompt: str,
    context: str,
    count_mcq: int,
    count_multi: int,
    count_brief: int,
    source_mode: str = MockTest.SOURCE_NOTES,
) -> str:
    user = (
        f"Source excerpts:\n\n{context}\n\n"
        f"Topic / instructions: {prompt}\n"
        f"Create exactly: {count_mcq} mcq, {count_multi} multi, {count_brief} brief."
    )
    messages = [
        {"role": "system", "content": system_prompt_for_source(source_mode)},
        {"role": "user", "content": user},
    ]
    provider, model = _resolve_model()
    if provider == "litellm":
        return _litellm(messages, model, max_tokens=8192)
    try:
        return chat_completion(
            messages,
            temperature=0.3,
            max_tokens=8192,
            response_format={"type": "json_object"},
            timeout=120,
            retries_on_429=1,
        )
    except Exception:
        # Some models reject response_format — retry without it.
        try:
            return chat_completion(
                messages,
                temperature=0.3,
                max_tokens=8192,
                timeout=120,
                retries_on_429=1,
            )
        except Exception as exc:
            raise HarnessLLMError(f"Chat LLM error: {exc}") from exc


def _litellm(messages: list[dict], model: str, max_tokens: int = 4096) -> str:
    try:
        from litellm import completion
    except ImportError as exc:
        raise HarnessLLMError("litellm is not installed") from exc
    try:
        resp = completion(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        try:
            resp = completion(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc2:
            raise HarnessLLMError(f"LiteLLM error: {exc2}") from exc2


def grade_brief_answer(
    *,
    question: MockQuestion,
    student_answer: str,
) -> tuple[float, str]:
    """Return (ai_score, feedback) for a brief question."""
    max_marks = float(question.marks)
    student_answer = (student_answer or "").strip()
    if not student_answer:
        return 0.0, "No answer provided."

    user = (
        f"Question: {question.prompt}\n"
        f"Model answer: {question.model_answer}\n"
        f"Max marks: {max_marks}\n"
        f"Student answer: {student_answer}"
    )
    messages = [
        {"role": "system", "content": _GRADE_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        provider, model = _resolve_model()
        if provider == "litellm":
            raw = _litellm(messages, model, max_tokens=1024)
        else:
            raw = chat_completion(
                messages,
                temperature=0.2,
                max_tokens=1024,
                response_format={"type": "json_object"},
                timeout=60,
            )
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        score = float(data.get("score", 0))
        score = max(0.0, min(max_marks, score))
        feedback = str(data.get("feedback") or "").strip()[:2000]
        return score, feedback or "Graded by AI."
    except Exception:
        logger.exception("AI brief grading failed")
        # Heuristic fallback: keyword overlap
        model_tokens = set(re.findall(r"[a-z0-9]+", question.model_answer.lower()))
        ans_tokens = set(re.findall(r"[a-z0-9]+", student_answer.lower()))
        if not model_tokens:
            return round(max_marks * 0.5, 1), "AI unavailable; provisional half marks."
        overlap = len(model_tokens & ans_tokens) / len(model_tokens)
        score = round(max_marks * min(1.0, overlap * 1.5), 1)
        return score, "AI unavailable; provisional score from keyword overlap."


def email_attempt_result(attempt: MockAttempt) -> str:
    """
    Email score summary to the student.
    Returns: 'sent' | 'skipped_no_email' | 'failed'
    """
    attempt = (
        MockAttempt.objects.select_related(
            "test", "test__school", "student__user"
        ).get(pk=attempt.pk)
    )
    user = attempt.student.user
    to_email = (user.email or "").strip()
    if not to_email:
        return "skipped_no_email"

    name = (user.first_name or user.username or "Student").strip()
    test = attempt.test
    school = test.school.name
    base = getattr(settings, "FRONTEND_BASE_URL", "http://127.0.0.1:5173").rstrip("/")
    link = f"{base}/app/mock-tests/{test.id}/take"
    score_line = f"{attempt.score}/{attempt.max_score} ({attempt.percent}%)"

    # Short question summary for the email body
    review = build_review(attempt, include_ai=False)
    lines = []
    for item in review[:25]:
        if item["qtype"] == "brief":
            earned = item.get("earned_marks")
            mark = f"{earned if earned is not None else '—'}/{item['marks']}"
            lines.append(f"Q{item['order']} (Brief): {mark}")
        else:
            mark = f"{item.get('earned_marks') or 0}/{item['marks']}"
            ok = "correct" if item.get("is_correct") else "incorrect"
            lines.append(f"Q{item['order']} ({item['qtype'].upper()}): {mark} — {ok}")
    summary_block = "\n".join(lines) if lines else "See your panel for full review."

    subject = f"Results released: {test.title}"
    text = (
        f"Hi {name},\n\n"
        f"Your teacher at {school} has released your results for:\n"
        f"  {test.title}\n\n"
        f"Score: {score_line}\n\n"
        f"Breakdown:\n{summary_block}\n\n"
        f"Open your full review here:\n{link}\n\n"
        "— ClassKit\n"
    )
    rows_html = "".join(
        f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e5e7eb;'>"
        f"{line}</td></tr>"
        for line in lines
    ) or (
        "<tr><td style='padding:6px 8px;'>See your panel for full review.</td></tr>"
    )
    html = (
        "<html><body style='font-family:system-ui,sans-serif;color:#111;'>"
        f"<p>Hi {name},</p>"
        f"<p>Your teacher at <strong>{school}</strong> has released your results for:</p>"
        f"<p style='font-size:18px;margin:8px 0;'><strong>{test.title}</strong></p>"
        f"<p style='font-size:22px;color:#0f766e;'><strong>{score_line}</strong></p>"
        "<p style='margin-top:16px;font-weight:600;'>Breakdown</p>"
        f"<table style='border-collapse:collapse;width:100%;max-width:480px;'>{rows_html}</table>"
        f"<p style='margin-top:20px;'><a href=\"{link}\" "
        "style='display:inline-block;background:#0f766e;color:#fff;padding:10px 16px;"
        "border-radius:8px;text-decoration:none;'>View full results</a></p>"
        "<p style='color:#6b7280;font-size:12px;margin-top:24px;'>— ClassKit</p>"
        "</body></html>"
    )
    try:
        send_transactional_email(
            to_email=to_email,
            to_name=name,
            subject=subject,
            text=text,
            html=html,
        )
        return "sent"
    except BrevoError:
        logger.exception("Failed to email mock result to %s", to_email)
        return "failed"


def release_attempt_with_email(
    attempt: MockAttempt, *, by: SchoolMembership | None
) -> dict[str, Any]:
    """Release results to student panel and email the score summary."""
    attempt.release_results(by=by)
    mail_status = email_attempt_result(attempt)
    return {
        "student_id": attempt.student_id,
        "results_released": True,
        "email": mail_status,
    }


def submit_and_grade(attempt: MockAttempt, answers: dict, *, auto: bool = False) -> None:
    """Persist answers, grade objective + AI-suggest briefs, mark submitted."""
    attempt.answers = answers
    attempt.auto_submitted = auto
    attempt.submitted_at = timezone.now()
    attempt.save(update_fields=["answers", "auto_submitted", "submitted_at"])

    brief_qs = list(
        attempt.test.questions.filter(qtype=MockQuestion.TYPE_BRIEF)
    )
    for q in brief_qs:
        raw = answers.get(str(q.id), answers.get(q.id, ""))
        text = str(raw or "").strip()
        ai_score, feedback = grade_brief_answer(question=q, student_answer=text)
        MockAnswerGrade.objects.update_or_create(
            attempt=attempt,
            question=q,
            defaults={
                "student_answer": text,
                "ai_score": ai_score,
                "ai_feedback": feedback,
                "teacher_score": None,
                "teacher_feedback": "",
                "confirmed_at": None,
                "confirmed_by": None,
            },
        )

    attempt.recompute_scores()
    # Immediate mode: student sees score/review right away + email
    if attempt.test.results_mode == MockTest.RESULTS_IMMEDIATE:
        release_attempt_with_email(attempt, by=None)


def build_review(attempt: MockAttempt, *, include_ai: bool = True) -> list[dict[str, Any]]:
    """Per-question review for a submitted attempt."""
    grades = {
        g.question_id: g for g in attempt.answer_grades.select_related("question").all()
    }
    review = []
    for q in attempt.test.questions.all():
        raw = attempt.answers.get(str(q.id))
        if raw is None:
            raw = attempt.answers.get(q.id)

        item: dict[str, Any] = {
            "question_id": q.id,
            "order": q.order,
            "qtype": q.qtype,
            "prompt": q.prompt,
            "options": q.options,
            "marks": q.marks,
            "correct_indices": q.correct_indices,
            "model_answer": q.model_answer if q.qtype == MockQuestion.TYPE_BRIEF else "",
        }

        if q.qtype == MockQuestion.TYPE_MCQ:
            try:
                selected = int(raw) if raw is not None else None
            except (TypeError, ValueError):
                selected = None
            correct = q.correct_indices or []
            correct_i = int(correct[0]) if correct else 0
            item["selected_index"] = selected
            item["selected_indices"] = [selected] if selected is not None else []
            item["is_correct"] = selected is not None and selected == correct_i
            item["earned_marks"] = float(q.marks) if item["is_correct"] else 0.0
        elif q.qtype == MockQuestion.TYPE_MULTI:
            selected_set = _as_set(raw)
            correct_set = set(int(i) for i in (q.correct_indices or []))
            item["selected_index"] = None
            item["selected_indices"] = sorted(selected_set) if selected_set is not None else []
            item["is_correct"] = (
                selected_set is not None
                and selected_set == correct_set
                and bool(correct_set)
            )
            item["earned_marks"] = float(q.marks) if item["is_correct"] else 0.0
        else:
            grade = grades.get(q.id)
            item["selected_index"] = None
            item["selected_indices"] = []
            item["student_answer"] = (
                grade.student_answer if grade else str(raw or "")
            )
            item["is_correct"] = None
            if grade:
                if include_ai:
                    item["ai_score"] = grade.ai_score
                    item["ai_feedback"] = grade.ai_feedback
                item["teacher_score"] = grade.teacher_score
                item["teacher_feedback"] = grade.teacher_feedback
                item["confirmed"] = grade.teacher_score is not None
                item["earned_marks"] = (
                    float(grade.teacher_score)
                    if grade.teacher_score is not None
                    else None
                )
                item["provisional_marks"] = (
                    float(grade.ai_score) if grade.ai_score is not None else None
                )
            else:
                item["ai_score"] = None
                item["ai_feedback"] = ""
                item["teacher_score"] = None
                item["teacher_feedback"] = ""
                item["confirmed"] = False
                item["earned_marks"] = None
                item["provisional_marks"] = None

        review.append(item)
    return review


def _as_set(raw) -> set[int] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        try:
            return {int(x) for x in raw}
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (int, float)):
        return {int(raw)}
    return None
