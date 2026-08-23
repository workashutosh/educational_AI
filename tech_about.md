# ClassKit — Technical Overview

Developer-facing reference for the **education_AI** monorepo (product name: **ClassKit**).  
For a non-technical product summary, see [`about.md`](about.md). For locked architecture decisions, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## What this system does

ClassKit is a **school-scoped** platform that:

1. Ingests teacher materials (notes, previous-year question papers) into **AI Buckets**
2. Indexes them with **structure-aware chunking + local embeddings** (no LLM on the ingest path)
3. Serves **grounded Q&A**, **PowerPoint generation**, **mock tests**, **lectures**, and **engagement loops** on top of that index

Every school is a tenant. Data and access are isolated by `school_id`. A user belongs to one school via `SchoolMembership`.

---

## Repository layout

| Path | Purpose |
|------|---------|
| [`backend/`](backend/) | Django 5 + DRF API, Celery workers, ingestion/RAG logic |
| [`frontend/`](frontend/) | Vite + React 19 + TypeScript SPA |
| [`e2e/`](e2e/) | Playwright end-to-end tests |
| [`docker-compose.yml`](docker-compose.yml) | Postgres 16 + Redis 7 for local/pilot |
| [`dev.sh`](dev.sh) | One-command dev: Docker infra + Django + Celery + Vite |
| [`QuestionPaper/`](QuestionPaper/) | Sample PDFs (not wired into runtime) |
| [`backend/pageindex_repo/`](backend/pageindex_repo/) | Vendored PageIndex (optional tree enrichment) |

---

## Stack summary

| Layer | Technology |
|-------|------------|
| API | Django, Django REST Framework, drf-spectacular (OpenAPI) |
| DB | PostgreSQL 16 (required in production; SQLite fallback in dev if unset) |
| Queue | Celery + Redis |
| Auth | Django sessions (browser) + DRF Token (API/scripts) |
| Frontend | React 19, React Router 7, Vite 8, Tailwind CSS 4, shadcn/base-ui |
| Embeddings | FastEmbed — `BAAI/bge-small-en-v1.5` (local, stored as JSON on `Chunk`) |
| Chat LLM | **DeepSeek** (`deepseek-v4-flash`) preferred; **Groq** fallback |
| OCR | PaddleOCR-VL hosted API (scanned PDFs / images only) |
| Email | Brevo (onboarding OTP, mock-test result release) |
| Meetings | Microsoft Graph (optional Teams links for lectures) |
| PPTX export | `python-pptx` |

---

## High-level architecture

```text
┌──────────────┐     HTTPS      ┌─────────────────────────────────────────┐
│  React SPA   │ ─────────────► │  Django (gunicorn/runserver)            │
│  :5173 dev   │   /api/*       │  DRF views + permissions                │
└──────────────┘                └───────────┬─────────────────────────────┘
                                            │
                    ┌───────────────────────┼───────────────────────┐
                    ▼                       ▼                       ▼
              PostgreSQL                 Redis                  local disk
           (models, chat, tests)      (Celery broker)         backend/media/
                    ▲                       │
                    │                       ▼
                    │               Celery worker
                    │         (parse → chunk → embed → index)
                    └──────────────────────────────────────────
```

### Pilot hosting target

Single VPS, Docker Compose for Postgres/Redis, Django + Celery on host or in containers, nginx for static/media. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`backend/deploy/README.md`](backend/deploy/README.md).

**Non-goals (pilot):** multi-region, S3 (interface-ready via `MEDIA_ROOT`), pgvector ANN, billing.

---

## Django applications

| App | Responsibility |
|-----|----------------|
| **`ingestion`** | Schools, buckets, documents, chunks, embeddings, chat sessions, auth API, upload/parse/index pipeline, `/api/ask/`, PPT generation |
| **`rag_harness`** | Shared retrieval + `run_query()` for future agents; proof endpoint `/api/harness/query/` |
| **`mock_tests`** | Blueprint → generate → assign → timed take → grade → release results |
| **`lectures`** | Schedule lectures, lecture room, optional Teams meeting via MS Graph OAuth |
| **`engagement`** | Streaks, micro-quizzes, mastery bars, notifications, digests, leaderboards, teacher “time saved” |

Root URL config: [`backend/config/urls.py`](backend/config/urls.py).

---

## Core data model (ingestion)

| Model | Role |
|-------|------|
| `School` | Tenant; join code, plan limits (`max_buckets`, `bucket_quota_bytes`, `max_users`) |
| `SchoolMembership` | User ↔ school; role: `admin`, `manager`, `teacher`, `student` |
| `SubjectBucket` | Subject/class folder within a school |
| `BucketAccess` | Grants teachers/students access to specific buckets |
| `Document` | Uploaded file; `kind`: `notes` \| `question_paper`; status lifecycle |
| `Chunk` | Text segment + JSON embedding + heading path + page range |
| `ChatSession` / `ChatMessage` | Persistent chat history per member + bucket |
| `PendingOnboard` | Email OTP flow for new school signup |

Document status flow: `queued` → `parsing` → `indexing` → `indexed` (or `failed` / `duplicate`).  
`Document.progress_message` exposes live OCR/index progress to the UI (e.g. `Reading (4/16 pages)`).

Media path pattern: `media/schools/{school_id}/buckets/{bucket_id}/...`

---

## Access control (RBAC)

| Role | All buckets | Upload | Chat/ask | Create buckets | Grant access | Create students | Mock tests |
|------|-------------|--------|----------|----------------|--------------|-----------------|------------|
| `admin` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `manager` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `teacher` | granted only | ✓ | ✓ | — | — | ✓ | ✓ (own drafts) |
| `student` | granted only | — | ✓ | — | — | — | take assigned |

Enforced in [`backend/ingestion/permissions.py`](backend/ingestion/permissions.py) and per-view checks (e.g. mock test `created_by` for teachers).

Students are provisioned via `POST /api/admin/students/` or `POST /api/admin/members/create/` with optional `bucket_ids`.

---

## Ingestion pipeline

**Entry:** `POST /api/documents/` (multipart: `file`, `bucket_id`, `kind`)  
**Worker:** `ingestion.tasks.process_document` (Celery)

```text
upload → SHA-256 dedupe (per bucket)
  → parse
       · PDF: PyMuPDF text layer; page-by-page PNG + PaddleOCR-VL if scan
       · DOCX / PPTX: native extract
       · Images: OCR
  → index
       · hierarchical chunking (headings, overlap)
       · FastEmbed vectors stored on Chunk rows
       · lightweight pageindex_tree (structure summary, no LLM on default path)
  → status = indexed
```

Key modules:

- [`parse_service.py`](backend/ingestion/services/parse_service.py) — parsing + OCR
- [`chunk_service.py`](backend/ingestion/services/chunk_service.py) — structure-aware splits
- [`embedding_service.py`](backend/ingestion/services/embedding_service.py) — FastEmbed
- [`indexing_service.py`](backend/ingestion/services/indexing_service.py) — persists chunks + tree
- [`retrieval_service.py`](backend/ingestion/services/retrieval_service.py) — bucket-scoped cosine search

**Important:** Parse → chunk → embed → retrieve does **not** call an LLM. Quota-sensitive work is isolated to chat/generation features.

---

## RAG & chat

### Retrieval

1. Embed query locally (same model as chunks)
2. Brute-force cosine similarity over chunks in bucket (optionally filter by `document.kind` or `document_ids`)
3. Optional ±1 neighbor expansion (`RAG_EXPAND_NEIGHBORS`) to keep Q/A pairs together
4. Score floor: `RAG_MIN_SCORE` — below threshold → no LLM call

PageIndex tree search is used when stored trees include node text; otherwise embedding search (current default).

### `/api/ask/` (product chat)

- Retrieves top-k chunks, builds numbered context
- Calls shared [`llm_provider.py`](backend/ingestion/services/llm_provider.py) (DeepSeek → Groq)
- Returns answer + sources + optional follow-up suggestions
- Supports `session_id` for history persistence
- Frontend: [`ChatPage.tsx`](frontend/src/pages/app/ChatPage.tsx) with KaTeX rendering in [`RichAnswer.tsx`](frontend/src/components/chat/RichAnswer.tsx)

### RAG harness

- Public API for agents: `rag_harness.agent.run_query(member, bucket_id, query)`
- HTTP: `POST /api/harness/query/`
- Same retrieval stack; intended as the **only** import surface for new agents

---

## LLM usage map

| Feature | LLM? | Provider module |
|---------|------|-----------------|
| Ingest / embed / retrieve | No | — |
| Chat `/api/ask/` | Yes | `llm_provider` |
| PPT outline | Yes | `pptx_service` |
| Mock test generation | Yes | `mock_tests/services.py` |
| Brief answer grading (AI suggest) | Yes | `mock_tests/services.py` |
| Micro-quiz generation | Yes | `engagement/services/micro_quiz.py` |
| PageIndex enrichment (optional) | Yes (Gemini via LiteLLM) | `pageindex_service` |

Chat config (see [`settings.py`](backend/config/settings.py)):

- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` (default `deepseek-v4-flash`)
- `GROQ_API_KEY`, `GROQ_MODEL` (fallback)
- `GEMINI_API_KEY`, `PAGEINDEX_MODEL` (optional PageIndex path)

---

## Feature modules (backend)

### PowerPoint — `ingestion/services/pptx_service.py`

- `POST /api/generate-pptx/` — RAG + LLM → JSON outline (preview)
- `POST /api/generate-pptx/download/` — build `.pptx` from outline
- **Styles:** `creative`, `clean`, `bold`, `sunset`, `ocean`
- **Slide layouts:** `standard`, `hook`, `compare`, `quiz`, `quote`, `summary`
- Creative mode uses higher temperature and varied layout instructions
- Export uses `python-pptx` with themed backgrounds, accent bars, callout boxes

### Mock tests — `mock_tests/`

- Blueprint: MCQ / multi-select / brief counts, marks, duration, `source_mode`
- **Sources:** notes only, question papers only, or both
- **`reference_document_ids`** — subset of indexed papers when using papers
- Generate → edit questions → assign students → publish → timed attempt
- Auto-grade objective; AI provisional + teacher confirm for brief
- `results_mode`: `immediate` \| `after_review`
- Optional class leaderboard (`engagement` app)
- Frontend copy protection during active attempts (`exam-secure` CSS + event handlers)

### Lectures — `lectures/`

- CRUD lectures linked to buckets
- **Lecture room:** notes panel + in-room AI ask
- Teams: delegated OAuth (`MS_GRAPH_*`) or manual meeting URL
- Setup: [`backend/lectures/SETUP_TEAMS.md`](backend/lectures/SETUP_TEAMS.md)

### Engagement — `engagement/`

- **Streaks** — daily activity from ask / micro-quiz / mock submit
- **Micro-quizzes** — 3 questions after document index or lecture end
- **Mastery** — per-bucket progress bars
- **Notifications** — in-app bell + optional email digests (Celery Beat)
- **Teacher impact** — estimated time saved from AI-generated tests/PPTs
- **Leaderboards** — opt-in per mock test

---

## Frontend architecture

- **Entry:** [`frontend/src/main.tsx`](frontend/src/main.tsx) → [`App.tsx`](frontend/src/App.tsx)
- **Auth:** [`lib/auth.tsx`](frontend/src/lib/auth.tsx) — `GET /api/auth/me/` on load; token in `localStorage` for API calls
- **API client:** [`lib/api.ts`](frontend/src/lib/api.ts) — JSON + blob download helpers
- **Layout:** [`AppLayout.tsx`](frontend/src/components/app/AppLayout.tsx) — sidebar nav; full-bleed workspace for chat/PPT
- **Role gates:** [`RoleGate.tsx`](frontend/src/components/app/RoleGate.tsx)

### Main routes

| Route | Page | Access |
|-------|------|--------|
| `/`, `/login`, `/onboard`, `/join` | Auth / marketing | Public |
| `/app` | Dashboard | Authenticated |
| `/app/buckets`, `/app/buckets/:id` | AI Bucket list & detail | Staff |
| `/app/chat` | Chat + history | All (bucket-scoped) |
| `/app/ppt` | Create PPT | Staff |
| `/app/mock-tests/*` | Mock test lifecycle | Staff + students |
| `/app/lectures`, `/app/lectures/:id` | Lectures & room | All (scoped) |
| `/app/members`, `/app/students` | Roster | Manager/admin or teachers |
| `/app/settings` | School settings | Authenticated |

Vite dev server proxies `/api`, `/accounts`, `/admin` → `http://127.0.0.1:8000`.

UI: Tailwind 4, shadcn-style components, KaTeX (CDN) for math in chat, dark auth shell ([`AuthShell.tsx`](frontend/src/pages/AuthShell.tsx)).

---

## API surface (selected)

OpenAPI: `http://127.0.0.1:8000/api/docs/`

### Auth (`/api/auth/`)

| Method | Path | Notes |
|--------|------|-------|
| POST | `login/` | Returns token + session payload |
| GET | `me/` | School, role, buckets, capabilities |
| POST | `onboard/start/` … `complete/` | OTP school signup |
| POST | `register/join/` | Join code flow |

### Ingestion & chat

| Method | Path | Notes |
|--------|------|-------|
| GET/POST | `/api/documents/` | List / upload |
| GET | `/api/documents/{id}/status/` | Poll processing |
| GET | `/api/documents/{id}/pages/{n}/` | PDF page PNG preview |
| POST | `/api/ask/` | RAG answer |
| POST | `/api/query/` | Raw vector search (debug) |
| GET/POST | `/api/chat/sessions/` | Chat history |

### Generation

| Method | Path | Body highlights |
|--------|------|-----------------|
| POST | `/api/generate-pptx/` | `bucket_id`, `prompt`, `slide_count`, `style` |
| POST | `/api/generate-pptx/download/` | `title`, `slides[]`, `style` |

### Mock tests (`/api/mock-tests/`)

Create, regenerate, assign, publish, start, submit, results release, per-question PATCH, leaderboard settings — see [`mock_tests/urls.py`](backend/mock_tests/urls.py).

### Engagement (`/api/engagement/`)

Dashboard stats, micro-quizzes, notifications, leaderboard — see [`engagement/urls.py`](backend/engagement/urls.py).

### Admin

| Method | Path |
|--------|------|
| POST | `/api/admin/buckets/` |
| GET/POST | `/api/admin/members/` |
| PUT | `/api/admin/members/{id}/access/` |
| POST | `/api/admin/buckets/{id}/grant/` |

---

## Background jobs

| Task | Trigger |
|------|---------|
| `process_document` | After upload (Celery) |
| `engagement.send_teacher_daily_digests` | Celery Beat (~24h) |
| `engagement.send_student_weekly_digests` | Celery Beat (~7d) |
| Micro-quiz generation | After document indexed / lecture ended (engagement tasks) |

**macOS dev note:** run Celery with `--pool=solo` and `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` (see [`dev.sh`](dev.sh)) to avoid fork crashes with ML libs.

---

## Environment variables

Copy [`backend/.env.example`](backend/.env.example) → `backend/.env`.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres connection string |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | Redis |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Django core |
| `DEEPSEEK_*` / `GROQ_*` | Chat LLM |
| `EMBEDDING_MODEL`, `CHUNK_*`, `RAG_*` | Retrieval tuning |
| `PADDLEOCR_VL_TOKEN` | OCR for scans |
| `BREVO_*`, `FRONTEND_BASE_URL` | Email + links in mail |
| `MS_GRAPH_*` | Teams meetings |
| `ALLOW_OPEN_ASK` | **Must be `False` on public VPS** |
| `MAX_UPLOAD_BYTES` | Upload size cap (default 50 MB) |
| `MEDIA_ROOT` | Local file storage root |

---

## Local development

```bash
# From repo root
docker compose up -d          # Postgres + Redis
./dev.sh                      # migrate + Django + Celery + Vite

# Or manually:
cd backend && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill keys
python manage.py migrate
python manage.py seed_pilot   # demo schools/users (password: changeme123)
python manage.py runserver
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -l info --pool=solo

cd frontend && npm install && npm run dev
```

- App: http://127.0.0.1:5173/
- API docs: http://127.0.0.1:8000/api/docs/

**Celery must be running** for document indexing. Without it, uploads stay on “Waiting…”.

---

## Testing

| Suite | Command |
|-------|---------|
| Backend ingestion verify | `python manage.py test_ingestion` / `verify_ingest` |
| E2E (Playwright) | `cd e2e && npm install && npm test` — RBAC smoke tests in [`e2e/tests/rbac.spec.ts`](e2e/tests/rbac.spec.ts) |
| Frontend lint | `cd frontend && npm run lint` |

---

## Security notes

- All API endpoints default to `IsAuthenticated`; bucket access enforced per request
- CSRF: session auth for same-origin SPA; token auth for scripts
- Student mock-test UI: client-side copy/select blocking during attempts (not a DRM substitute)
- Secrets only in `backend/.env` — never commit `.env`
- `ALLOW_OPEN_ASK=False` in production closes unauthenticated `/api/ask/` abuse
- Upload dedupe by hash per bucket prevents re-OCR waste

---

## Extension points

1. **New AI features** — call `rag_harness.agent.run_query()` or `retrieval_service.search_bucket()` + `llm_provider.chat_completion()`
2. **New document kinds** — extend `Document.KIND_*`, parse path, and UI filters
3. **Storage** — swap `MEDIA_ROOT` / custom Django storage without model changes
4. **Vector DB** — replace brute-force cosine in `retrieval_service.py` when chunk counts grow (pgvector planned)

---

## Related docs

| File | Audience |
|------|----------|
| [`about.md`](about.md) | Teachers / school leaders |
| [`README.md`](README.md) | Quick start |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Locked pilot decisions |
| [`intructions.md`](intructions.md) | Ingestion API notes |
| [`backend/lectures/SETUP_TEAMS.md`](backend/lectures/SETUP_TEAMS.md) | Microsoft Teams OAuth |
| [`backend/deploy/README.md`](backend/deploy/README.md) | VPS deployment |
| [`e2e/README.md`](e2e/README.md) | Playwright setup |

---

*Last updated: March 2026 — reflects DeepSeek chat LLM, creative PPT styles, mock-test paper selection, chat layout, and exam copy protection.*
