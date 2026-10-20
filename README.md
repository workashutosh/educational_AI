# ClassKit

Monorepo for school-scoped teacher notes → parse → chunk → embed → RAG Q&A.

| Path | Stack |
|------|--------|
| [`backend/`](backend/) | Django + DRF + Postgres + Celery |
| [`frontend/`](frontend/) | Vite + React + TypeScript + shadcn/ui |
| [`docker-compose.yml`](docker-compose.yml) | Postgres + Redis (run from repo root) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for VPS / tenancy decisions and
[API.md](API.md) for the API guide (mobile apps should use `/api/v1/`).

## Quick start

### Infra (repo root)

```bash
docker compose up -d
# Postgres: education/education@127.0.0.1:5432/education_ai
# Redis: 127.0.0.1:6379
```

### Backend

```bash
cd backend
source .venv/bin/activate   # or: python3 -m venv .venv && pip install -r requirements.txt
cp .env.example .env        # set DATABASE_URL, GROQ_*, etc.
python manage.py migrate
python manage.py seed_pilot
python manage.py runserver
# index uploads (macOS: use solo pool to avoid fork crashes)
OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES celery -A config worker -l info --pool=solo
# digests, parent weekly email, subscription expiry
celery -A config beat -l info
# tests (no external services needed)
python manage.py test
```

- API docs: http://127.0.0.1:8000/api/docs/
- Browser auth: http://127.0.0.1:8000/accounts/login/
- Ops notes: [`backend/deploy/README.md`](backend/deploy/README.md)

Seed password: `changeme123` (`greenfield_admin`, `greenfield_teacher`, … / `riverside_*`).
`seed_pilot` also prints each school’s **join code**.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

- App: http://127.0.0.1:5173/
- Vite proxies `/api`, `/accounts`, `/admin` → `http://127.0.0.1:8000`

Add shadcn components:

```bash
cd frontend
npm_config_cache=../.npm-cache npx --yes shadcn@4.15.0 add card input
```

## Browser accounts

| Path | Purpose |
|------|---------|
| `/` (frontend) | Landing |
| `/onboard` | 3-step school onboarding (form → Brevo email OTP → AI Buckets) |
| `/join` | Join with school join code (teacher/student) |
| `/login` | Sign in |
| `/app` | Dashboard (after login / onboard) |
| `/app/buckets` | List / create AI Buckets |
| `/app/buckets/:id` | Notes · Access (links out to Chat / PPT) |
| `/app/chat` | Chat with history (pick AI Bucket) |
| `/app/ppt` | Create PPT preview + download |
| `/app/mock-tests` | Mock tests — generate, assign, take, scores |
| `/app/students` | Create student logins + roster (admin/manager/teacher) |
| `/app/settings` | Plan, join code, account |
| `/app/question-bank` | Question bank: topics, AI generation, past-paper import, practice tests (staff) |
| `/app/papers` | Question papers with sections + PDF/Word export and answer key (staff) |
| `/app/homework` | Homework: assign, photo/text submissions, AI-suggested marks, return |
| `/app/flashcards` | Flashcard decks + spaced-repetition study |
| `/app/doubts` | Questions the AI couldn't answer, routed to teachers |
| `/app/insights` | Weak-topic analytics (students: My Progress; staff: class heatmap + revision tests) |
| `/app/parents` | Parent logins linked to students (staff) |
| `/app/billing` | Plans, Razorpay checkout, AI usage & cost (admin/manager) |
| `/parent` | Parent portal (read-only child overview) |

Django template fallbacks still exist under `/accounts/...` on the API host.

Default plan after onboard: **5 buckets × 1 GB** each (editable in step 3, or skip).
OTP emails are sent via Brevo (`BREVO_API_KEY` / `BREVO_SENDER_EMAIL` in `backend/.env`).

## Access model

| Role | Access |
|------|--------|
| `admin` / `manager` | All buckets; create buckets; grant access; create students |
| `teacher` | Upload + ask on **granted** buckets; create students |
| `student` | Ask only on **granted** buckets (login with provisioned credentials) |

## API (member)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/buckets/` | Buckets you can access |
| GET/POST | `/api/documents/` | List / upload (students cannot POST) |
| GET | `/api/documents/{id}/status/` | Poll status |
| POST | `/api/query/` | Raw vector search |
| POST | `/api/ask/` | RAG answer (+ optional `session_id`) |
| POST | `/api/harness/query/` | Harness proof: `{bucket_id, query}` → `{answer, sources}` |
| POST | `/api/generate-pptx/` | `{bucket_id, prompt, slide_count}` → JSON outline (preview) |
| POST | `/api/generate-pptx/download/` | `{bucket_id, title, slides}` → `.pptx` download |
| GET/POST | `/api/chat/sessions/` | List / create chat sessions |

**Manager / admin:** `POST /api/admin/buckets/`, grant/revoke access.  
**Admin / manager / teacher:** `POST /api/admin/students/` — create student username+password (optional `bucket_id` grant).  
**Mock tests:** `POST/GET /api/mock-tests/`, assign/publish/submit/results under `/api/mock-tests/{id}/…`.

Auth: session cookie (browser) or `Authorization: Token …` (API).

## Pipeline

```
upload → hash / dedupe
  → parse (PyMuPDF / docx / pptx; PaddleOCR-VL for scans)
  → hierarchical chunks + FastEmbed vectors
  → retrieve (bucket-scoped cosine) → Groq-grounded answer
```

No LLM on the parse → chunk → embed → retrieve path. PageIndex + Gemini remain vendored under `backend/pageindex_repo/` as optional future enrichment only.

## Env highlights (`backend/.env`)

- `DATABASE_URL` — Postgres connection
- `GROQ_API_KEY` — ask/chat answers
- `PADDLEOCR_VL_TOKEN` — scanned PDF/image OCR only
- `ALLOW_OPEN_ASK` — must be `False` on a public VPS
# educational_AI
