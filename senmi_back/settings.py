import os
from pathlib import Path
from datetime import timedelta
import dj_database_url
from dotenv import load_dotenv
import cloudinary

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


# =========================
# SECURITY
# =========================

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = os.getenv("DEBUG", "False").strip().lower() == "true"

ALLOWED_HOSTS = [
    "api.senmi.com.ng",
    "senmiback-production.up.railway.app",
    ".railway.app",
    "127.0.0.1",
    "localhost"
]


# =========================
# DATABASE (FIXED - NO CONFLICTS)
# =========================

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# =========================
# APPS
# =========================

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'corsheaders',
    'rest_framework',
    'channels',

    'cloudinary',
    'cloudinary_storage',

    'senmi',
]


# =========================
# MIDDLEWARE
# =========================

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',

    'corsheaders.middleware.CorsMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'senmi_back.urls'
WSGI_APPLICATION = 'senmi_back.wsgi.application'
ASGI_APPLICATION = 'senmi_back.asgi.application'


# =========================
# REDIS
# =========================

REDIS_URL = os.getenv("REDIS_URL")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL] if REDIS_URL else [],
        },
    },
}


# =========================
# AUTH
# =========================

AUTH_USER_MODEL = 'senmi.User'


# =========================
# REST FRAMEWORK
# =========================

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    )
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# =========================
# STATIC FILES
# =========================

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


# =========================
# CLOUDINARY
# =========================

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"


# =========================
# BUSINESS LOGIC
# =========================

COMMISSION_RATE = float(os.getenv("COMMISSION_RATE", 0.05))
BASE_FEE = 1000
PER_KM_RATE = 205
FUEL_MULTIPLIER = 1.39


# =========================
# SECURITY HEADERS
# =========================

CSRF_TRUSTED_ORIGINS = [
    "https://api.senmi.com.ng",
    "https://senmiback-production.up.railway.app"
]

# All media uploads go to Cloudinary
DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"