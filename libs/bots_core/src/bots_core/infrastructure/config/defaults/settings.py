# -*- coding: utf-8 -*-
"""Django settings for bots project."""

import os
import platform

import bots
from bots.botsinit import BotsConfig


BOTS_PATH = bots.__path__[0]

# BOTSENV
BOTSENV = os.environ.get("BOTSENV") or "default"
BOTS_CONFIG_DIR = os.path.dirname(__file__)
BOTSENV_PATH = os.path.dirname(BOTS_CONFIG_DIR)

# BOTSSYS
config = BotsConfig()
config.read(os.path.join(BOTS_CONFIG_DIR, 'bots.ini'))
BOTSSYS = config.get('directories', 'botssys', 'botssys')
if os.path.sep not in BOTSSYS:
    # Set absolute botssys path from botsenv path
    BOTSSYS = os.path.join(BOTSENV_PATH, BOTSSYS)

HOSTNAME = platform.node()

# *******settings for sending bots error reports via email**********************************
MANAGERS = (
    # bots will send error reports to the MANAGERS
    ('name_manager', 'adress@test.com'),
)
EMAIL_HOST = 'localhost'    # Default: 'localhost'
EMAIL_PORT = '25'           # Default: 25
EMAIL_USE_TLS = False       # Default: False
EMAIL_HOST_USER = ""        # Default: '' Username to use for the SMTP server defined in EMAIL_HOST.
EMAIL_HOST_PASSWORD = ""    # Default: '' PASSWORD to use for the SMTP server defined in EMAIL_HOST.
# If EMAIL_HOST_USER is empty, Django won't attempt authentication.
SERVER_EMAIL = f"{BOTSENV}@{HOSTNAME}"  # Sender of bots error reports. Default: 'root@localhost'
# EMAIL_SUBJECT_PREFIX = ''   # This is prepended on email subject.

# *********database settings*************************
# SQLite database (default bots database)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BOTSSYS, 'sqlitedb', 'botsdb'),
        "USER": "",         # not needed for SQLite
        "PASSWORD": "",     # not needed for SQLite
        "HOST": "",         # not needed for SQLite
        "PORT": "",         # not needed for SQLite
        "OPTIONS": {
            "init_command": "PRAGMA synchronous=OFF;",
            "transaction_mode": "EXCLUSIVE",
            "timeout": 99.0,
            # "detect_types": sqlite3.PARSE_DECLTYPES,
        },
    }
}
# # MySQL:
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.mysql',
#         'NAME': 'botsdb',
#         'USER': 'bots',
#         'PASSWORD': 'botsbots',
#         'HOST': '127.0.0.1',
#         'PORT': '3306',
#         'OPTIONS': {'use_unicode':True,'charset':'utf8','init_command': 'SET storage_engine=INNODB'},
#     }
# }
# PostgreSQL:
# DATABASES = {
#     'default': {
#         "ENGINE": "django.db.backends.postgresql",
#         'NAME': 'botsdb',
#         'USER': 'bots',
#         'PASSWORD': 'botsbots',
#         'HOST': '127.0.0.1',
#         'PORT': '5432',
#         "OPTIONS": {
#             "client_encoding": "utf-8",
#         },
#     }
# }

# *********setting date/time zone and formats *************************
# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'Europe/Paris'
# Bots engine always use localtime
USE_TZ = False

# ******language code/internationalization*************************
# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'
# LANGUAGE_CODE = 'nl'
# LANGUAGE_CODE = 'fr'
USE_I18N = True

# *************************************************************************
# *********other django setting. please consult django docs.***************
# *************************************************************************
# *************************************************************************

# *********path settings*************************
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BOTSSYS, 'static')
ROOT_URLCONF = 'bots.urls'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/bots/home'
LOGOUT_URL = '/logout/'
# LOGOUT_REDIRECT_URL = # not such parameter; is set in urls.py
ALLOWED_HOSTS = ['*']

# *********sessions, cookies, log out time*************************
SESSION_EXPIRE_AT_BROWSER_CLOSE = True    # True: always log in when browser is closed
SESSION_COOKIE_AGE = 3600                 # seconds a user needs to login when no activity
SESSION_SAVE_EVERY_REQUEST = True         # if True: SESSION_COOKIE_AGE is interpreted as: since last activity
SESSION_COOKIE_NAME = f"bots_sessionid_{BOTSENV}"
CSRF_COOKIE_NAME = f"bots_csrftoken_{BOTSENV}"

# set in bots.ini
# DEBUG = True
# TEMPLATE_DEBUG = DEBUG
SITE_ID = 1
# Make this unique, and don't share it with anybody.
SECRET_KEY = 'm@-u37qiujmeqfbu$daaaaz)sp^7an4u@h=wfx9dd$$$zl2i*x9#awojdc'

# *******includes for django*************************************************************************
LOCALE_PATHS = (
    os.path.join(BOTS_PATH, 'locale'),
)

# save uploaded file (=plugin) always to file. no path for temp storage is used, so system default is used.
FILE_UPLOAD_HANDLERS = (
    'django.core.files.uploadhandler.TemporaryFileUploadHandler',
)

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bots',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            os.path.join(BOTS_PATH, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'bots.bots_context.set_context',
            ],
        },
    },
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]
