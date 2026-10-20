# Architecture — locked decisions (2-school VPS pilot)

## Decisions (2026-07-31)

| Topic | Choice | Why |
|-------|--------|-----|
| Hosting | Single VPS + Docker Compose | 2 schools; simple ops; cheap |
| Database | **PostgreSQL 16** (required) | Concurrent uploads, durable chat, ready for pgvector later |
| Cache/queue | Redis 7 | Celery broker + rate limits |
| Files | **Local disk** under `backend/media/schools/...` | Enough for pilot; storage backend swappable to S3 later without model changes |
| Auth | **Django session (web) + DRF Token (API/agents)** | Best for small VPS: no JWT ops burden; tokens for future agent clients |
| Chat history | **Server-side** `ChatSession` + `ChatMessage` | Survives refresh/devices; auditable; required for real product |
| Scale target | 2 schools, tens of teachers/students, thousands of docs | Brute-force embeddings per bucket stay fine |

## Roles (school-scoped)

| Role | Buckets | Upload | Ask/Chat | Create buckets | Grant access | Create students |
|------|---------|--------|----------|----------------|--------------|----------------|
| `admin` | all in school | yes | yes | yes | yes | yes |
| `manager` | all in school | yes | yes | yes | yes | yes |
| `teacher` | granted only | yes | yes | no | no | yes |
| `student` | granted only | **no** | yes | no | no | no |
| parent (not a member) | — | — | — | — | — | — (read-only portal for linked children) |

Student logins: `POST /api/admin/students/` (admin/manager/teacher) sets username+password; student signs in at `/api/auth/login/`. Optional `bucket_id` grants access at create time. `School.max_users` (when &gt; 0) caps total active memberships.

Platform operator = Django `is_superuser` (create schools, first admin).

## Access rule

A member may act on a bucket if same `school_id` and:

- role ∈ {`admin`, `manager`}, **or**
- a `BucketAccess` row exists for (member, bucket)

Uploads additionally require role ∈ {`admin`, `manager`, `teacher`}.

## VPS topology

```text
┌─────────────────────────────────────────────┐
│  VPS (e.g. 2–4 GB RAM)                      │
│  docker compose:                            │
│    postgres  (tuned: low shared_buffers)    │
│    redis                                        │
│  host (or containers):                      │
│    gunicorn (Django)                        │
│    celery worker                            │
│    nginx → static/media + proxy             │
│  disk: ./media  (bind-mounted)              │
└─────────────────────────────────────────────┘
```

## Mock tests (`mock_tests`)

Teachers configure a blueprint (duration, MCQ / multi-select / brief counts + marks), generate from an AI Bucket via RAG + LLM, preview/edit, then assign and publish. Students get a timed attempt. Objective items auto-grade; brief answers get an AI provisional score that teachers confirm or override before the official result is final.

## RAG harness (`rag_harness`)

Shared query/retrieval layer for future agents. **Only import** `rag_harness.agent.run_query`.

```text
check_bucket_access → indexed Documents → retrieve → build_context → LLM → {answer, sources}
```

Proof endpoint: `POST /api/harness/query/` `{bucket_id, query}`.

Retrieval uses PageIndex tree-search when trees include node text; otherwise embedding `search_bucket` (current indexing path). LLM reuses `GROQ_*` / `PAGEINDEX_MODEL` + `GEMINI_API_KEY` via LiteLLM.

## Feature apps (2026-10)

| App | Owns |
|---|---|
| `question_bank` | Topics (from note headings, no LLM), bank questions (dedupe by normalized prompt hash), past-paper import, question papers + PDF/DOCX export |
| `learning` | Flashcards + SM-2 scheduling, doubts (auto-opened when a student's question isn't in the notes), chat answer feedback |
| `homework` | Assignments, submissions (text + photos/files, OCR'd with the notes parser), AI-suggested marks, release |
| `analytics` | Per-topic accuracy from mock tests, quick checks, and flashcards; class heatmap; remediation tests |
| `school_ops` | Attendance (auto from lecture-room joins), parent accounts + portal |
| `billing` | Plans (code-defined), Razorpay orders/webhook, usage metering + monthly AI quota |

Decisions:

- **Parents are not `SchoolMembership` rows.** Every existing endpoint gates on `IsSchoolMember`, so a parent account can only reach `/api/parent/…`, which checks `ParentLink`.
- **Topics come from chunk heading paths** (numbered section, else chapter). Tagging a question = nearest note chunk by embedding, so it costs no LLM tokens.
- **Metering:** a request/task `usage_scope` plus the shared `llm_provider` records tokens per school. OCR pages and transcription minutes are recorded at their call sites.
- **pgvector is optional.** Migration `ingestion.0007` adds `embedding_vec vector(384)` + HNSW if the extension can be created. Retrieval uses it when present and falls back to numpy otherwise. `manage.py vector_index --backfill`.
- **API versioning:** `/api/v1/` mirrors `/api/`. Token auth comes before session auth so a bad token is a 401.

## Non-goals (pilot)

- Multi-region / S3 (interface ready, not required)
- Push delivery (device tokens are stored; FCM/APNs sending not wired)
