from __future__ import annotations

from celery import shared_task


def grade_submission(submission_id: int) -> dict:
    from billing.services.usage import usage_scope

    from .models import Submission
    from .services import ai_grade

    sub = Submission.objects.select_related("assignment").filter(pk=submission_id).first()
    if sub is None:
        return {"ok": False}
    with usage_scope(school_id=sub.assignment.school_id, member_id=sub.student_id, feature="homework"):
        ai_grade(sub)
    return {"ok": True, "ai_status": sub.ai_status}


@shared_task(name="homework.grade_submission", max_retries=0)
def grade_submission_task(submission_id: int) -> dict:
    return grade_submission(submission_id)
