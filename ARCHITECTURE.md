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

## Non-goals (pilot)

- Multi-region / S3 (interface ready, not required)
- pgvector ANN (add when chunk count hurts)
- Question-paper generation agent (call `run_query` from a separate app later)
