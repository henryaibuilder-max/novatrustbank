"""
Django settings for config project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Read .env file
load_dotenv(BASE_DIR / '.env')

def _env(key, default=None):
    return os.environ.get(key, default)

def _env_bool(key, default=False):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ('true', '1', 'yes')

def _env_int(key, default=0):
    val = os.environ.get(key)
    return int(val) if val is not None else default

def _env_list(key, default=None):
    val = os.environ.get(key)
    if val is None:
        return default or []
    return [v.strip() for v in val.split(',') if v.strip()]

# ------------------------------------------------------------------
# Core
# ------------------------------------------------------------------

SECRET_KEY = _env('SECRET_KEY', 'django-insecure-c24ior8s(7k4sa&vwlj2cxn0l7eqr6&rrb!==t(i)d6u1&4$oe')

DEBUG = _env_bool('DEBUG', default=True)

ALLOWED_HOSTS = _env_list('ALLOWED_HOSTS', default=['*'])


# ------------------------------------------------------------------
# Applications
# ------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'django_countries',
    'accounts',
    'core',
    'banking',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise must come directly after SecurityMiddleware (prod only injected below)
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

# Inject WhiteNoise in production
if not DEBUG:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

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
                'core.context_processors.nav_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------

if DEBUG:
    # Local development: SQLite
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    # Production: PostgreSQL (Aiven)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': _env('DB_NAME'),
            'USER': _env('DB_USER'),
            'PASSWORD': _env('DB_PASSWORD'),
            'HOST': _env('DB_HOST'),
            'PORT': _env('DB_PORT', '5432'),
            'OPTIONS': {
                'sslmode': _env('DB_SSLMODE', 'require'),
            },
        }
    }


# ------------------------------------------------------------------
# Password validation
# ------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ------------------------------------------------------------------
# Internationalisation
# ------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = _env('TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True


# ------------------------------------------------------------------
# Static files
# ------------------------------------------------------------------

STATIC_URL = 'static/'

STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

STATIC_ROOT = BASE_DIR / 'staticfiles'

if not DEBUG:
    # WhiteNoise compressed manifest storage for production
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ------------------------------------------------------------------
# Auth / allauth
# ------------------------------------------------------------------

AUTH_USER_MODEL = 'accounts.User'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SITE_ID = _env_int('SITE_ID', default=1)

LOGIN_URL = 'account_login'
LOGIN_REDIRECT_URL = 'core:dashboard'
LOGOUT_REDIRECT_URL = 'core:home'

ACCOUNT_ADAPTER = 'accounts.adapter.BankAccountAdapter'
ACCOUNT_SIGNUP_FORM_CLASS = 'accounts.forms.BankSignupForm'
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_EMAIL_VERIFICATION = 'optional'
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_SESSION_REMEMBER = True
ACCOUNT_LOGOUT_ON_GET = False


# ------------------------------------------------------------------
# Email
# ------------------------------------------------------------------

if DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = _env('EMAIL_HOST', 'smtp.sendgrid.net')
    EMAIL_PORT = _env_int('EMAIL_PORT', default=587)
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = _env('EMAIL_HOST_USER', '')
    EMAIL_HOST_PASSWORD = _env('EMAIL_HOST_PASSWORD', '')

DEFAULT_FROM_EMAIL = _env('DEFAULT_FROM_EMAIL', 'NovaPlusBank <noreply@novaplusbank.com>')
