# Small-VPS ops (2-school pilot)

## Infrastructure

Preferred on this Mac for now: **Homebrew PostgreSQL 16/14 + Redis** (already used).

On a real VPS, use Docker Compose from the **repo root**:

```bash
docker compose up -d
# Postgres: education/education@localhost:5432/education_ai (tuned for ~2–4GB RAM)
# Redis: localhost:6379
```

Init SQL is mounted from `backend/deploy/postgres/init.sql`.

## App bring-up

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set DATABASE_URL, GROQ_*, ALLOW_OPEN_ASK=False in prod
python manage.py migrate
python manage.py seed_pilot
python manage.py createsuperuser   # optional platform operator
python manage.py runserver 0.0.0.0:8000
# separate terminal:
celery -A config worker -l info
```

## Frontend (repo root)

```bash
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173 — proxies /api to :8000
```

## Pilot logins (from `seed_pilot`)

Password for all: `changeme123`

| School | Admin | Manager | Teacher | Student |
|--------|-------|---------|---------|---------|
| Greenfield High | `greenfield_admin` | `greenfield_manager` | `greenfield_teacher` | `greenfield_student` |
| Riverside Academy | `riverside_admin` | `riverside_manager` | `riverside_teacher` | `riverside_student` |

DRF tokens are created for each user (usable as `Authorization: Token …`).
Join codes are printed by `seed_pilot` and shown on `/app/` for admins/managers.

## Important flags

- `ALLOW_OPEN_ASK=True` — only for local pilot. **Set False on any public VPS.**
- Files stay on local disk under `backend/media/schools/{school_id}/buckets/{bucket_id}/documents/`.
