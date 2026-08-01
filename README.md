# Education AI

Monorepo for school-scoped teacher notes → parse → chunk → embed → RAG Q&A.

| Path | Stack |
|------|--------|
| [`backend/`](backend/) | Django + DRF + Postgres + Celery |
| [`frontend/`](frontend/) | Vite + React + TypeScript + shadcn/ui |
| [`docker-compose.yml`](docker-compose.yml) | Postgres + Redis (run from repo root) |

See [ARCHITECTURE.md](ARCHITECTURE.md) for VPS / tenancy decisions.

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
| `/app/buckets/:id` | Ask · Notes (upload) · Access (grant/revoke) |
| `/app/settings` | Plan, join code, account |

Django template fallbacks still exist under `/accounts/...` on the API host.

Default plan after onboard: **5 buckets × 1 GB** each (editable in step 3, or skip).
OTP emails are sent via Brevo (`BREVO_API_KEY` / `BREVO_SENDER_EMAIL` in `backend/.env`).

## Access model

| Role | Access |
|------|--------|
| `admin` / `manager` | All buckets in school; create buckets; grant access |
| `teacher` | Upload + ask on **granted** buckets |
| `student` | Ask only on **granted** buckets |

## API (member)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/buckets/` | Buckets you can access |
| GET/POST | `/api/documents/` | List / upload (students cannot POST) |
| GET | `/api/documents/{id}/status/` | Poll status |
| POST | `/api/query/` | Raw vector search |
| POST | `/api/ask/` | RAG answer (+ optional `session_id`) |
| GET/POST | `/api/chat/sessions/` | List / create chat sessions |

**Manager / admin:** `POST /api/admin/buckets/`, grant/revoke access endpoints.

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
