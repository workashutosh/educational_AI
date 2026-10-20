from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def run_import_job(job_id: int) -> dict:
    from billing.services.usage import usage_scope

    from .models import BankImportJob
    from .services.bank import BankError, import_from_document

    job = BankImportJob.objects.select_related("document__bucket", "created_by").get(pk=job_id)
    job.status = BankImportJob.STATUS_RUNNING
    job.save(update_fields=["status"])
    try:
        with usage_scope(
            school_id=job.school_id, member_id=job.created_by_id, feature="question_bank"
        ):
            created, skipped = import_from_document(job.document, created_by=job.created_by)
    except BankError as exc:
        job.status = BankImportJob.STATUS_FAILED
        job.error_message = str(exc)
    except Exception:
        logger.exception("bank import failed job=%s", job_id)
        job.status = BankImportJob.STATUS_FAILED
        job.error_message = "Could not extract questions from this paper."
    else:
        job.status = BankImportJob.STATUS_DONE
        job.created_count = created
        job.skipped_duplicates = skipped
    job.finished_at = timezone.now()
    job.save()
    return {"ok": job.status == BankImportJob.STATUS_DONE, "created": job.created_count}


@shared_task(name="question_bank.import_document")
def import_document_task(job_id: int) -> dict:
    return run_import_job(job_id)


@shared_task(name="question_bank.sync_mock_test")
def sync_mock_test_task(test_id: int) -> dict:
    """Save a freshly generated mock test into the bank + tag its topics."""
    from mock_tests.models import MockTest

    from .services.bank import import_from_mock_test

    test = MockTest.objects.select_related("bucket", "created_by").filter(pk=test_id).first()
    if test is None:
        return {"ok": False}
    created, skipped = import_from_mock_test(test)
    return {"ok": True, "created": len(created), "skipped": skipped}
