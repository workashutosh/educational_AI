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

| Role | Buckets | Upload | Ask/Chat | Create buckets | Grant access | Manage members |
|------|---------|--------|----------|----------------|--------------|----------------|
| `admin` | all in school | yes | yes | yes | yes | yes |
| `manager` | all in school | yes | yes | yes | yes | teachers/students only |
| `teacher` | granted only | yes | yes | no | no | no |
| `student` | granted only | **no** | yes | no | no | no |

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

## Non-goals (pilot)

- Multi-region / S3 (interface ready, not required)
- pgvector ANN (add when chunk count hurts)
- Question-paper generation agent (ingestion + chat first)
