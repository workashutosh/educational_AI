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
    "engagement",
    "question_bank",
    "learning",
    "homework",
    "analytics",
    "school_ops",
    "billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "billing.middleware.UsageScopeMiddleware",
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
    # Token first so a missing/expired token is a 401 (with WWW-Authenticate),
    # which mobile clients use as the "sign in again" signal.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "config.schema.ClassKitAutoSchema",
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

# Celery Beat — engagement digests (run: celery -A config beat -l info)
from datetime import timedelta  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "engagement-teacher-daily-digest": {
        "task": "engagement.send_teacher_daily_digests",
        "schedule": timedelta(hours=24),
        # Prefer crontab in production; timedelta keeps deps light for pilot
    },
    "engagement-student-weekly-digest": {
        "task": "engagement.send_student_weekly_digests",
        "schedule": timedelta(days=7),
    },
}

# School-local calendar for streaks / digests
SCHOOL_DEFAULT_TZ = env("SCHOOL_DEFAULT_TZ", default="Asia/Kolkata")

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
CHUNK_OVERLAP_CHARS = env.int("CHUNK_OVERLAP_CHARS", default=640)
# Cosine similarity floor after quality demotion; below this → no LLM call
RAG_MIN_SCORE = env.float("RAG_MIN_SCORE", default=0.22)
# Keep small — large top_k + neighbor expansion blows Groq free-tier TPM (12k).
RAG_TOP_K = env.int("RAG_TOP_K", default=5)
RAG_EXPAND_NEIGHBORS = env.bool("RAG_EXPAND_NEIGHBORS", default=True)
RAG_MAX_CONTEXT_CHARS = env.int("RAG_MAX_CONTEXT_CHARS", default=7000)
RAG_MAX_CHUNK_CHARS = env.int("RAG_MAX_CHUNK_CHARS", default=1100)

# ---------------------------------------------------------------------------
# Chat LLM — DeepSeek preferred (OpenAI-compatible), Groq fallback.
# Used by /api/ask/, PPT, mock tests, micro-quiz, RAG harness.
# Docs: https://api-docs.deepseek.com/
# OCR (PaddleOCR-VL) is unrelated — do not route OCR through this.
# ---------------------------------------------------------------------------
DEEPSEEK_API_KEY = env("DEEPSEEK_API_KEY", default="")
DEEPSEEK_MODEL = env("DEEPSEEK_MODEL", default="deepseek-v4-flash")
DEEPSEEK_BASE_URL = env("DEEPSEEK_BASE_URL", default="https://api.deepseek.com")
# disabled | enabled — thinking mode (DeepSeek V4); keep disabled for latency
DEEPSEEK_THINKING = env("DEEPSEEK_THINKING", default="disabled")
DEEPSEEK_REASONING_EFFORT = env("DEEPSEEK_REASONING_EFFORT", default="high")

GROQ_API_KEY = env("GROQ_API_KEY", default="")
GROQ_MODEL = env("GROQ_MODEL", default="llama-3.3-70b-versatile")

# ---------------------------------------------------------------------------
# RAG harness (rag_harness.agent.run_query) — shared query/retrieval layer
# for future agents. Reuses DEEPSEEK_* / GROQ_* / PAGEINDEX_MODEL above.
# ---------------------------------------------------------------------------
RAG_HARNESS_TOP_K = env.int("RAG_HARNESS_TOP_K", default=5)
RAG_HARNESS_MAX_CONTEXT_CHARS = env.int("RAG_HARNESS_MAX_CONTEXT_CHARS", default=12000)

# ---------------------------------------------------------------------------
# Brevo — transactional email for onboarding OTP
# https://developers.brevo.com/docs/send-a-transactional-email
# ---------------------------------------------------------------------------
BREVO_API_KEY = env("BREVO_API_KEY", default="")
BREVO_SENDER_EMAIL = env("BREVO_SENDER_EMAIL", default="")
BREVO_SENDER_NAME = env("BREVO_SENDER_NAME", default="ClassKit")
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
# Preferred: delegated OAuth (Connect Microsoft → POST /me/onlineMeetings).
# Optional app-only: OnlineMeetings.ReadWrite.All + application access policy.
# ---------------------------------------------------------------------------
MS_GRAPH_TENANT_ID = env("MS_GRAPH_TENANT_ID", default="")
MS_GRAPH_CLIENT_ID = env("MS_GRAPH_CLIENT_ID", default="")
MS_GRAPH_CLIENT_SECRET = env("MS_GRAPH_CLIENT_SECRET", default="")
# Entra object ID or UPN of the user who organizes meetings (app-only mode)
MS_GRAPH_ORGANIZER_USER_ID = env("MS_GRAPH_ORGANIZER_USER_ID", default="")
# Delegated OAuth (teacher Connect Microsoft) — no access policy needed
MS_GRAPH_REDIRECT_URI = env(
    "MS_GRAPH_REDIRECT_URI",
    default="http://127.0.0.1:8000/api/lectures/teams/callback/",
)
# organizations = any work/school tenant; or set to your tenant id for single-tenant apps
MS_GRAPH_OAUTH_TENANT = env("MS_GRAPH_OAUTH_TENANT", default="organizations")

# ---------------------------------------------------------------------------
# Retrieval vector backend — auto uses pgvector when ingestion 0007 could
# create the `embedding_vec` column; json = always brute-force numpy.
# EMBEDDING_DIM must match EMBEDDING_MODEL (bge-small / multilingual MiniLM = 384).
# Set EMBEDDING_MULTILINGUAL=True after switching to a multilingual model so
# non-English questions are embedded directly (no translation step).
# ---------------------------------------------------------------------------
RAG_VECTOR_BACKEND = env("RAG_VECTOR_BACKEND", default="auto")
EMBEDDING_DIM = env.int("EMBEDDING_DIM", default=384)
EMBEDDING_MULTILINGUAL = env.bool("EMBEDDING_MULTILINGUAL", default=False)

# ---------------------------------------------------------------------------
# Speech-to-text (voice questions + lecture recordings). OpenAI-compatible
# Whisper endpoint; defaults to Groq with GROQ_API_KEY.
# ---------------------------------------------------------------------------
TRANSCRIPTION_API_URL = env("TRANSCRIPTION_API_URL", default="")
TRANSCRIPTION_API_KEY = env("TRANSCRIPTION_API_KEY", default="")
TRANSCRIPTION_MODEL = env("TRANSCRIPTION_MODEL", default="whisper-large-v3-turbo")
TRANSCRIPTION_MAX_UPLOAD_BYTES = env.int("TRANSCRIPTION_MAX_UPLOAD_BYTES", default=25 * 1024 * 1024)
LECTURE_RECORDING_MAX_BYTES = env.int("LECTURE_RECORDING_MAX_BYTES", default=500 * 1024 * 1024)

# ---------------------------------------------------------------------------
# Billing (Razorpay Orders + Checkout) and usage metering
# ---------------------------------------------------------------------------
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
BILLING_PRICE_STANDARD_PAISE = env.int("BILLING_PRICE_STANDARD_PAISE", default=299_900)
BILLING_PRICE_PRO_PAISE = env.int("BILLING_PRICE_PRO_PAISE", default=799_900)
# Block LLM calls once a school exceeds its plan's monthly token allowance.
BILLING_ENFORCE_AI_QUOTA = env.bool("BILLING_ENFORCE_AI_QUOTA", default=True)
# Cost estimates only (USD). {model: [input_per_1M_tokens, output_per_1M_tokens]}
LLM_PRICING_USD_PER_MTOK = env.json(
    "LLM_PRICING_USD_PER_MTOK",
    default={
        "deepseek-v4-flash": [0.27, 1.10],
        "llama-3.3-70b-versatile": [0.59, 0.79],
        "gemini/gemini-2.5-flash": [0.30, 2.50],
        "default": [0.50, 1.50],
    },
)
OCR_COST_USD_PER_PAGE = env.float("OCR_COST_USD_PER_PAGE", default=0.0015)
TRANSCRIPTION_COST_USD_PER_MINUTE = env.float("TRANSCRIPTION_COST_USD_PER_MINUTE", default=0.0007)

CELERY_BEAT_SCHEDULE.update(
    {
        "billing-expire-subscriptions": {
            "task": "billing.expire_subscriptions",
            "schedule": timedelta(hours=6),
        },
        "school-ops-parent-weekly-digest": {
            "task": "school_ops.send_parent_weekly_digests",
            "schedule": timedelta(days=7),
        },
    }
)

# Uniform API errors: every 4xx/5xx carries `detail` (+ `errors` for field issues).
REST_FRAMEWORK["EXCEPTION_HANDLER"] = "config.api.exception_handler"
SPECTACULAR_SETTINGS.update(
    {
        "TITLE": "ClassKit API",
        "DESCRIPTION": (
            "School-scoped notes → RAG chat, mock tests, question bank & papers, homework, "
            "flashcards, doubts, lectures (recordings, attendance), analytics, parent portal, "
            "billing. Authenticate with `Authorization: Token <key>` from /api/auth/login/. "
            "All routes are also served under /api/v1/ for mobile clients."
        ),
        "VERSION": "1.0.0",
        "COMPONENT_SPLIT_REQUEST": True,
        "SCHEMA_PATH_PREFIX": r"/api/",
        "PREPROCESSING_HOOKS": ["config.api.drop_versioned_duplicates"],
        "ENUM_NAME_OVERRIDES": {
            "BankQuestionTypeEnum": "question_bank.models.QuestionItem.TYPE_CHOICES",
            "DifficultyEnum": "question_bank.models.QuestionItem.DIFFICULTY_CHOICES",
            "DeckVisibilityEnum": "learning.models.FlashcardDeck.VISIBILITY_CHOICES",
        },
    }
)

# Tests run Celery tasks inline (no broker needed); external calls are mocked.
if len(sys.argv) > 1 and sys.argv[1] == "test":
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = False
    BILLING_ENFORCE_AI_QUOTA = True
