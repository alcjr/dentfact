# ==========================================
# Django settings for Dentfact project
# Ubicación: C:\dentfact | Datos: C:\data
# ==========================================

import os
import logging
import logging.config
from pathlib import Path
from configparser import ConfigParser
from decouple import config as decouple_config, UndefinedValueError
import environ

# === RUTAS BASE ===
BASE_DIR = Path(__file__).parent.parent  # C:\dentfact
DATA_DIR = Path(r"C:\data")

# Crear directorios si no existen
for dir_path in [DATA_DIR / "logs", DATA_DIR / "temp", DATA_DIR / "media"]:
    dir_path.mkdir(parents=True, exist_ok=True)

LOG_DIR = DATA_DIR / "logs"
TEMP_DIR = DATA_DIR / "temp"
DB_PATH = DATA_DIR / "dentfact.sqlite3"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)

# === CONFIGURACIÓN INI (UTF-8) ===
CONFIG_PATH = BASE_DIR / 'config.ini'
ini_config = ConfigParser()
ini_config.read(CONFIG_PATH, encoding='utf-8')

# === VARIABLES DE ENTORNO (.env) ===
env = environ.Env(DEBUG=(bool, True))
ENV_FILE = BASE_DIR / '.env'
if ENV_FILE.exists():
    environ.Env.read_env(ENV_FILE)

# === SECRET KEY (SEGURA) ===
try:
    SECRET_KEY = decouple_config('SECRET_KEY')
except UndefinedValueError:
    import secrets
    SECRET_KEY = f"django-insecure-{secrets.token_urlsafe(50)}"
    print(f"SECRET_KEY generada: {SECRET_KEY[:20]}... (guarda en .env)")

# === DEBUG / SERVER ===
DEBUG = decouple_config('DEBUG', default=True, cast=bool)
SERVER = decouple_config('SERVER', default='localhost').strip()
if not SERVER:
    raise ValueError("SERVER debe estar en .env")

# === CERTIFICADOS AEAT ===
CERT_PATH = decouple_config('CERT_PATH', default=str(BASE_DIR / 'certificates' / 'certificado_aeat.p12'))
CERT_PASSWORD = decouple_config('CERT_PASSWORD', default=None)

# === EMAIL CONFIG (CORREGIDO: smtp, no smpt) ===
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = ini_config.get('smtp', 'email_host', fallback='smtp.gmail.com')
EMAIL_PORT = ini_config.getint('smtp', 'email_port', fallback=587)
EMAIL_USE_SSL = ini_config.getboolean('smtp', 'email_use_ssl', fallback=False)
EMAIL_USE_TLS = ini_config.getboolean('smtp', 'email_use_tls', fallback=True)
EMAIL_HOST_USER = ini_config.get('smtp', 'email_host_user', fallback='tuemail@gmail.com')
EMAIL_HOST_PASSWORD = decouple_config('EMAIL_HOST_PASSWORD')  # ← OBLIGATORIO EN .env

# === BASE DE DATOS ===

DB_ENGINE = decouple_config('DB_ENGINE', default='postgresql')

if DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': str(DB_PATH),
            'OPTIONS': {'timeout': 30},
            'ATOMIC_REQUESTS': True,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': decouple_config('DB_NAME', default='dentfact'),
            'USER': decouple_config('DB_USER', default='dentfact'),
            'PASSWORD': decouple_config('DB_PASSWORD'),
            'HOST': decouple_config('DB_HOST', default='localhost'),
            'PORT': decouple_config('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
            'ATOMIC_REQUESTS': True,
        }
    }

# === SEGURIDAD ===
ALLOWED_HOSTS = ['localhost', '127.0.0.1', SERVER]
CSRF_TRUSTED_ORIGINS = [f"https://{SERVER}", f"http://localhost:8000"]
CORS_ALLOWED_ORIGINS = CSRF_TRUSTED_ORIGINS

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG

# === APLICACIONES ===
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'apps.home',
    'apps.authentication',
    'corsheaders',
    'rest_framework',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# === URLS / LOGIN ===
ROOT_URLCONF = 'core.urls'
LOGIN_REDIRECT_URL = 'home:dashboard'
LOGOUT_REDIRECT_URL = '/auth/login/'
LOGIN_URL = '/auth/login/'

# === TEMPLATES ===
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'apps' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# === STATIC / MEDIA ===
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'apps' / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = DATA_DIR / 'media'

# === WSGI ===
WSGI_APPLICATION = 'core.wsgi.application'

# === INTERNACIONALIZACIÓN ===
LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_L10N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# === LOGGING ===
LOG_FILE = LOG_DIR / 'dentfact.log'
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': str(LOG_FILE),
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['file', 'console'],
        'level': 'INFO',
    },
}

# Colorlog opcional
try:
    import colorlog
    LOGGING['formatters']['console'] = {
        '()': 'colorlog.ColoredFormatter',
        'format': '%(log_color)s%(levelname)s %(module)s %(message)s',
    }
    LOGGING['handlers']['console']['formatter'] = 'console'
except ImportError:
    pass

logging.config.dictConfig(LOGGING)