"""Django settings for the homelab log viewer."""

from __future__ import annotations

import os
from pathlib import Path

from config.env import load_env

BASE_DIR = Path(__file__).resolve().parent.parent

load_env(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "django-insecure-logviewer-local-only-key"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the stylesheet without DEBUG and without a separate web server.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
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

DATA_DIR = Path(os.environ.get("LOGVIEWER_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-gb"
TIME_ZONE = os.environ.get("LOGVIEWER_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = DATA_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Compressed but not hashed: the hashed-manifest variant would make every
    # template render depend on collectstatic having already run.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Log viewer configuration -------------------------------------------------

# Upstream repository holding one folder of logs per service.
LOGS_REPO_URL = os.environ.get(
    "LOGS_REPO_URL", "https://gitlab.labjunkie.org/alex/logs.git"
)
LOGS_REPO_BRANCH = os.environ.get("LOGS_REPO_BRANCH", "main")
# Local working clone of that repository.
LOGS_REPO_DIR = Path(os.environ.get("LOGS_REPO_DIR", DATA_DIR / "logs"))
# HTTPS access token, read from .env.
GITLAB_ACCESS_TOKEN = os.environ.get("GITLAB_ACCESS_TOKEN", "")
GITLAB_TOKEN_USERNAME = os.environ.get("GITLAB_TOKEN_USERNAME", "oauth2")

# Depth of the local clone. The dashboard only ever shows the newest log, so
# there is no reason to keep the whole history on disk. 0 means a full clone.
LOGS_CLONE_DEPTH = int(os.environ.get("LOGS_CLONE_DEPTH", "50"))

# Folders in the repository that never hold service logs.
LOGS_IGNORED_DIRS = {"docs", "scripts", ".github", ".gitlab"}
LOG_FILE_SUFFIXES = (".log", ".md", ".txt")

# Command used to summarise a log. Overridden in tests.
CLAUDE_COMMAND = os.environ.get(
    "CLAUDE_COMMAND", "claude -p --dangerously-skip-permissions"
)
CLAUDE_TIMEOUT_SECONDS = int(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "300"))
# Logs are long; only the first N characters are handed to the summariser.
CLAUDE_MAX_LOG_CHARS = int(os.environ.get("CLAUDE_MAX_LOG_CHARS", "60000"))

# The Claude CLI writes a session transcript per invocation into its own config
# directory, containing the whole log we piped in. Those are write-only clutter
# for us and would otherwise grow without limit, so they are pruned after each
# summarisation. Set to "0" to keep them for debugging.
CLAUDE_PRUNE_TRANSCRIPTS = os.environ.get("CLAUDE_PRUNE_TRANSCRIPTS", "1") == "1"
# How many of the most recent transcripts to keep when pruning.
CLAUDE_TRANSCRIPT_KEEP = int(os.environ.get("CLAUDE_TRANSCRIPT_KEEP", "0"))
CLAUDE_CONFIG_DIR = Path(
    os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")
)

# How often the dashboard checks the remote for newly committed logs.
REMOTE_POLL_SECONDS = int(os.environ.get("LOGVIEWER_POLL_SECONDS", "120"))
# How often the browser asks the server for dashboard state.
BROWSER_POLL_SECONDS = int(os.environ.get("LOGVIEWER_BROWSER_POLL_SECONDS", "20"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "dashboard": {
            "handlers": ["console"],
            "level": os.environ.get("LOGVIEWER_LOG_LEVEL", "INFO"),
        }
    },
}
