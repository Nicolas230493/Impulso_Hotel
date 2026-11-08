"""Configuración de IMPULSO HOTEL.

Los valores sensibles se leen de variables de entorno (archivo .env).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(nombre, defecto=None):
    return os.environ.get(nombre, defecto)


def env_bool(nombre, defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.lower() in ("1", "true", "si", "sí", "yes", "on")


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-inseguro-cambiar-en-produccion")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.humanize",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "django_otp",
    "django_otp.plugins.otp_totp",
    # Apps del dominio
    "core",
    "saas",
    "habitaciones",
    "huespedes",
    "reservas",
    "recepcion",
    "caja",
    "facturacion",
    "inventario",
    "compras",
    "limpieza",
    "mantenimiento",
    "personal",
    "notificaciones",
    "bi",
    "integraciones",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.HotelActivoMiddleware",
    "core.middleware.DobleFactorMiddleware",
    "saas.middleware.SuscripcionMiddleware",
]

ROOT_URLCONF = "impulso.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.impulso",
            ],
        },
    },
]

WSGI_APPLICATION = "impulso.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "impulso"),
        "USER": env("POSTGRES_USER", "impulso"),
        "PASSWORD": env("POSTGRES_PASSWORD", "impulso"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5433"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_USER_MODEL = "core.Usuario"
AUTHENTICATION_BACKENDS = ["core.backends.BloqueoModelBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"

# Bloqueo tras intentos fallidos
LOGIN_MAX_INTENTOS = int(env("LOGIN_MAX_INTENTOS", "5"))
LOGIN_MINUTOS_BLOQUEO = int(env("LOGIN_MINUTOS_BLOQUEO", "15"))
# Doble factor obligatorio para administradores
REQUIRE_2FA_ADMINS = env_bool("REQUIRE_2FA_ADMINS", not DEBUG)

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True
FORMS_URLFIELD_ASSUME_HTTPS = True
USE_THOUSAND_SEPARATOR = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Impulso Hotel <no-responder@impulso.com.ar>")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["core.permisos_api.PermisoPorRol"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.api.manejador_excepciones",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "IMPULSO HOTEL API",
    "DESCRIPTION": "API REST del sistema de gestión hotelera Impulso Hotel.",
    "VERSION": "1.0.0",
}

# Celery
CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_BEAT_SCHEDULE = {
    "no-show": {"task": "reservas.tasks.marcar_no_shows", "schedule": 60 * 60},
    "cargar-noches": {"task": "caja.tasks.cargar_noches", "schedule": 60 * 60 * 6},
    "tareas-limpieza": {"task": "limpieza.tasks.generar_tareas_del_dia", "schedule": 60 * 60 * 3},
    "preventivos": {"task": "mantenimiento.tasks.generar_ordenes_preventivas", "schedule": 60 * 60 * 6},
    "reintentar-arca": {"task": "facturacion.tasks.reintentar_pendientes", "schedule": 60 * 5},
    "whatsapp-programados": {"task": "notificaciones.tasks.mensajes_programados", "schedule": 60 * 60},
    "bi-nocturno": {"task": "bi.tasks.proceso_nocturno", "schedule": 60 * 60 * 24},
    "reportes-programados": {"task": "bi.tasks.enviar_reportes_programados", "schedule": 60 * 60},
    "suscripciones": {"task": "saas.tasks.revisar_suscripciones", "schedule": 60 * 60 * 12},
}

# ARCA (ex AFIP) — facturación electrónica
ARCA_MODO = env("ARCA_MODO", "simulado")  # simulado | homologacion | produccion
ARCA_CUIT = env("ARCA_CUIT", "")
ARCA_CERT = env("ARCA_CERT", "")  # ruta al certificado .crt
ARCA_KEY = env("ARCA_KEY", "")  # ruta a la clave privada .key

# WhatsApp Business (Cloud API oficial de Meta)
WHATSAPP_MODO = env("WHATSAPP_MODO", "simulado")  # simulado | real
WHATSAPP_TOKEN = env("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = env("WHATSAPP_PHONE_ID", "")

# Pasarela de suscripciones y channel manager (decisiones abiertas)
PASARELA_MODO = env("PASARELA_MODO", "simulado")
CHANNEL_MANAGER_MODO = env("CHANNEL_MANAGER_MODO", "simulado")

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
