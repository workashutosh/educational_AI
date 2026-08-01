# Build: Teacher Notes Ingestion Pipeline (PageIndex-based)

## Context
Django + PostgreSQL backend (existing project). Building the ingestion half of
a system that will later power an AI agent generating question papers, mock
tests, notes, and PPTs from teacher-uploaded notes. This task is ONLY
ingestion: upload → parse → build PageIndex tree → store → basic query
endpoint. Do not build the generation/agent side yet.

## Stack
- Django + Django REST Framework
- PostgreSQL for all storage (relational data AND the PageIndex tree, as JSON)
- Docling (https://github.com/docling-project/docling) — parses PDF/docx/pptx/
  images into clean text/PDF locally, handles OCR and tables, no external API
- **PageIndex**, self-hosted (https://github.com/VectifyAI/PageIndex) — builds
  a hierarchical tree index per document and answers queries via LLM reasoning
  over that tree. NOT pgvector. NOT embeddings. NOT a vector DB.
  `git clone https://github.com/VectifyAI/PageIndex.git && pip3 install -r requirements.txt`
- PageIndex uses LiteLLM under the hood — point it at the existing NVIDIA NIM
  (Qwen 2.5 72B) endpoint via `.env`/config, not OpenAI. Model is swappable
  later via config only, no code changes.
- Celery — tree-building must not block the upload request

## Data model
Institutional buckets, scoped by subject + grade level within a school.
Access is admin-granted only — no self-serve.

```python
class School(models.Model):
    name = models.CharField(max_length=255)

class Teacher(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    is_admin = models.BooleanField(default=False)  # implicit access to all buckets in own school

class SubjectBucket(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)                    # "Physics"
    grade_level = models.CharField(max_length=50, blank=True)  # "Class 12"
    class Meta:
        unique_together = ("school", "name", "grade_level")

class TeacherBucketAccess(models.Model):
    """No row = no access, unless teacher.is_admin. Sole access gate for
    both upload and query."""
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE)
    granted_by = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True, related_name="+")
    granted_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        unique_together = ("teacher", "bucket")

class Document(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("parsing", "Parsing"),
        ("indexing", "Indexing"),       # PageIndex tree-building
        ("indexed", "Indexed"),
        ("duplicate", "Duplicate"),
        ("failed", "Failed"),
    ]
    bucket = models.ForeignKey(SubjectBucket, on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(Teacher, on_delete=models.SET_NULL, null=True)  # attribution only
    file = models.FileField(upload_to="teacher_notes/%Y/%m/")
    original_filename = models.CharField(max_length=500)
    file_hash = models.CharField(max_length=64, db_index=True)  # sha256 of raw file bytes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    error_message = models.TextField(blank=True)
    page_count = models.IntegerField(null=True, blank=True)
    pageindex_tree = models.JSONField(null=True, blank=True)   # the tree itself, stored directly
    duplicate_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
```

**Access rule, enforced everywhere**: a teacher may upload to or query a
bucket if `teacher.is_admin == True` OR a `TeacherBucketAccess` row exists for
`(teacher, bucket)`. One shared DRF permission class, not per-view checks.
Bucket creation and access grants are admin-only.

**Dedup rule (simple, file-level — no chunk-level dedup since there are no
chunks)**: on upload, compute `file_hash` (sha256 of the raw file). If a
`Document` with the same `file_hash` already exists and is `indexed` in the
same bucket, set the new upload's status to `duplicate`, point `duplicate_of`
at the original, and skip processing entirely. This only catches exact
re-uploads, not edited versions — that's an acceptable v1 limitation.

## API endpoints (DRF)

Teacher-facing (require bucket access per the rule above):
1. `GET /api/buckets/` — buckets the requester has access to
2. `POST /api/documents/` — multipart upload (`file`, `bucket_id`). Computes
   `file_hash` immediately; if duplicate, returns status `duplicate` without
   processing. Otherwise creates `Document` (status `queued`), triggers
   `process_document.delay(document_id)`, returns immediately.
3. `GET /api/documents/` — list, filterable by `bucket_id`/`status`
4. `GET /api/documents/{id}/status/` — poll: `{status, error_message, duplicate_of}`
5. `POST /api/query/` — `{query, bucket_id, top_k?}` — runs PageIndex tree
   search scoped to documents in that bucket, requester must have access.
   Returns matched sections with page/section references. For testing
   retrieval quality — not the final agent endpoint.

Admin-only (`teacher.is_admin == True`):
6. `POST /api/admin/buckets/` — create bucket (`name`, `grade_level`)
7. `POST /api/admin/buckets/{id}/grant/` — `{teacher_id}` → grant access
8. `DELETE /api/admin/buckets/{id}/grant/{teacher_id}/` — revoke access
9. `GET /api/admin/buckets/{id}/access/` — list teachers with access

## Celery task: process_document
```
1. Compute file_hash; if duplicate exists → status="duplicate", stop
2. status="parsing" → run Docling → clean text/PDF
   on failure: status="failed", save error_message, stop
3. status="indexing" → run PageIndex tree-building against the NIM/Qwen
   endpoint, on the Docling output
   on failure: status="failed", save error_message, stop
4. Save result to pageindex_tree, page_count
5. status="indexed", processed_at=now()
```
Wrap each stage in try/except with a human-readable error_message, not a raw
stack trace.

## Query flow
`POST /api/query/` → load `pageindex_tree` for each `indexed` Document in the
requested bucket → run PageIndex's tree-search reasoning step (LLM call,
against the same NIM/Qwen endpoint) → return matched nodes with their
page/section reference and text.

## What NOT to build yet
- No hybrid search, no reranking (not applicable — no vectors)
- No generation/agent endpoints (question papers, PPTs, etc.)
- No cross-document dedup beyond exact file-hash match
- No academic-year scoping on buckets yet

## Deliverables
- Django app `ingestion` with the models, migrations, DRF views/serializers/urls above
- Celery task wired to existing Celery config (check for existing `celery.py`; create if missing)
- Local clone of PageIndex, configured against the existing NIM/Qwen endpoint via LiteLLM
- A management command `test_ingestion <file_path> <bucket_id>` that runs the
  pipeline synchronously (no Celery) for local debugging
- requirements additions: `docling`, `celery` (if not present); PageIndex
  installed separately per its own requirements.txt, not via pip

Ask before assuming existing Celery/Redis config — check the project first.