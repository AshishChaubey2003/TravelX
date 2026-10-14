from pathlib import Path
import os
import dj_database_url
from decouple import config, Csv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config('DEBUG', default=False, cast=bool)

# --- F-22 Phase 1.1: fail fast in production if SECRET_KEY is not supplied. ---
# Local dev keeps the existing insecure fallback (DEBUG=True only).
#
# The literal string below is used ONLY when DEBUG=True (local development),
# and ONLY if the SECRET_KEY env var is not set. It MUST NEVER be the key
# used in production — the check above raises ImproperlyConfigured if someone
# tries to run with DEBUG=False and no SECRET_KEY env var, so the insecure
# key cannot leak into a real deploy. Set SECRET_KEY in your .env (see
# .env.example) to override it even in dev. See audit docs/audit/FINDINGS.md
# F-R1 for the reasoning behind keeping the fallback for DX.
_SECRET_KEY_ENV = config('SECRET_KEY', default=None)
if not DEBUG and not _SECRET_KEY_ENV:
    raise ImproperlyConfigured(
        "SECRET_KEY environment variable is required when DEBUG=False (production). "
        "Set it in the environment before starting the app."
    )
SECRET_KEY = _SECRET_KEY_ENV or 'django-insecure-travelx-dev-key-change-in-production'

# Csv() splits on commas AND strips surrounding whitespace from each host and
# drops empty entries. A bare .split(',') did neither, so a value entered the
# natural way in a dashboard ("host-a, host-b") kept a leading space on every
# entry after the first and never matched the incoming Host header
# (DisallowedHost). Same caster the health-check settings below already use.
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,0.0.0.0,web', cast=Csv())

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'django_filters',
    'django_celery_beat',

    # TravelX apps
    'apps.core',
    'apps.accounts',
    'apps.locations',
    'apps.hotels',
    'apps.adventures',
    'apps.vehicles',
    'apps.bookings',
    'apps.payments',
    'apps.kafka_events',
    'apps.ai_agent',
]

MIDDLEWARE = [
    'apps.core.middleware.RequestIDMiddleware',        # H01
    'apps.core.metrics_middleware.MetricsMiddleware',  # H05
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- F-22 Phase 1.2: fail fast in production if DATABASE_URL is not supplied. ---
# Local dev / existing SQLite workflow is preserved (DEBUG=True only).
_DATABASE_URL_ENV = config('DATABASE_URL', default=None)
if not DEBUG and not _DATABASE_URL_ENV:
    raise ImproperlyConfigured(
        "DATABASE_URL environment variable is required when DEBUG=False (production)."
    )
DATABASES = {
    'default': dj_database_url.config(
        default=_DATABASE_URL_ENV or 'postgresql://travelx_user:travelx_pass@db:5432/travelx_db',
        conn_max_age=600,
    )
}

# Redis Cache — falls back to in-memory if Redis is not configured
if config('USE_REDIS', default=False, cast=bool):
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': config('REDIS_URL', default='redis://localhost:6379/0'),
            'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # F-22 Phase 2/3: scoped throttles. These do NOT apply globally -
    # only a view that explicitly sets throttle_scope to one of these keys
    # is affected. No other endpoint's behavior changes.
    'DEFAULT_THROTTLE_RATES': {
        'ai_plan_trip': config('AI_PLAN_TRIP_THROTTLE_RATE', default='10/min'),
        'otp_verify': config('OTP_VERIFY_THROTTLE_RATE', default='5/min'),
        'otp_resend': config('OTP_RESEND_THROTTLE_RATE', default='3/min'),
        # F-001: login throttles. `login` is IP-keyed (ScopedRateThrottle
        # default), `login_account` is username-keyed (apps/accounts/throttles.py
        # LoginAccountThrottle). Both must pass. Numbers are conservative so a
        # genuine user who typos a few times is not locked out.
        'login': config('LOGIN_THROTTLE_RATE', default='20/min'),
        'login_account': config('LOGIN_ACCOUNT_THROTTLE_RATE', default='10/5min'),
    },
}

# JWT
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}

# Celery
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://redis:6379/2')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://redis:6379/2')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Kafka
KAFKA_BROKER = config('KAFKA_BROKER', default='kafka:29092')

# Razorpay
RAZORPAY_KEY_ID = config('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = config('RAZORPAY_KEY_SECRET', default='')
RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')

# Groq
GROQ_API_KEY = config('GROQ_API_KEY', default='')

# Email
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')

# Make the console email backend resilient to characters the terminal can't
# display (e.g. emoji on a Windows cp1252 console). This only changes how
# such characters are shown in console output; it does not alter the
# EMAIL_BACKEND choice, the email content sent via send_mail(), or anything
# about production SMTP delivery. stdout is what Django's console backend
# writes to; stderr is included because the dev server's own log output
# shares the same console and should not crash either.
if EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
    import sys
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors='backslashreplace')
        except (AttributeError, ValueError):
            pass
EMAIL_HOST = config('EMAIL_HOST', default='smtp.mailtrap.io')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = True
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=10, cast=int)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@travelx.com')

# F-010 Decision A: PBKDF2 stays the PREFERRED hasher for user passwords —
# their behaviour does not change at all (existing hashes verify as before
# and are NOT re-hashed on login). Argon2 is listed SECOND purely so
# make_password(..., hasher='argon2') can resolve it for OTP hashing
# (apps/accounts/models.py). Moving Argon2 first (Decision B — re-hashes
# every user's password on next login, adds argon2 to the auth hot path) is
# explicitly out of scope and needs its own approval.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static & Media
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
# F-015: STATICFILES_STORAGE is deprecated in Django 5.1+. The STORAGES dict
# below replaces it with the same whitenoise backend (byte-identical behaviour)
# and silences the RemovedInDjango51Warning that was polluting test output.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ---------------------------------------------------------------------------
# F-002: production security hardening. Only applied when DEBUG=False, so dev
# is untouched. Every setting reads from env with a conservative default:
#   - SECURE_SSL_REDIRECT defaults OFF — turning it on without a correct
#     reverse-proxy header causes redirect loops, so operators opt in only
#     once their load balancer is confirmed to forward X-Forwarded-Proto.
#   - SECURE_PROXY_SSL_HEADER is only honoured when TRUST_FORWARDED_PROTO=True.
#     If no trusted proxy sits in front of Django, do NOT turn this on, or
#     an attacker could spoof the header and bypass redirect-to-HTTPS.
#   - Cookies are marked Secure by default: safe because they only matter
#     over an HTTPS connection anyway.
#   - HSTS defaults to 0 seconds (OFF). Enable only after a successful HTTPS
#     deploy on a domain you intend to keep on HTTPS forever.
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
    if config('TRUST_FORWARDED_PROTO', default=False, cast=bool):
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)
    CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool)
    SECURE_HSTS_PRELOAD = config('SECURE_HSTS_PRELOAD', default=False, cast=bool)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    SESSION_COOKIE_SAMESITE = config('SESSION_COOKIE_SAMESITE', default='Lax')
    CSRF_COOKIE_SAMESITE = config('CSRF_COOKIE_SAMESITE', default='Lax')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS — allow local + your deployed frontend
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000'
).split(',')

# Trust the deployed backend host for CSRF (Render)
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:3000'
).split(',')

# ---------------------------------------------------------------------------
# Logging (H01): structured logs + request correlation IDs
# LOG_FORMAT=json (default, for containers/prod) or plain (readable in dev)
# ---------------------------------------------------------------------------
LOG_LEVEL = config('LOG_LEVEL', default='INFO').upper()
LOG_FORMAT = config('LOG_FORMAT', default='json').lower()
if LOG_FORMAT not in ('json', 'plain'):
    LOG_FORMAT = 'json'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'request_id': {'()': 'apps.core.logging_utils.RequestIDFilter'},
    },
    'formatters': {
        'json': {'()': 'apps.core.logging_utils.JsonFormatter'},
        'plain': {
            'format': '%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': LOG_FORMAT,
            'filters': ['request_id'],
        },
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        # Override Django's defaults so lines are not duplicated / unstructured.
        'django': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        # Our own per-request line.
        'travelx.request': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

# Keep Celery from replacing the root logger config above.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

# ---------------------------------------------------------------------------
# Health checks (H02)
# Comma-separated subset of: database, cache, broker, kafka
# ---------------------------------------------------------------------------
from decouple import Csv  # noqa: E402

HEALTH_READINESS_CHECKS = config(
    'HEALTH_READINESS_CHECKS', default='database,cache', cast=Csv()
)

# ---------------------------------------------------------------------------
# Dependency monitoring (H04)
# ---------------------------------------------------------------------------
# Token for GET /health/dependencies/ (header X-Monitoring-Token).
# Empty = endpoint disabled (404). Keep the real value in the ignored .env.
MONITORING_TOKEN = config('MONITORING_TOKEN', default='')

MONITOR_INTERVAL_SECONDS = config('MONITOR_INTERVAL_SECONDS', default=60, cast=int)
MONITOR_OUTBOX_MAX_PENDING = config('MONITOR_OUTBOX_MAX_PENDING', default=100, cast=int)
MONITOR_OUTBOX_MAX_AGE_SECONDS = config('MONITOR_OUTBOX_MAX_AGE_SECONDS', default=300, cast=int)
MONITOR_DEAD_LETTER_MAX = config('MONITOR_DEAD_LETTER_MAX', default=0, cast=int)

# Picked up by Celery beat (config_from_object, namespace CELERY).
# If you already define CELERY_BEAT_SCHEDULE, merge this entry into it.
CELERY_BEAT_SCHEDULE = {
    'monitor-dependencies': {
        'task': 'apps.core.tasks.monitor_dependencies',
        'schedule': MONITOR_INTERVAL_SECONDS,
    },
}

# ---------------------------------------------------------------------------
# Application metrics (H05)
# ---------------------------------------------------------------------------
# Bearer token for GET /metrics. Empty = endpoint disabled (404).
# Keep the real value in the ignored .env, never in source.
METRICS_TOKEN = config('METRICS_TOKEN', default='')

# ---------------------------------------------------------------------------
# Booking / payment flow health (H06)
# ---------------------------------------------------------------------------
# A PENDING booking/payment older than this is counted as "stale".
FLOW_PENDING_STALE_MINUTES = config('FLOW_PENDING_STALE_MINUTES', default=30, cast=int)

# F-005: a PENDING booking older than this with NO Payment row is expired by
# the (dormant, manually-invoked) sweep in apps/bookings/tasks_expiry.py.
# The sweep has NO beat schedule entry; enabling it is a separate approval.
BOOKING_PENDING_EXPIRY_MINUTES = config('BOOKING_PENDING_EXPIRY_MINUTES', default=30, cast=int)

# F-008: an outbox row stuck IN_FLIGHT longer than this is returned to
# PENDING (lease cleared) by outbox.rescue_stale_inflight_events — a manual/
# unscheduled watchdog. Must comfortably exceed the relay's flush timeout
# (10s) + the producer's message.timeout.ms (5s); 60s gives 4x headroom.
OUTBOX_INFLIGHT_RESCUE_SECONDS = config('OUTBOX_INFLIGHT_RESCUE_SECONDS', default=60, cast=int)
# H04 reports "degraded" when stale pending bookings (or payments) exceed this.
# Abandoned checkouts are normal, so this is a volume limit, not zero.
FLOW_MAX_STALE_PENDING = config('FLOW_MAX_STALE_PENDING', default=50, cast=int)
# Booking/payment inconsistencies tolerated (money and status disagree). Keep 0.
FLOW_MAX_INCONSISTENT = config('FLOW_MAX_INCONSISTENT', default=0, cast=int)

# -- H03: error tracking (Sentry). Disabled unless SENTRY_DSN is set. --
SENTRY_DSN = config('SENTRY_DSN', default='')
SENTRY_ENVIRONMENT = config('SENTRY_ENVIRONMENT', default='development')
SENTRY_RELEASE = config('SENTRY_RELEASE', default='') or None
SENTRY_TRACES_SAMPLE_RATE = config('SENTRY_TRACES_SAMPLE_RATE', default=0.0, cast=float)

if SENTRY_DSN:
    from apps.core.error_tracking import init_sentry
    init_sentry(
        dsn=SENTRY_DSN,
        environment=SENTRY_ENVIRONMENT,
        release=SENTRY_RELEASE,
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
    )

# ---------------------------------------------------------------------------
# Demo-mode inline consumer (DEMO_INLINE_CONSUMER)
# ---------------------------------------------------------------------------
# When True, booking and payment events are processed synchronously via
# transaction.on_commit() instead of requiring Kafka + a background consumer.
# This enables a zero-dependency demo on Render (no Kafka, no Redis, no
# workers). Default: False — production uses the full Kafka pipeline.
#
# How it works:
#   After the transaction that writes an outbox event commits, an on_commit
#   callback calls process_event_once() with the same event_id that the
#   outbox row carries. If (and when) a real Kafka consumer processes the
#   same event later, the ProcessedEvent ledger deduplicates it.
#
# If the inline call fails, the primary state (Payment, Booking, outbox row)
# is already committed. The booking status transition is deferred — equivalent
# to Kafka consumer lag in the full stack. The outbox row remains for manual
# replay (manage.py recovery replay-events --all).
#
# Celery eager mode: with no Redis broker, .delay() executes synchronously.
# CELERY_TASK_EAGER_PROPAGATES=False ensures that an email-sending failure
# does not crash the inline path or the webhook response.
DEMO_INLINE_CONSUMER = config('DEMO_INLINE_CONSUMER', default=False, cast=bool)

if DEMO_INLINE_CONSUMER:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = False
