"""
Django settings for the teacher-notes ingestion backend.
"""
import os
import sys
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# Make the local PageIndex clone importable as `pageindex`
PAGEINDEX_REPO = BASE_DIR / "pageindex_repo"
if PAGEINDEX_REPO.exists() and str(PAGEINDEX_REPO) not in sys.path:
    sys.path.insert(0, str(PAGEINDEX_REPO))

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "drf_spectacular",
    # Local
    "ingestion",
    "rag_harness",
    "mock_tests",
    "lectures",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_ROOT", default="media")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Teacher Notes Ingestion API",
    "DESCRIPTION": "Upload → parse (PaddleOCR-VL OCR fallback) → PageIndex tree → query",
    "VERSION": "0.1.0",
}

CORS_ALLOW_ALL_ORIGINS = DEBUG

# ---------------------------------------------------------------------------
# Celery (Redis broker — greenfield; no prior Celery config existed)
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# ---------------------------------------------------------------------------
# LiteLLM → Google Gemini (Google AI Studio)
#
# Used for PageIndex tree building + tree-search query
# (ingestion/services/pageindex_service.py). Swappable via env only — no code
# changes needed. PAGEINDEX_LLM_RPM throttles our own call rate to stay under
# whatever RPM the API key's project/tier allows (see pageindex_repo/pageindex/utils.py).
#
# OCR fallback for scanned PDFs/images uses the hosted PaddleOCR-VL API
# (AI Studio) — no local paddle/paddlex install (ingestion/services/parse_service.py).
# ---------------------------------------------------------------------------
PAGEINDEX_MODEL = env("PAGEINDEX_MODEL", default="gemini/gemini-2.5-flash")
PAGEINDEX_WORKSPACE = BASE_DIR / env("PAGEINDEX_WORKSPACE", default="media/pageindex_workspace")

GEMINI_API_KEY = env("GEMINI_API_KEY", default="")
if GEMINI_API_KEY:
    os.environ.setdefault("GEMINI_API_KEY", GEMINI_API_KEY)

# ---------------------------------------------------------------------------
# Retrieval pipeline — structure-aware chunking + local embeddings.
# No LLM/API in this path at all (see ingestion/services/{chunk,embedding,
# indexing,retrieval}_service.py) — it must never depend on anyone's quota.
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="BAAI/bge-small-en-v1.5")
CHUNK_MAX_CHARS = env.int("CHUNK_MAX_CHARS", default=3200)
CHUNK_OVERLAP_CHARS = env.int("CHUNK_OVERLAP_CHARS", default=320)

# ---------------------------------------------------------------------------
# Groq — the only LLM call anywhere in this pipeline: query-time answer
# generation on top of retrieval (ingestion/services/answer_service.py,
# POST /api/ask/). One call per question, free tier, OpenAI-compatible API.
# ---------------------------------------------------------------------------
GROQ_API_KEY = env("GROQ_API_KEY", default="")
GROQ_MODEL = env("GROQ_MODEL", default="llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# RAG harness (rag_harness.agent.run_query) — shared query/retrieval layer
# for future agents. Reuses GROQ_* / PAGEINDEX_MODEL + GEMINI_API_KEY above.
# ---------------------------------------------------------------------------
RAG_HARNESS_TOP_K = env.int("RAG_HARNESS_TOP_K", default=5)
RAG_HARNESS_MAX_CONTEXT_CHARS = env.int("RAG_HARNESS_MAX_CONTEXT_CHARS", default=12000)

# ---------------------------------------------------------------------------
# Brevo — transactional email for onboarding OTP
# https://developers.brevo.com/docs/send-a-transactional-email
# ---------------------------------------------------------------------------
BREVO_API_KEY = env("BREVO_API_KEY", default="")
BREVO_SENDER_EMAIL = env("BREVO_SENDER_EMAIL", default="")
BREVO_SENDER_NAME = env("BREVO_SENDER_NAME", default="Education AI")
# Used in result emails (link back to My Tests)
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://127.0.0.1:5173").rstrip("/")
OTP_TTL_SECONDS = env.int("OTP_TTL_SECONDS", default=600)
OTP_RESEND_COOLDOWN_SECONDS = env.int("OTP_RESEND_COOLDOWN_SECONDS", default=60)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
ONBOARD_PENDING_TTL_SECONDS = env.int("ONBOARD_PENDING_TTL_SECONDS", default=1800)
ONBOARD_SETUP_TOKEN_TTL_SECONDS = env.int("ONBOARD_SETUP_TOKEN_TTL_SECONDS", default=1800)

PADDLEOCR_VL_TOKEN = env("PADDLEOCR_VL_TOKEN", default="")
PADDLEOCR_VL_MODEL = env("PADDLEOCR_VL_MODEL", default="PaddleOCR-VL-1.6")

# Pilot chat page (/ask-test/) can call /api/ask/ without login when True.
# Must be False on a public VPS.
ALLOW_OPEN_ASK = env.bool("ALLOW_OPEN_ASK", default=DEBUG)

# Upload limits (bytes) — soft guard for small VPS disks
MAX_UPLOAD_BYTES = env.int("MAX_UPLOAD_BYTES", default=50 * 1024 * 1024)

# ---------------------------------------------------------------------------
# Microsoft Graph — Teams online meetings for Lectures
# https://learn.microsoft.com/en-us/graph/api/application-post-onlinemeetings
# Requires OnlineMeetings.ReadWrite.All + application access policy.
# ---------------------------------------------------------------------------
MS_GRAPH_TENANT_ID = env("MS_GRAPH_TENANT_ID", default="")
MS_GRAPH_CLIENT_ID = env("MS_GRAPH_CLIENT_ID", default="")
MS_GRAPH_CLIENT_SECRET = env("MS_GRAPH_CLIENT_SECRET", default="")
# Entra object ID or UPN of the user who organizes meetings
MS_GRAPH_ORGANIZER_USER_ID = env("MS_GRAPH_ORGANIZER_USER_ID", default="")
